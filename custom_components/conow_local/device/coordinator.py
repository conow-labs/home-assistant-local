"""Unified Modbus data update coordinator.

One coordinator polls the active register map (v1 or v2) and exposes a flat
``{code: {raw, value, display}}`` snapshot to both the HA entities and the
grouping panel.  v1 keeps the 5 s interval, v2 polls every 30 s; both work
over RTU and TCP.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any, TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ..maps import model as map_model
from . import handoff
from ..client import (
    INTER_FRAME_DELAY_S,
    POST_WRITE_DELAY_S,
    VERIFY_CODE_START,
    ConowConnectError,
    ConowExceptionResponseError,
    ConowModbusClient,
    ConowModbusError,
    encode_verify_code,
)
from ..const import (
    CONF_LAST_MAP_VERSION,
    CONF_MODBUS_BAUDRATE,
    CONF_MODBUS_HOST,
    CONF_MODBUS_MODE,
    CONF_MODBUS_PORT,
    CONF_MODBUS_SLAVE,
    CONF_MODBUS_TCP_PORT,
    CONF_POLL_INTERVAL,
    CONF_TCP_VERIFY_CODE,
    DEFAULT_BAUDRATE,
    DEFAULT_TCP_PORT,
    DOMAIN,
    LOGGER,
    MODBUS_MODE_TCP_DIRECT,
    MODBUS_POLL_INTERVAL,
    MODBUS_TCP_MODES,
    POLL_INTERVAL_OPTIONS,
)
from ..maps.registry import (
    FIRMWARE_VERSION_ADDRESS,
    FIRMWARE_VERSION_REGISTERS,
    MAP_V1,
    MAP_V2,
    format_version,
    map_source,
    parse_firmware_version,
    select_map,
)

_T = TypeVar("_T")

PANEL_POLL_INTERVAL_S = 30

# The block that carries the live measurements.  A device that cannot answer
# it is offline: reporting the other blocks would mix fresh and stale values.
KEY_BLOCK = "monitoring"


def configured_poll_interval(entry: ConfigEntry) -> int | None:
    """Return the panel-configured interval, or None when unset or invalid."""
    try:
        seconds = int(entry.options.get(CONF_POLL_INTERVAL))
    except (TypeError, ValueError):
        return None
    return seconds if seconds in POLL_INTERVAL_OPTIONS else None


def read_map_blocks(
    client: ConowModbusClient, map_version: str
) -> dict[str, list[int] | None]:
    """Read every block of one map with one connected client."""
    blocks: dict[str, list[int] | None] = {}
    for index, (block, (start, count)) in enumerate(
        map_model.get_block_spans(map_version).items()
    ):
        if index:
            time.sleep(INTER_FRAME_DELAY_S)
        try:
            blocks[block] = client.read_holding_registers(start, count)
        except ConowConnectError:
            # No link at all: every later block would only repeat the same
            # connect timeout, so stop the poll here.
            raise
        except ConowExceptionResponseError as exc:
            if exc.device_level:
                # Exception 4/5/6 describes the link (another client, stale
                # verification code, RTU external control off), not this
                # block: the remaining reads would fail the same way.
                raise
            LOGGER.debug(
                "Map %s: block %s refused: %s", map_version, block, exc
            )
            blocks[block] = None
        except ConowModbusError:
            LOGGER.debug("Map %s: block %s read failed", map_version, block)
            blocks[block] = None
    return blocks


def decode_required_blocks(
    blocks: dict[str, list[int] | None], map_version: str
) -> dict[str, dict[str, Any]]:
    """Decode a snapshot, requiring the live-measurement block.

    A partial read is not a usable snapshot: entities must either show fresh
    values or become unavailable, never keep the previous poll's numbers.
    Raises ``ConowModbusError`` when the map's key block did not answer, so
    callers can report the whole device as offline.
    """
    if KEY_BLOCK in blocks and blocks[KEY_BLOCK] is None:
        raise ConowModbusError(
            f"{map_source(map_version)}: block {KEY_BLOCK!r} is not readable"
        )
    return decode_map_blocks(blocks, map_version)


def decode_map_blocks(
    blocks: dict[str, list[int] | None], map_version: str
) -> dict[str, dict[str, Any]]:
    """Decode the successfully read blocks into one flat snapshot."""
    decoded: dict[str, dict[str, Any]] = {}
    for block, words in blocks.items():
        if words is not None:
            decoded.update(map_model.decode_block(block, words, map_version))
    return decoded


def write_register_ops(
    client: ConowModbusClient, ops: list[tuple[int, list[int]]]
) -> None:
    """Write ``(address, words)`` operations back to back.

    Every frame goes out as FC 0x10, including single-register writes: the
    machine answers FC 0x06 with an exception (0x86/03) instead of writing.
    """
    for index, (address, words) in enumerate(ops):
        if index:
            time.sleep(INTER_FRAME_DELAY_S)
        client.write_registers(address, words)
        time.sleep(POST_WRITE_DELAY_S)


class ConowLocalCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll a CONOW device over Modbus RTU or TCP."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        self.entry = entry
        self.mode = entry.data.get(CONF_MODBUS_MODE, "rtu")
        self.slave = entry.data[CONF_MODBUS_SLAVE]
        if self.mode in MODBUS_TCP_MODES:
            self.host = entry.data[CONF_MODBUS_HOST]
            self.tcp_port = entry.data.get(CONF_MODBUS_TCP_PORT, DEFAULT_TCP_PORT)
            self.port = None
            self.baudrate = None
        else:
            self.host = None
            self.port = entry.data[CONF_MODBUS_PORT]
            self.baudrate = entry.data[CONF_MODBUS_BAUDRATE]
        self._lock = threading.Lock()
        self._client: ConowModbusClient | None = None
        # A device-level refusal (4 = another client holds the machine, 5 = the
        # verification code is stale) means this client can no longer read or
        # write anything: every later frame would be refused the same way.  The
        # refusal is kept and replayed without touching the device until a new
        # code is accepted or the entry is reloaded.
        self._blocked: ConowExceptionResponseError | None = None
        # Direct TCP entries carry the challenge code that guards the machine.
        self.verify_code: str | None = (
            entry.data.get(CONF_TCP_VERIFY_CODE)
            if self.mode == MODBUS_MODE_TCP_DIRECT
            else None
        )
        # v1 is the default; async_probe_map_version() may upgrade this.
        self.map_version = MAP_V1
        self.firmware_version: tuple[int, ...] | None = None
        # A panel-configured interval overrides the map default; the map is
        # only known after the probe, so the effective value is resolved in
        # _apply_poll_interval().
        self._configured_poll_interval = configured_poll_interval(entry)
        self.poll_interval_seconds = MODBUS_POLL_INTERVAL
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=MODBUS_POLL_INTERVAL),
        )

    def _connect(self) -> ConowModbusClient:
        """Open or reuse the Modbus client (serial or TCP)."""
        if self._client is None:
            adopted = None
            if self.mode in MODBUS_TCP_MODES:
                # The config flow probes the same endpoint in the same
                # process; adopting that verified link avoids a second
                # connection and a second verification-code write.
                adopted = handoff.take(
                    handoff.connection_key(
                        self.mode,
                        self.host,
                        self.tcp_port,
                        self.slave,
                        self.verify_code,
                    )
                )
            if adopted is not None:
                LOGGER.debug(
                    "TCP: adopted the verified connection to %s", self.host
                )
                self._client = adopted
                return self._client
            client = ConowModbusClient(
                self.port,
                host=self.host,
                tcp_port=self.tcp_port if self.host is not None else DEFAULT_TCP_PORT,
                slave=self.slave,
                baudrate=self.baudrate or DEFAULT_BAUDRATE,
            )
            client.connect()
            self._client = client
        return self._client

    def _reset_client(self) -> None:
        """Close the client after an I/O error."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def _raise_if_blocked(self) -> None:
        """Replay a device-level refusal without touching the device.

        Once the machine answers 4 (another client holds it), 5 (the stored
        verification code is stale) or 6 (RTU external control switched off),
        no further request from this client can succeed.  Re-raising the
        stored refusal keeps the cause visible in the log and in the panel
        while sending nothing.
        """
        if self._blocked is not None:
            raise self._blocked

    def _run_locked(self, operation: Callable[[ConowModbusClient], _T]) -> _T:
        """Run a Modbus operation with exclusive port access."""
        with self._lock:
            try:
                return operation(self._connect())
            except ConowExceptionResponseError as err:
                # The device answered and refused the request; the link is
                # fine, so keep it open instead of reconnecting on every poll.
                if err.device_level:
                    # Another client holds the machine, the code needs a manual
                    # refresh, or the RTU external-control switch is off: this
                    # link cannot carry a read or a write anymore.  Drop it and
                    # stop polling until the user fixes the cause and reloads
                    # the entry (or writes a new verification code).
                    self._blocked = err
                    self._reset_client()
                    LOGGER.warning(
                        "Device refused the link (exception %s); stopping all "
                        "Modbus I/O until a new verification code is accepted "
                        "or the entry is reloaded",
                        err.exception_code,
                    )
                raise
            except ConowModbusError:
                self._reset_client()
                raise

    def shutdown(self) -> None:
        """Release the serial port."""
        with self._lock:
            self._reset_client()

    def _probe_firmware_version(self) -> tuple[tuple[int, ...] | None, bool]:
        """Read the firmware register and report whether the probe succeeded.

        Any reply selects the v2 map, so the decoded version is only used for
        logging.  Some machines expose a single word at 0x274E, so a failed
        two-word read is retried with one word before giving up.
        """
        last_error: ConowModbusError | None = None
        for count in (FIRMWARE_VERSION_REGISTERS, 1):
            try:
                words = self._run_locked(
                    lambda client, count=count: client.read_holding_registers(
                        FIRMWARE_VERSION_ADDRESS,
                        count,
                        retries=2,
                    )
                )
            except ConowConnectError:
                # The link itself cannot be opened: that says nothing about
                # the map.  Fail the setup so it retries, instead of locking
                # the entry onto v1 and pruning the v2 entities.
                raise
            except ConowModbusError as err:
                last_error = err
                continue
            return parse_firmware_version(words), True

        LOGGER.info(
            "Map: firmware probe at 0x%04X failed (%s); keeping %s",
            FIRMWARE_VERSION_ADDRESS,
            last_error,
            map_source(MAP_V1),
        )
        return None, False

    async def async_probe_map_version(self) -> str:
        """Probe the device and store the selected register map id."""
        version, probe_ok = await self.hass.async_add_executor_job(
            self._probe_firmware_version
        )
        self.firmware_version = version
        self.map_version = select_map(probe_ok)
        self._apply_poll_interval()
        self._remember_map_version()
        LOGGER.info(
            "Map: firmware=%s -> %s (%s), poll every %ss",
            format_version(version) or "unknown",
            self.map_version,
            map_source(self.map_version),
            self.poll_interval_seconds,
        )
        return self.map_version

    def _remember_map_version(self) -> None:
        """Persist the selected map for the panel's offline fallback.

        The map itself is still chosen by the firmware probe on every setup;
        this only lets the panel keep showing the right groups (they differ
        between v1 and v2) while the device cannot be read.
        """
        if self.entry.options.get(CONF_LAST_MAP_VERSION) == self.map_version:
            return
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={
                **self.entry.options,
                CONF_LAST_MAP_VERSION: self.map_version,
            },
        )

    def _apply_poll_interval(self) -> None:
        """Use the panel-configured interval when set, else the map default."""
        seconds = self._configured_poll_interval
        if seconds is None:
            seconds = (
                PANEL_POLL_INTERVAL_S
                if self.map_version == MAP_V2
                else MODBUS_POLL_INTERVAL
            )
        self.poll_interval_seconds = seconds
        self.update_interval = timedelta(seconds=seconds)

    async def async_set_poll_interval(self, seconds: int) -> None:
        """Apply a new polling interval without reloading the entry."""
        if seconds not in POLL_INTERVAL_OPTIONS:
            raise ValueError(f"Unsupported poll interval: {seconds}s")
        self._configured_poll_interval = seconds
        self._apply_poll_interval()
        # Re-arm the timer with the new interval right away instead of waiting
        # for the currently scheduled refresh.
        await self.async_request_refresh()

    def _read_snapshot(self) -> dict[str, dict[str, Any]]:
        """Blocking read of every block of the active map.

        Raises ``ConowModbusError`` when the key block is unreadable so the
        coordinator marks the device unavailable instead of half-updating it.
        """
        self._raise_if_blocked()
        return self._run_locked(
            lambda client: decode_required_blocks(
                read_map_blocks(client, self.map_version), self.map_version
            )
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from device."""
        try:
            data = await self.hass.async_add_executor_job(self._read_snapshot)
        except ConowModbusError as err:
            raise UpdateFailed(str(err)) from err
        if not data:
            raise UpdateFailed(
                f"{map_source(self.map_version)} is not readable on this device"
            )
        return data

    async def async_read_snapshot(self) -> dict[str, dict[str, Any]]:
        """Read the active map without touching coordinator data.

        Used by the grouping panel so a manual refresh does not overwrite the
        polled entity data.
        """
        return await self.hass.async_add_executor_job(self._read_snapshot)

    async def async_write_verify_code(self, verify_code: str) -> None:
        """Send a new challenge code over the existing TCP connection.

        Reuses the coordinator's link so a device that accepts only one TCP
        client is not asked for a second one while the entry is loaded.  This
        is the one operation that runs while a device-level refusal is held:
        an accepted code lifts the stop.
        """
        await self.hass.async_add_executor_job(
            self._run_locked,
            lambda client: client.write_registers(
                VERIFY_CODE_START,
                encode_verify_code(verify_code),
                retries=1,
            ),
        )
        if self._blocked is not None:
            LOGGER.info(
                "Device accepted the new verification code; resuming Modbus I/O"
            )
            self._blocked = None

    def _write_panel_ops(self, ops: list[tuple[int, list[int]]]) -> None:
        """Write grouping-panel registers under the shared Modbus lock."""
        self._raise_if_blocked()
        self._run_locked(lambda client: write_register_ops(client, ops))

    async def async_write_panel_ops(self, ops: list[tuple[int, list[int]]]) -> None:
        """Write grouping-panel registers without disturbing entity polling."""
        await self.hass.async_add_executor_job(self._write_panel_ops, ops)

    def _entry(self, code: str) -> dict[str, Any]:
        return (self.data or {}).get(code) or {}

    @property
    def new_model(self) -> bool:
        """Whether the device SN marks a new-model unit.

        Old units (SN third character A–J) lack the registers flagged
        ``new_model_only``; an unreadable SN is treated as the old model.
        """
        return map_model.values_new_model(self.data)

    def get_raw(self, code: str) -> int | str | None:
        """Return the raw register value of a code."""
        return self._entry(code).get("raw")

    def get_value(self, code: str) -> float | str | None:
        """Return the decoded physical value of a code."""
        return self._entry(code).get("value")

    def get_display(self, code: str) -> str:
        """Return the panel display string of a code."""
        return self._entry(code).get("display", "")
