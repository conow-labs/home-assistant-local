"""Number entities for writable numeric registers of the active map."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device.coordinator import ConowLocalCoordinator
from .device.descriptions import (
    build_device_info,
    build_number_description,
    display_value,
)
from .device.guard import async_refuse_device_write
from .maps.entity_model import NUMBER, EntitySpec, specs_for_platform


class ConowNumber(CoordinatorEntity[ConowLocalCoordinator], NumberEntity):
    """Writable setting shown on the device page; writes go through the panel."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ConowLocalCoordinator,
        entry: ConfigEntry,
        spec: EntitySpec,
    ) -> None:
        """Initialize number entity."""
        super().__init__(coordinator)
        self._entry = entry
        self._spec = spec
        self.entity_description = build_number_description(spec)
        self._attr_unique_id = f"{entry.entry_id}_{spec.unique_code}"
        self._attr_device_info = build_device_info(coordinator.hass, entry)

    @property
    def native_value(self) -> int | float | None:
        """Return the decoded value formatted like the grouping panel."""
        value = self.coordinator.get_value(self._spec.register.code)
        if not isinstance(value, (int, float)):
            return None
        return display_value(self._spec.register, value)

    async def async_set_native_value(self, value: float) -> None:
        """Refuse single-register writes from the device page."""
        async_refuse_device_write(self.hass, self._entry)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one number per writable numeric register of the active map."""
    coordinator: ConowLocalCoordinator = entry.runtime_data
    async_add_entities(
        ConowNumber(coordinator, entry, spec)
        for spec in specs_for_platform(
            coordinator.map_version, NUMBER, coordinator.new_model
        )
    )
