"""Constants for Conow Local (Modbus RTU) integration."""

import logging

from homeassistant.const import Platform

DOMAIN = "conow_local"
LOGGER = logging.getLogger(__package__)

CONF_MODBUS_MODE = "modbus_mode"
CONF_MODBUS_PORT = "modbus_port"
CONF_MODBUS_HOST = "modbus_host"
CONF_MODBUS_TCP_PORT = "modbus_tcp_port"
CONF_MODBUS_SLAVE = "modbus_slave"
CONF_MODBUS_BAUDRATE = "modbus_baudrate"
CONF_DEVICE_NAME = "device_name"

MODBUS_MODE_RTU = "rtu"
MODBUS_MODE_TCP = "tcp"
DEFAULT_TCP_PORT = 502

MODBUS_POLL_INTERVAL = 5

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SELECT,
]
