"""Modbus switch entities for the active register map."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device.coordinator import ConowLocalCoordinator
from .device.descriptions import build_device_info, build_switch_description
from .device.guard import async_refuse_device_write
from .maps.entity_model import SWITCH, EntitySpec, specs_for_platform


class ConowSwitch(CoordinatorEntity[ConowLocalCoordinator], SwitchEntity):
    """Writable on/off register; writes are refused on the device page."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ConowLocalCoordinator,
        entry: ConfigEntry,
        spec: EntitySpec,
    ) -> None:
        """Initialize switch entity."""
        super().__init__(coordinator)
        self._entry = entry
        self._spec = spec
        self.entity_description = build_switch_description(spec)
        self._attr_unique_id = f"{entry.entry_id}_{spec.unique_code}"
        self._attr_device_info = build_device_info(coordinator.hass, entry)

    @property
    def is_on(self) -> bool | None:
        """Return the register's raw 0/1 state."""
        raw = self.coordinator.get_raw(self._spec.register.code)
        if not isinstance(raw, int):
            return None
        return bool(raw)

    async def async_turn_on(self, **kwargs: object) -> None:
        """Refuse single-register writes from the device page."""
        async_refuse_device_write(self.coordinator.hass, self._entry)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Refuse single-register writes from the device page."""
        async_refuse_device_write(self.coordinator.hass, self._entry)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one switch per writable boolean register of the active map."""
    coordinator: ConowLocalCoordinator = entry.runtime_data
    async_add_entities(
        ConowSwitch(coordinator, entry, spec)
        for spec in specs_for_platform(
            coordinator.map_version, SWITCH, coordinator.new_model
        )
    )
