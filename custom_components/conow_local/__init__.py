"""Conow Local — Modbus RTU integration for CONOW energy devices."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .coordinator import ConowLocalCoordinator

type ConowLocalConfigEntry = ConfigEntry[ConowLocalCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Conow Local."""
    # pymodbus logs each timeout as ERROR; conow_local already retries internally.
    logging.getLogger("pymodbus").setLevel(logging.WARNING)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConowLocalConfigEntry) -> bool:
    """Set up a Modbus RTU config entry."""
    coordinator = ConowLocalCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConowLocalConfigEntry) -> bool:
    """Unload Conow Local platforms."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and entry.runtime_data is not None:
        await hass.async_add_executor_job(entry.runtime_data.shutdown)
    return unload_ok
