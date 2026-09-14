"""Config flow for Conow Local."""

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .client import ConowModbusError, probe_connection
from .const import (
    CONF_DEVICE_NAME,
    CONF_MODBUS_BAUDRATE,
    CONF_MODBUS_HOST,
    CONF_MODBUS_MODE,
    CONF_MODBUS_PORT,
    CONF_MODBUS_SLAVE,
    CONF_MODBUS_TCP_PORT,
    DEFAULT_TCP_PORT,
    DOMAIN,
    MODBUS_MODE_RTU,
    MODBUS_MODE_TCP,
)
from .register_map import DEFAULT_BAUDRATE, DEFAULT_SLAVE

MODBUS_MODES = {
    MODBUS_MODE_RTU: "Modbus RTU (RS-485 serial)",
    MODBUS_MODE_TCP: "Modbus TCP (RS-485↔Ethernet adapter)",
}


class ConowLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle Conow Local config flow."""

    VERSION = 1

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
        if mode == MODBUS_MODE_TCP:
            return await self.async_step_tcp()
        return await self.async_step_rtu()

    def _rtu_schema(
        self, device_name: str = "CONOW Energy", port: str = "", slave: int = DEFAULT_SLAVE,
        baudrate: int = DEFAULT_BAUDRATE,
    ) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_DEVICE_NAME, default=device_name): str,
                vol.Required(CONF_MODBUS_PORT, default=port): str,
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

    async def async_step_rtu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a Modbus RTU serial connection."""
        errors: dict[str, str] = {}
        if user_input is not None:
            port = user_input[CONF_MODBUS_PORT]
            slave = user_input[CONF_MODBUS_SLAVE]
            baudrate = user_input[CONF_MODBUS_BAUDRATE]
            await self.async_set_unique_id(f"modbus_rtu_{port}_{slave}_{baudrate}")
            self._abort_if_unique_id_configured()
            try:
                await self.hass.async_add_executor_job(
                    probe_connection, port, slave=slave, baudrate=baudrate
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
                ),
                errors=errors,
            )

        return self.async_show_form(step_id="rtu", data_schema=self._rtu_schema())

    async def async_step_tcp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a Modbus TCP connection via an RS-485↔Ethernet adapter."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_MODBUS_HOST]
            tcp_port = user_input[CONF_MODBUS_TCP_PORT]
            slave = user_input[CONF_MODBUS_SLAVE]
            await self.async_set_unique_id(f"modbus_tcp_{host}_{tcp_port}_{slave}")
            self._abort_if_unique_id_configured()
            try:
                await self.hass.async_add_executor_job(
                    probe_connection, None, host=host, tcp_port=tcp_port, slave=slave
                )
            except ConowModbusError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_DEVICE_NAME],
                    data={
                        CONF_MODBUS_MODE: MODBUS_MODE_TCP,
                        CONF_DEVICE_NAME: user_input[CONF_DEVICE_NAME],
                        CONF_MODBUS_HOST: host,
                        CONF_MODBUS_TCP_PORT: tcp_port,
                        CONF_MODBUS_SLAVE: slave,
                    },
                )

            return self.async_show_form(
                step_id="tcp",
                data_schema=self._tcp_schema(
                    user_input.get(CONF_DEVICE_NAME, "CONOW Energy"),
                    host,
                    tcp_port,
                    slave,
                ),
                errors=errors,
            )

        return self.async_show_form(step_id="tcp", data_schema=self._tcp_schema())
