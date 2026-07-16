"""Build Home Assistant entity descriptions from registers.json."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.helpers.entity import EntityCategory

from .register_map import EntityDef, RegisterDef, REGISTERS_BY_NAME

HA_UNITS = {
    "V": UnitOfElectricPotential.VOLT,
    "kWh": UnitOfEnergy.KILO_WATT_HOUR,
    "%": PERCENTAGE,
    "W": UnitOfPower.WATT,
    "Hz": UnitOfFrequency.HERTZ,
    "°C": UnitOfTemperature.CELSIUS,
}

ENTITY_CATEGORIES = {
    "diagnostic": EntityCategory.DIAGNOSTIC,
}


def _unit_for_register(register: RegisterDef | None) -> str | None:
    """Map register unit string to Home Assistant unit constant."""
    if register is None or not register.unit:
        return None
    return HA_UNITS.get(register.unit)


def build_sensor_description(
    entity: EntityDef, register: RegisterDef | None
) -> SensorEntityDescription:
    """Build sensor entity description from JSON definitions."""
    kwargs: dict[str, object] = {
        "key": entity.code,
        "translation_key": entity.code,
    }
    if entity.device_class:
        kwargs["device_class"] = entity.device_class
    if entity.state_class:
        kwargs["state_class"] = entity.state_class
    if entity.entity_category:
        kwargs["entity_category"] = ENTITY_CATEGORIES[entity.entity_category]
    unit = _unit_for_register(register)
    if unit is not None:
        kwargs["native_unit_of_measurement"] = unit
    return SensorEntityDescription(**kwargs)


def build_binary_sensor_description(entity: EntityDef) -> BinarySensorEntityDescription:
    """Build binary sensor entity description from JSON definitions."""
    kwargs: dict[str, object] = {
        "key": entity.code,
        "translation_key": entity.code,
    }
    if entity.device_class:
        kwargs["device_class"] = entity.device_class
    return BinarySensorEntityDescription(**kwargs)


def build_number_description(
    entity: EntityDef, register: RegisterDef | None
) -> NumberEntityDescription:
    """Build number entity description from JSON definitions."""
    kwargs: dict[str, object] = {
        "key": entity.code,
        "translation_key": entity.code,
    }
    if entity.min_value is not None:
        kwargs["native_min_value"] = entity.min_value
    if entity.max_value is not None:
        kwargs["native_max_value"] = entity.max_value
    if entity.step is not None:
        kwargs["native_step"] = entity.step
    unit = _unit_for_register(register)
    if unit is not None:
        kwargs["native_unit_of_measurement"] = unit
    return NumberEntityDescription(**kwargs)


def build_switch_description(entity: EntityDef) -> SwitchEntityDescription:
    """Build switch entity description from JSON definitions."""
    return SwitchEntityDescription(
        key=entity.code,
        translation_key=entity.code,
    )


def build_select_description(entity: EntityDef) -> SelectEntityDescription:
    """Build select entity description from JSON definitions."""
    return SelectEntityDescription(
        key=entity.code,
        translation_key=entity.code,
    )


def register_for_entity(entity: EntityDef) -> RegisterDef | None:
    """Return backing register definition for an entity."""
    return REGISTERS_BY_NAME.get(entity.register)
