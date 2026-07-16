"""Config flow for Conow Local."""

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .client import ConowModbusError, probe_connection
from .const import (
    CONF_DEVICE_NAME,
    CONF_MODBUS_BAUDRATE,
    CONF_MODBUS_PORT,
    CONF_MODBUS_SLAVE,
    DOMAIN,
)
from .register_map import DEFAULT_BAUDRATE, DEFAULT_SLAVE


class ConowLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle Conow Local config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure local Modbus RTU connection."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_DEVICE_NAME, default="CONOW Energy"): str,
                        vol.Required(CONF_MODBUS_PORT): str,
                        vol.Optional(CONF_MODBUS_SLAVE, default=DEFAULT_SLAVE): int,
                        vol.Optional(CONF_MODBUS_BAUDRATE, default=DEFAULT_BAUDRATE): int,
                    }
                ),
            )

        port = user_input[CONF_MODBUS_PORT]
        slave = user_input[CONF_MODBUS_SLAVE]
        baudrate = user_input[CONF_MODBUS_BAUDRATE]
        unique_id = f"modbus_{port}_{slave}_{baudrate}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        try:
            await self.hass.async_add_executor_job(probe_connection, port, slave, baudrate)
        except ConowModbusError:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_DEVICE_NAME,
                            default=user_input.get(CONF_DEVICE_NAME, "CONOW Energy"),
                        ): str,
                        vol.Required(CONF_MODBUS_PORT, default=port): str,
                        vol.Optional(CONF_MODBUS_SLAVE, default=slave): int,
                        vol.Optional(CONF_MODBUS_BAUDRATE, default=baudrate): int,
                    }
                ),
                errors={"base": "cannot_connect"},
            )

        return self.async_create_entry(
            title=user_input[CONF_DEVICE_NAME],
            data={
                CONF_DEVICE_NAME: user_input[CONF_DEVICE_NAME],
                CONF_MODBUS_PORT: port,
                CONF_MODBUS_SLAVE: slave,
                CONF_MODBUS_BAUDRATE: baudrate,
            },
        )
