"""Modbus switch entities."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_NAME, DOMAIN
from .coordinator import ConowLocalCoordinator
from .entity_factory import build_switch_description
from .register_map import EntityDef, get_entities


class ConowModbusSwitch(CoordinatorEntity[ConowLocalCoordinator], SwitchEntity):
    """Writable on/off Modbus register."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ConowLocalCoordinator,
        entry: ConfigEntry,
        entity: EntityDef,
    ) -> None:
        """Initialize switch entity."""
        super().__init__(coordinator)
        self._register_name = entity.register
        self.entity_description = build_switch_description(entity)
        self._attr_unique_id = f"{entry.entry_id}_{entity.code}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_DEVICE_NAME],
            manufacturer="CONOW",
            model="Balcony Solar Storage",
        )

    @property
    def is_on(self) -> bool | None:
        """Return switch state."""
        value = self.coordinator.get_register_value("control", self._register_name)
        if value is None:
            return None
        return bool(int(value))

    async def async_turn_on(self, **kwargs: object) -> None:
        """Turn switch on."""
        await self.coordinator.async_write_register_raw(self._register_name, 1)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Turn switch off."""
        await self.coordinator.async_write_register_raw(self._register_name, 0)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Modbus switch entities from registers.json."""
    coordinator: ConowLocalCoordinator = entry.runtime_data
    entities = [
        ConowModbusSwitch(coordinator, entry, entity_def)
        for entity_def in get_entities("switch")
    ]
    async_add_entities(entities)
