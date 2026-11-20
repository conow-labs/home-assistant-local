"""Modbus sensor entities for the active register map."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device.coordinator import ConowLocalCoordinator
from .device.descriptions import (
    build_device_info,
    build_sensor_description,
    display_value,
)
from .maps.entity_model import SENSOR, EntitySpec, specs_for_platform
from .maps.model import PanelRegister


class ConowSensor(CoordinatorEntity[ConowLocalCoordinator], SensorEntity):
    """Sensor backed by a read-only register of the active map.

    Read-only numeric/enum/string registers share this class; the spec's
    register decides how the value is rendered.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ConowLocalCoordinator,
        entry: ConfigEntry,
        spec: EntitySpec,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._spec = spec
        self.entity_description = build_sensor_description(spec)
        self._attr_unique_id = f"{entry.entry_id}_{spec.unique_code}"
        self._attr_device_info = build_device_info(coordinator.hass, entry)

    @property
    def _register(self) -> PanelRegister:
        return self._spec.register

    @property
    def native_value(self) -> Any:
        """Return the decoded register value."""
        data = self.coordinator.data or {}
        entry = data.get(self._register.code) or {}
        if self._register.values:
            # Enum registers expose the mapped label, matching the options.
            return entry.get("display") or None
        if self._register.dtype == "string":
            return entry.get("raw") or None
        value = entry.get("value")
        if isinstance(value, (int, float)):
            return display_value(self._register, value)
        return value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one sensor per sensor spec of the active map."""
    coordinator: ConowLocalCoordinator = entry.runtime_data
    async_add_entities(
        ConowSensor(coordinator, entry, spec)
        for spec in specs_for_platform(
            coordinator.map_version, SENSOR, coordinator.new_model
        )
    )
