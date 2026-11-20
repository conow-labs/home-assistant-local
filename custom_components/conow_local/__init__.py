"""Conow Local — Modbus RTU integration for CONOW energy devices."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .client import ConowConnectError
from .const import DOMAIN, LOGGER, PLATFORMS
from .device.coordinator import ConowLocalCoordinator
from .device.network import async_register_device_mac
from .maps import entity_model
from .panel.panel_api import async_register_local_panel


def _prune_stale_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    map_version: str,
    new_model: bool,
) -> None:
    """Remove registry entries the active map does not own.

    Without this, switching maps leaves the other map's entities behind as
    unavailable "restored" entities, which looks like both maps are loaded.
    A platform mismatch is removed too, so a register that moved from
    ``number`` to a hidden ``sensor`` does not keep a stale row.  Registers
    that this hardware generation lacks are pruned the same way.
    """
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    expected = entity_model.entity_registry_keys(
        entry.entry_id, map_version, new_model
    )
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if expected.get(registry_entry.unique_id) == registry_entry.domain:
            continue
        LOGGER.debug(
            "Map %s: removing stale entity %s",
            map_version,
            registry_entry.entity_id,
        )
        registry.async_remove(registry_entry.entity_id)


type ConowLocalConfigEntry = ConfigEntry[ConowLocalCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Conow Local."""
    # pymodbus logs each timeout as ERROR; conow_local already retries internally.
    logging.getLogger("pymodbus").setLevel(logging.WARNING)
    await async_register_local_panel(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConowLocalConfigEntry) -> bool:
    """Set up a Modbus config entry."""
    coordinator = ConowLocalCoordinator(hass, entry)
    try:
        # Select the map before the first poll: exactly one map is active.
        await coordinator.async_probe_map_version()
        await coordinator.async_config_entry_first_refresh()
    except ConowConnectError as err:
        # An unreachable device is no evidence for the v1 map.  Retry instead
        # of locking the entry onto v1 and pruning the v2 entities.
        await hass.async_add_executor_job(coordinator.shutdown)
        raise ConfigEntryNotReady(f"Device unreachable: {err}") from err
    except Exception:
        # Serial ports are opened exclusively: a failed setup must release
        # the handle or every retry fails with "Failed to open serial port".
        await hass.async_add_executor_job(coordinator.shutdown)
        raise
    entry.runtime_data = coordinator
    _prune_stale_entities(
        hass, entry, coordinator.map_version, coordinator.new_model
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # The device registry entry exists only after the platforms are forwarded.
    # The first poll has just succeeded, so the TCP peer's ARP entry is warm.
    await async_register_device_mac(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConowLocalConfigEntry) -> bool:
    """Unload Conow Local platforms."""
    coordinator = entry.runtime_data
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and coordinator is not None:
        await hass.async_add_executor_job(coordinator.shutdown)
    return unload_ok
