"""Modbus sensor entities."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_NAME, DOMAIN
from .coordinator import ConowLocalCoordinator
from .entity_factory import build_sensor_description, register_for_entity
from .register_map import EntityDef, get_entities


class ConowModbusSensor(CoordinatorEntity[ConowLocalCoordinator], SensorEntity):
    """Sensor backed by a Modbus monitoring register."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ConowLocalCoordinator,
        entry: ConfigEntry,
        entity: EntityDef,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._register_name = entity.register
        register = register_for_entity(entity)
        self.entity_description = build_sensor_description(entity, register)
        self._attr_unique_id = f"{entry.entry_id}_{entity.code}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_DEVICE_NAME],
            manufacturer="CONOW",
            model="Balcony Solar Storage",
        )

    @property
    def native_value(self) -> float | int | None:
        """Return sensor value."""
        return self.coordinator.get_register_value("monitoring", self._register_name)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Modbus sensors from registers.json."""
    coordinator: ConowLocalCoordinator = entry.runtime_data
    entities = [
        ConowModbusSensor(coordinator, entry, entity_def)
        for entity_def in get_entities("sensor")
    ]
    async_add_entities(entities)
