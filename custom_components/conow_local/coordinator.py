"""Modbus data update coordinator."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any, TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import POST_WRITE_DELAY_S, ConowModbusClient, ConowModbusError
from .const import (
    CONF_MODBUS_BAUDRATE,
    CONF_MODBUS_PORT,
    CONF_MODBUS_SLAVE,
    DOMAIN,
    LOGGER,
    MODBUS_POLL_INTERVAL,
)

_T = TypeVar("_T")


class ConowLocalCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll CONOW device over Modbus RTU."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        self.entry = entry
        self.port = entry.data[CONF_MODBUS_PORT]
        self.slave = entry.data[CONF_MODBUS_SLAVE]
        self.baudrate = entry.data[CONF_MODBUS_BAUDRATE]
        self._lock = threading.Lock()
        self._client: ConowModbusClient | None = None
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=MODBUS_POLL_INTERVAL),
        )

    def _connect(self) -> ConowModbusClient:
        """Open or reuse the serial Modbus client."""
        if self._client is None:
            client = ConowModbusClient(
                self.port,
                slave=self.slave,
                baudrate=self.baudrate,
            )
            client.connect()
            self._client = client
        return self._client

    def _reset_client(self) -> None:
        """Close the serial client after an I/O error."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def _run_locked(self, operation: Callable[[ConowModbusClient], _T]) -> _T:
        """Run a Modbus operation with exclusive serial port access."""
        with self._lock:
            try:
                return operation(self._connect())
            except ConowModbusError:
                self._reset_client()
                raise

    def shutdown(self) -> None:
        """Release the serial port."""
        with self._lock:
            self._reset_client()

    def _read_device(self) -> dict[str, Any]:
        """Blocking Modbus read executed in executor."""
        return self._run_locked(lambda client: client.read_all())

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from device."""
        try:
            return await self.hass.async_add_executor_job(self._read_device)
        except ConowModbusError as err:
            raise UpdateFailed(str(err)) from err

    def _write_and_read(
        self, write_op: Callable[[ConowModbusClient], None]
    ) -> dict[str, Any]:
        """Write then read back in one locked serial session."""

        def _operation(client: ConowModbusClient) -> dict[str, Any]:
            LOGGER.debug("Coordinator: executing Modbus write then read-back")
            write_op(client)
            time.sleep(POST_WRITE_DELAY_S)
            LOGGER.debug("Coordinator: read-back after write (monitoring + control)")
            data = client.read_all()
            control = data.get("control", {})
            direction = control.get("charge_discharge_direction", {})
            power = control.get("battery_target_power", {})
            cutoff = control.get("battery_cutoff_soc", {})
            LOGGER.debug(
                "Coordinator: read-back control snapshot direction=%s power=%s cutoff_soc=%s",
                direction.get("raw"),
                power.get("raw"),
                cutoff.get("raw"),
            )
            return data

        return self._run_locked(_operation)

    async def _async_write_and_update(
        self, write_op: Callable[[ConowModbusClient], None]
    ) -> None:
        """Write to device and push fresh register data to entities."""
        data = await self.hass.async_add_executor_job(self._write_and_read, write_op)
        self.async_set_updated_data(data)

    async def async_write_register_raw(self, name: str, raw_value: int) -> None:
        """Write a control register and refresh coordinator data."""
        await self._async_write_and_update(
            lambda client: client.write_named_register_raw(name, raw_value)
        )

    async def async_write_register(self, name: str, physical_value: float) -> None:
        """Write a control register using physical units."""
        await self._async_write_and_update(
            lambda client: client.write_named_register(name, physical_value)
        )

    async def async_write_force_mode(
        self, direction: int, power_w: int, cutoff_soc: int
    ) -> None:
        """Write forced charge/discharge command sequence."""
        await self._async_write_and_update(
            lambda client: client.write_force_mode(direction, power_w, cutoff_soc)
        )

    def get_register_value(self, block: str, name: str) -> float | None:
        """Return decoded physical value for a register name."""
        data = self.data or {}
        section = data.get(block, {})
        entry = section.get(name)
        if not entry:
            return None
        return entry.get("value")

    def get_status_bit(self, name: str) -> bool | None:
        """Return a parsed system status bit."""
        data = self.data or {}
        status = data.get("monitoring", {}).get("system_status")
        if not status:
            return None
        bits = status.get("bits", {})
        return bits.get(name)
