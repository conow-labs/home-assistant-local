"""Modbus select entity for charge/discharge direction."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_NAME, DOMAIN
from .coordinator import ConowLocalCoordinator
from .entity_factory import build_select_description
from .register_map import DIRECTION_IDLE, EntityDef, get_entities


class ConowModbusDirectionSelect(
    CoordinatorEntity[ConowLocalCoordinator], SelectEntity
):
    """Select entity driven by registers.json."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ConowLocalCoordinator,
        entry: ConfigEntry,
        entity: EntityDef,
    ) -> None:
        """Initialize select entity."""
        super().__init__(coordinator)
        self._entity = entity
        self._register_name = entity.register
        self.entity_description = build_select_description(entity)
        self._attr_unique_id = f"{entry.entry_id}_{entity.code}"
        self._attr_options = list((entity.options or {}).keys())
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_DEVICE_NAME],
            manufacturer="CONOW",
            model="Balcony Solar Storage",
        )

    @property
    def current_option(self) -> str | None:
        """Return current direction option."""
        value = self.coordinator.get_register_value("control", self._register_name)
        if value is None or not self._entity.options:
            return None
        raw = int(value)
        for option, option_value in self._entity.options.items():
            if option_value == raw:
                return option
        return None

    async def async_select_option(self, option: str) -> None:
        """Write selected direction to device."""
        if not self._entity.options:
            return
        direction = self._entity.options[option]
        if self._entity.write_handler == "force_mode":
            power = int(
                self.coordinator.get_register_value(
                    "control", "battery_target_power"
                )
                or 0
            )
            cutoff = int(
                self.coordinator.get_register_value(
                    "control", "battery_cutoff_soc"
                )
                or 0
            )
            if direction != DIRECTION_IDLE:
                if power <= 0:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="force_mode_power_required",
                    )
                if not 1 <= cutoff <= 100:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="force_mode_cutoff_required",
                    )
            await self.coordinator.async_write_force_mode(direction, power, cutoff)
            return
        await self.coordinator.async_write_register_raw(self._register_name, direction)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Modbus select entities from registers.json."""
    coordinator: ConowLocalCoordinator = entry.runtime_data
    entities = [
        ConowModbusDirectionSelect(coordinator, entry, entity_def)
        for entity_def in get_entities("select")
    ]
    async_add_entities(entities)
