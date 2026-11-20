"""Time entities for HH:MM registers of the active register map."""

from __future__ import annotations

from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device.coordinator import ConowLocalCoordinator
from .device.descriptions import build_device_info, build_time_description
from .device.guard import async_refuse_device_write
from .maps.entity_model import TIME, EntitySpec, specs_for_platform


class ConowTime(CoordinatorEntity[ConowLocalCoordinator], TimeEntity):
    """Schedule register (high byte hour, low byte minute) as a time entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ConowLocalCoordinator,
        entry: ConfigEntry,
        spec: EntitySpec,
    ) -> None:
        """Initialize time entity."""
        super().__init__(coordinator)
        self._entry = entry
        self._spec = spec
        self.entity_description = build_time_description(spec)
        self._attr_unique_id = f"{entry.entry_id}_{spec.unique_code}"
        self._attr_device_info = build_device_info(coordinator.hass, entry)

    @property
    def native_value(self) -> dt_time | None:
        """Return the current HH:MM value."""
        raw = self.coordinator.get_raw(self._spec.register.code)
        if not isinstance(raw, int):
            return None
        hour = (raw >> 8) & 0xFF
        minute = raw & 0xFF
        if hour > 23 or minute > 59:
            return None
        return dt_time(hour=hour, minute=minute)

    async def async_set_value(self, value: dt_time) -> None:
        """Refuse single-register writes from the device page."""
        async_refuse_device_write(self.hass, self._entry)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one time entity per HH:MM spec of the active map."""
    coordinator: ConowLocalCoordinator = entry.runtime_data
    async_add_entities(
        ConowTime(coordinator, entry, spec)
        for spec in specs_for_platform(
            coordinator.map_version, TIME, coordinator.new_model
        )
    )
