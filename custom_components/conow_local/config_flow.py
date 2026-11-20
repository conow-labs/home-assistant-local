"""Config flow for Conow Local."""

import logging
from functools import partial
from typing import Any

import voluptuous as vol

from homeassistant.components import usb
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .client import (
    CONOW_EXCEPTION_DEVICE_BUSY,
    CONOW_EXCEPTION_EXTERNAL_CONTROL,
    CONOW_EXCEPTION_VERIFICATION_REQUIRED,
    VERIFY_CODE_LENGTH,
    ConowConnectError,
    ConowExceptionResponseError,
    ConowModbusError,
    ConowVerificationError,
    probe_connection,
    probe_direct_connection,
)
from .const import (
    CONF_DEVICE_NAME,
    CONF_MODBUS_BAUDRATE,
    CONF_MODBUS_HOST,
    CONF_MODBUS_MODE,
    CONF_MODBUS_PORT,
    CONF_MODBUS_SLAVE,
    CONF_MODBUS_TCP_PORT,
    CONF_TCP_VERIFY_CODE,
    DEFAULT_BAUDRATE,
    DEFAULT_SLAVE,
    DEFAULT_TCP_PORT,
    DOMAIN,
    MODBUS_MODE_RTU,
    MODBUS_MODE_TCP,
    MODBUS_MODE_TCP_DIRECT,
    MODBUS_TCP_MODES,
)
from .device.handoff import connection_key, stash
from .device.network import resolve_mac, tcp_unique_id

MODBUS_MODES = {
    MODBUS_MODE_RTU: "Modbus RTU (RS-485 serial)",
    MODBUS_MODE_TCP: "Modbus TCP (RS-485↔Ethernet adapter)",
    MODBUS_MODE_TCP_DIRECT: "Modbus TCP (direct to all-in-one machine)",
}

_LOGGER = logging.getLogger(__name__)

# Ports that are never an RS-485 adapter; macOS always exposes them.
_SERIAL_PORT_NOISE = ("Bluetooth-Incoming-Port", "debug-console")


def _is_valid_verify_code(value: str) -> bool:
    """Return whether the value is an 8-character hexadecimal code."""
    text = str(value).strip()
    return len(text) == VERIFY_CODE_LENGTH and all(
        char in "0123456789abcdefABCDEF" for char in text
    )


def _serial_port_label(port: Any) -> str:
    """Return a readable label for a detected serial port."""
    if isinstance(port, usb.USBDevice):
        return usb.human_readable_device_name(
            port.device,
            port.serial_number,
            port.manufacturer,
            port.description,
            port.vid,
            port.pid,
        )
    description = getattr(port, "description", None)
    return f"{description} ({port.device})" if description else port.device


def _refusal_error(
    err: ConowExceptionResponseError, default: str, *, rtu: bool = False
) -> str:
    """Map the machine's private exception codes to a UI error key.

    The Conow firmware answers 4 when another client already holds the device
    and 5 when it wants the verification code refreshed, on every connection
    type.  Code 6 ("external control switched off") only concerns the RS-485
    link, so it is translated for an RTU probe and left as the generic error
    on TCP paths.
    """
    if err.exception_code == CONOW_EXCEPTION_DEVICE_BUSY:
        return "device_busy"
    if err.exception_code == CONOW_EXCEPTION_VERIFICATION_REQUIRED:
        return "verification_required"
    if rtu and err.exception_code == CONOW_EXCEPTION_EXTERNAL_CONTROL:
        return "external_control_disabled"
    return default


class ConowLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle Conow Local config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ConowLocalOptionsFlow:
        """Return the options flow that edits the TCP connection parameters."""
        return ConowLocalOptionsFlow(config_entry)

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        """TCP entries can move to a new address, port or slave address."""
        return config_entry.data.get(CONF_MODBUS_MODE) in MODBUS_TCP_MODES

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the Modbus connection mode."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_MODBUS_MODE, default=MODBUS_MODE_RTU
                        ): vol.In(MODBUS_MODES),
                    }
                ),
            )

        mode = user_input[CONF_MODBUS_MODE]
        if mode == MODBUS_MODE_TCP_DIRECT:
            return await self.async_step_tcp_direct()
        if mode == MODBUS_MODE_TCP:
            return await self.async_step_tcp()
        return await self.async_step_rtu()

    async def _async_serial_port_options(self) -> list[SelectOptionDict]:
        """Scan the host for serial ports and build selector options."""
        try:
            ports = await usb.async_scan_serial_ports(self.hass)
        except Exception:  # noqa: BLE001 - never block the flow on a scan failure
            _LOGGER.exception("Unable to scan serial ports")
            return []
        return [
            SelectOptionDict(
                value=usb.get_serial_by_id(port.device),
                label=_serial_port_label(port),
            )
            for port in ports
            if not any(token in port.device for token in _SERIAL_PORT_NOISE)
        ]

    def _rtu_schema(
        self,
        device_name: str = "CONOW Energy",
        port: str = "",
        slave: int = DEFAULT_SLAVE,
        baudrate: int = DEFAULT_BAUDRATE,
        port_options: list[SelectOptionDict] | None = None,
    ) -> vol.Schema:
        options = port_options or []
        default_port = port
        if not default_port and len(options) == 1:
            default_port = options[0]["value"]
        port_field: Any = (
            SelectSelector(
                SelectSelectorConfig(
                    options=options,
                    mode=SelectSelectorMode.DROPDOWN,
                    custom_value=True,
                )
            )
            if options
            else str
        )
        return vol.Schema(
            {
                vol.Required(CONF_DEVICE_NAME, default=device_name): str,
                vol.Required(CONF_MODBUS_PORT, default=default_port): port_field,
                vol.Optional(CONF_MODBUS_SLAVE, default=slave): int,
                vol.Optional(CONF_MODBUS_BAUDRATE, default=baudrate): int,
            }
        )

    def _tcp_schema(
        self, device_name: str = "CONOW Energy", host: str = "",
        tcp_port: int = DEFAULT_TCP_PORT, slave: int = DEFAULT_SLAVE,
    ) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_DEVICE_NAME, default=device_name): str,
                vol.Required(CONF_MODBUS_HOST, default=host): str,
                vol.Optional(CONF_MODBUS_TCP_PORT, default=tcp_port): int,
                vol.Optional(CONF_MODBUS_SLAVE, default=slave): int,
            }
        )

    def _tcp_direct_schema(
        self, device_name: str = "CONOW Energy", host: str = "",
        tcp_port: int = DEFAULT_TCP_PORT, slave: int = DEFAULT_SLAVE,
        verify_code: str = "",
    ) -> vol.Schema:
        return self._tcp_schema(device_name, host, tcp_port, slave).extend(
            {
                vol.Required(CONF_TCP_VERIFY_CODE, default=verify_code): str,
            }
        )

    async def async_step_rtu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a Modbus RTU serial connection."""
        port_options = await self._async_serial_port_options()
        errors: dict[str, str] = {}
        if user_input is not None:
            port = str(user_input[CONF_MODBUS_PORT]).strip()
            slave = user_input[CONF_MODBUS_SLAVE]
            baudrate = user_input[CONF_MODBUS_BAUDRATE]
            if not port:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"modbus_rtu_{port}_{slave}_{baudrate}")
                self._abort_if_unique_id_configured()
                try:
                    await self.hass.async_add_executor_job(
                        partial(probe_connection, port, slave=slave, baudrate=baudrate)
                    )
                except ConowExceptionResponseError as err:
                    # An RTU probe can be refused with 4/5/6; the user needs
                    # the concrete cause rather than "cannot connect".
                    errors["base"] = _refusal_error(
                        err, "cannot_connect", rtu=True
                    )
                except ConowModbusError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        title=user_input[CONF_DEVICE_NAME],
                        data={
                            CONF_MODBUS_MODE: MODBUS_MODE_RTU,
                            CONF_DEVICE_NAME: user_input[CONF_DEVICE_NAME],
                            CONF_MODBUS_PORT: port,
                            CONF_MODBUS_SLAVE: slave,
                            CONF_MODBUS_BAUDRATE: baudrate,
                        },
                    )

            return self.async_show_form(
                step_id="rtu",
                data_schema=self._rtu_schema(
                    user_input.get(CONF_DEVICE_NAME, "CONOW Energy"),
                    port,
                    slave,
                    baudrate,
                    port_options,
                ),
                errors=errors,
            )

        return self.async_show_form(
            step_id="rtu",
            data_schema=self._rtu_schema(port_options=port_options),
        )

    async def async_step_tcp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a Modbus TCP connection via an RS-485↔Ethernet adapter."""
        return await self._async_step_tcp(user_input, MODBUS_MODE_TCP, "tcp")

    async def async_step_tcp_direct(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a Modbus TCP connection to the all-in-one machine."""
        return await self._async_step_tcp(
            user_input, MODBUS_MODE_TCP_DIRECT, "tcp_direct"
        )

    async def _async_step_tcp(
        self,
        user_input: dict[str, Any] | None,
        mode: str,
        step_id: str,
    ) -> ConfigFlowResult:
        """Shared Modbus TCP form for adapters and direct device connections."""
        errors: dict[str, str] = {}
        direct = mode == MODBUS_MODE_TCP_DIRECT
        if user_input is not None:
            host = user_input[CONF_MODBUS_HOST]
            tcp_port = user_input[CONF_MODBUS_TCP_PORT]
            slave = user_input[CONF_MODBUS_SLAVE]
            verify_code = str(user_input.get(CONF_TCP_VERIFY_CODE, "")).strip()
            if direct and not _is_valid_verify_code(verify_code):
                errors["base"] = "invalid_verify_code"
            else:
                # A cheap duplicate check before touching the device; the
                # entry's real identity is the MAC, resolved after the probe.
                await self.async_set_unique_id(
                    tcp_unique_id(mode, None, host, tcp_port, slave)
                )
                self._abort_if_unique_id_configured()
                try:
                    if direct:
                        probed = await self.hass.async_add_executor_job(
                            partial(
                                probe_direct_connection,
                                host,
                                tcp_port=tcp_port,
                                slave=slave,
                                verify_code=verify_code,
                                keep_open=True,
                            )
                        )
                    else:
                        probed = await self.hass.async_add_executor_job(
                            partial(
                                probe_connection,
                                None,
                                host=host,
                                tcp_port=tcp_port,
                                slave=slave,
                                keep_open=True,
                            )
                        )
                except ConowVerificationError:
                    errors["base"] = "verification_failed"
                except ConowConnectError:
                    errors["base"] = "tcp_connect_failed"
                except ConowExceptionResponseError as err:
                    errors["base"] = _refusal_error(err, "cannot_connect")
                except ConowModbusError:
                    errors["base"] = "cannot_connect"
                else:
                    try:
                        # The probe warmed the ARP entry.  With a MAC the entry
                        # is identified by hardware, so a new IP/port/slave
                        # edits the same entry; a routed peer has no MAC and
                        # keeps the old host-based name.
                        mac = await self.hass.async_add_executor_job(
                            resolve_mac, host
                        )
                        await self.async_set_unique_id(
                            tcp_unique_id(mode, mac, host, tcp_port, slave)
                        )
                        self._abort_if_unique_id_configured()
                    except Exception:
                        # Aborted (already configured) or the MAC lookup
                        # failed: the verified link will not be adopted.
                        if probed is not None:
                            probed.close()
                        raise
                    # Hand the verified link to the entry setup that follows so
                    # the machine sees one connection and one code write.
                    if probed is not None:
                        stash(
                            connection_key(mode, host, tcp_port, slave, verify_code),
                            probed,
                        )
                    data = {
                        CONF_MODBUS_MODE: mode,
                        CONF_DEVICE_NAME: user_input[CONF_DEVICE_NAME],
                        CONF_MODBUS_HOST: host,
                        CONF_MODBUS_TCP_PORT: tcp_port,
                        CONF_MODBUS_SLAVE: slave,
                    }
                    if direct:
                        # The stored code is sent only if the machine refuses
                        # a request after a reconnect, so a router reboot does
                        # not need a new entry and a machine that does not
                        # demand the code is not written to at all.
                        data[CONF_TCP_VERIFY_CODE] = verify_code
                    return self.async_create_entry(
                        title=user_input[CONF_DEVICE_NAME],
                        data=data,
                    )

            return self.async_show_form(
                step_id=step_id,
                data_schema=(
                    self._tcp_direct_schema(
                        user_input.get(CONF_DEVICE_NAME, "CONOW Energy"),
                        host,
                        tcp_port,
                        slave,
                        verify_code,
                    )
                    if direct
                    else self._tcp_schema(
                        user_input.get(CONF_DEVICE_NAME, "CONOW Energy"),
                        host,
                        tcp_port,
                        slave,
                    )
                ),
                errors=errors,
            )

        return self.async_show_form(
            step_id=step_id,
            data_schema=(
                self._tcp_direct_schema() if direct else self._tcp_schema()
            ),
        )


class ConowLocalOptionsFlow(OptionsFlow):
    """Edit the connection parameters of a TCP entry.

    The peer's address, the TCP port and the slave address can all move (DHCP
    lease, adapter swap, re-addressing), and a direct-TCP machine shows a fresh
    verification code after a power cycle.  Every value is validated against
    the device before the stored entry is replaced.
    """

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Store the entry the options belong to."""
        self._entry = config_entry

    def _schema(self, data: dict[str, Any], direct: bool) -> vol.Schema:
        """Return the form pre-filled with the stored values."""
        fields: dict[Any, Any] = {
            vol.Required(
                CONF_MODBUS_HOST, default=str(data.get(CONF_MODBUS_HOST, "") or "")
            ): str,
            vol.Optional(
                CONF_MODBUS_TCP_PORT,
                default=data.get(CONF_MODBUS_TCP_PORT, DEFAULT_TCP_PORT),
            ): int,
            vol.Optional(
                CONF_MODBUS_SLAVE,
                default=data.get(CONF_MODBUS_SLAVE, DEFAULT_SLAVE),
            ): int,
        }
        if direct:
            fields[
                vol.Required(
                    CONF_TCP_VERIFY_CODE,
                    default=str(data.get(CONF_TCP_VERIFY_CODE, "") or ""),
                )
            ] = str
        return vol.Schema(fields)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate the new parameters against the device, then save them."""
        data = dict(self._entry.data)
        mode = data.get(CONF_MODBUS_MODE)
        if mode not in MODBUS_TCP_MODES:
            return self.async_abort(reason="no_options")

        direct = mode == MODBUS_MODE_TCP_DIRECT
        errors: dict[str, str] = {}

        if user_input is not None:
            host = str(user_input.get(CONF_MODBUS_HOST, "")).strip()
            tcp_port = user_input.get(CONF_MODBUS_TCP_PORT, DEFAULT_TCP_PORT)
            slave = user_input.get(CONF_MODBUS_SLAVE, DEFAULT_SLAVE)
            verify_code = str(
                user_input.get(CONF_TCP_VERIFY_CODE)
                or data.get(CONF_TCP_VERIFY_CODE)
                or ""
            ).strip()
            if not host:
                errors["base"] = "cannot_connect"
            elif direct and not _is_valid_verify_code(verify_code):
                errors["base"] = "invalid_verify_code"
            else:
                target_changed = (
                    host != data.get(CONF_MODBUS_HOST)
                    or tcp_port != data.get(CONF_MODBUS_TCP_PORT, DEFAULT_TCP_PORT)
                    or slave != data.get(CONF_MODBUS_SLAVE, DEFAULT_SLAVE)
                )
                coordinator = getattr(self._entry, "runtime_data", None)
                loaded = (
                    self._entry.state is ConfigEntryState.LOADED
                    and coordinator is not None
                )
                if loaded and target_changed:
                    # The direct-connected machine accepts a single TCP client;
                    # drop the live link before probing a different endpoint.
                    await self.hass.async_add_executor_job(coordinator.shutdown)
                new_data = {
                    **data,
                    CONF_MODBUS_HOST: host,
                    CONF_MODBUS_TCP_PORT: tcp_port,
                    CONF_MODBUS_SLAVE: slave,
                }
                if direct:
                    new_data[CONF_TCP_VERIFY_CODE] = verify_code

                if direct and loaded and not target_changed:
                    # Only the code changed: write it over the live link and
                    # keep that link.  Reloading would reconnect and make the
                    # machine verify the code a second time.
                    if verify_code.lower() == str(
                        data.get(CONF_TCP_VERIFY_CODE, "") or ""
                    ).strip().lower():
                        # Nothing changed; do not touch the device at all.
                        return self.async_create_entry(
                            title="", data=dict(self._entry.options)
                        )
                    try:
                        await coordinator.async_write_verify_code(verify_code)
                    except ConowVerificationError:
                        errors["base"] = "verification_failed"
                    except ConowConnectError:
                        errors["base"] = "tcp_connect_failed"
                    except ConowExceptionResponseError as err:
                        errors["base"] = _refusal_error(err, "verification_failed")
                    except ConowModbusError:
                        errors["base"] = "verification_failed"
                    else:
                        coordinator.verify_code = verify_code
                        self.hass.config_entries.async_update_entry(
                            self._entry, data=new_data
                        )
                        return self.async_create_entry(
                            title="", data=dict(self._entry.options)
                        )
                elif not direct and not target_changed:
                    # Adapter mode has no code and the endpoint is unchanged:
                    # nothing to verify against the device.
                    self.hass.config_entries.async_update_entry(
                        self._entry, data=new_data
                    )
                    if loaded:
                        return self.async_create_entry(
                            title="", data=dict(self._entry.options)
                        )
                    # Retry an entry that is not running right now.
                    await self.hass.config_entries.async_reload(
                        self._entry.entry_id
                    )
                    return self.async_create_entry(
                        title="", data=dict(self._entry.options)
                    )
                else:
                    try:
                        if direct:
                            probed = await self.hass.async_add_executor_job(
                                partial(
                                    probe_direct_connection,
                                    host,
                                    tcp_port=tcp_port,
                                    slave=slave,
                                    verify_code=verify_code,
                                    keep_open=True,
                                )
                            )
                        else:
                            # Adapter mode has no code; a successful read
                            # proves the new address/port/slave reach the
                            # device.
                            probed = await self.hass.async_add_executor_job(
                                partial(
                                    probe_connection,
                                    None,
                                    host=host,
                                    tcp_port=tcp_port,
                                    slave=slave,
                                    keep_open=True,
                                )
                            )
                    except ConowVerificationError:
                        errors["base"] = "verification_failed"
                    except ConowConnectError:
                        errors["base"] = "tcp_connect_failed"
                    except ConowExceptionResponseError as err:
                        errors["base"] = _refusal_error(
                            err,
                            "verification_failed" if direct else "cannot_connect",
                        )
                    except ConowModbusError:
                        errors["base"] = (
                            "verification_failed" if direct else "cannot_connect"
                        )
                    else:
                        # The reload's coordinator adopts this verified link,
                        # so the machine never sees a second connection.
                        if probed is not None:
                            stash(
                                connection_key(
                                    mode, host, tcp_port, slave, verify_code
                                ),
                                probed,
                            )
                        self.hass.config_entries.async_update_entry(
                            self._entry, data=new_data
                        )
                        # Setup re-resolves the MAC, so the entry's unique id
                        # follows the hardware if the address changed.
                        await self.hass.config_entries.async_reload(
                            self._entry.entry_id
                        )
                        return self.async_create_entry(
                            title="", data=dict(self._entry.options)
                        )

            return self.async_show_form(
                step_id="init",
                data_schema=self._schema({**data, **(user_input or {})}, direct),
                errors=errors,
            )

        return self.async_show_form(
            step_id="init",
            data_schema=self._schema(data, direct),
        )
