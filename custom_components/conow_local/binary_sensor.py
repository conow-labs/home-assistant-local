"""Modbus binary sensor entities for the active register map."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device.coordinator import ConowLocalCoordinator
from .device.descriptions import build_binary_sensor_description, build_device_info
from .maps.entity_model import BINARY_SENSOR, EntitySpec, specs_for_platform


class ConowBinarySensor(
    CoordinatorEntity[ConowLocalCoordinator], BinarySensorEntity
):
    """Bit of a bitmask register, or a read-only boolean register."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ConowLocalCoordinator,
        entry: ConfigEntry,
        spec: EntitySpec,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(coordinator)
        self._spec = spec
        self.entity_description = build_binary_sensor_description(spec)
        self._attr_unique_id = f"{entry.entry_id}_{spec.unique_code}"
        self._attr_device_info = build_device_info(coordinator.hass, entry)

    @property
    def is_on(self) -> bool | None:
        """Return the bit/register state, or None when it was not read."""
        data = self.coordinator.data or {}
        raw = (data.get(self._spec.register.code) or {}).get("raw")
        if not isinstance(raw, int):
            return None
        if self._spec.bit is None:
            return bool(raw)
        return bool(raw & (1 << self._spec.bit.bit))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one binary sensor per bit/boolean spec of the active map."""
    coordinator: ConowLocalCoordinator = entry.runtime_data
    async_add_entities(
        ConowBinarySensor(coordinator, entry, spec)
        for spec in specs_for_platform(
            coordinator.map_version, BINARY_SENSOR, coordinator.new_model
        )
    )
