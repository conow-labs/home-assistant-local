"""Select entities for writable enum registers of the active map."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device.coordinator import ConowLocalCoordinator
from .device.descriptions import build_device_info, build_select_description
from .device.guard import async_refuse_device_write
from .maps.entity_model import SELECT, EntitySpec, specs_for_platform


class ConowSelect(CoordinatorEntity[ConowLocalCoordinator], SelectEntity):
    """Writable enum shown on the device page; writes go through the panel."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ConowLocalCoordinator,
        entry: ConfigEntry,
        spec: EntitySpec,
    ) -> None:
        """Initialize select entity."""
        super().__init__(coordinator)
        self._entry = entry
        self._spec = spec
        self.entity_description = build_select_description(spec)
        self._attr_unique_id = f"{entry.entry_id}_{spec.unique_code}"
        self._attr_device_info = build_device_info(coordinator.hass, entry)

    @property
    def current_option(self) -> str | None:
        """Return the map label of the current enum value."""
        data = self.coordinator.data or {}
        display = (data.get(self._spec.register.code) or {}).get("display")
        options = list(self.entity_description.options or ())
        return display if display in options else None

    async def async_select_option(self, option: str) -> None:
        """Refuse single-register writes from the device page."""
        async_refuse_device_write(self.hass, self._entry)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one select per writable enum register of the active map."""
    coordinator: ConowLocalCoordinator = entry.runtime_data
    async_add_entities(
        ConowSelect(coordinator, entry, spec)
        for spec in specs_for_platform(
            coordinator.map_version, SELECT, coordinator.new_model
        )
    )
