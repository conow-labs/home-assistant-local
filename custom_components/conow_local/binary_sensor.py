"""Modbus binary sensor entities."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_NAME, DOMAIN
from .coordinator import ConowLocalCoordinator
from .entity_factory import build_binary_sensor_description
from .register_map import EntityDef, get_entities


class ConowModbusBinarySensor(
    CoordinatorEntity[ConowLocalCoordinator], BinarySensorEntity
):
    """Binary sensor for system status bits."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ConowLocalCoordinator,
        entry: ConfigEntry,
        entity: EntityDef,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(coordinator)
        self._bit_name = entity.code
        self.entity_description = build_binary_sensor_description(entity)
        self._attr_unique_id = f"{entry.entry_id}_status_{entity.code}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_DEVICE_NAME],
            manufacturer="CONOW",
            model="Balcony Solar Storage",
        )

    @property
    def is_on(self) -> bool | None:
        """Return parsed status bit."""
        return self.coordinator.get_status_bit(self._bit_name)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Modbus binary sensors from registers.json."""
    coordinator: ConowLocalCoordinator = entry.runtime_data
    entities = [
        ConowModbusBinarySensor(coordinator, entry, entity_def)
        for entity_def in get_entities("binary_sensor")
    ]
    async_add_entities(entities)
