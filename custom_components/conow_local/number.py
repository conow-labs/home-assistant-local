"""Modbus number entities for writable registers."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_NAME, DOMAIN
from .coordinator import ConowLocalCoordinator
from .entity_factory import build_number_description, register_for_entity
from .register_map import EntityDef, get_entities


class ConowModbusNumber(CoordinatorEntity[ConowLocalCoordinator], NumberEntity):
    """Writable Modbus register exposed as a number."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ConowLocalCoordinator,
        entry: ConfigEntry,
        entity: EntityDef,
    ) -> None:
        """Initialize number entity."""
        super().__init__(coordinator)
        self._register_name = entity.register
        register = register_for_entity(entity)
        self.entity_description = build_number_description(entity, register)
        self._attr_unique_id = f"{entry.entry_id}_{entity.code}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_DEVICE_NAME],
            manufacturer="CONOW",
            model="Balcony Solar Storage",
        )

    @property
    def native_value(self) -> float | None:
        """Return current register value."""
        return self.coordinator.get_register_value("control", self._register_name)

    async def async_set_native_value(self, value: float) -> None:
        """Write register value to device."""
        await self.coordinator.async_write_register(self._register_name, value)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Modbus number entities from registers.json."""
    coordinator: ConowLocalCoordinator = entry.runtime_data
    entities = [
        ConowModbusNumber(coordinator, entry, entity_def)
        for entity_def in get_entities("number")
    ]
    async_add_entities(entities)
