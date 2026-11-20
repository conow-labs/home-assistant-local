"""Build Home Assistant entity descriptions from :class:`EntitySpec`.

Merged from the former ``entity_factory`` (v1) and ``panel_entities`` (v2):
both maps now share one description builder and every entity resolves its
name from a ``translation_key`` equal to its code.
"""

from __future__ import annotations

import math

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntityDescription,
)
from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.components.time import TimeEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory

from ..const import CONF_DEVICE_NAME, DOMAIN, LOGGER, PANEL_URL_PATH
from ..maps.entity_model import EntitySpec
from ..maps.model import PanelRegister

# Map unit strings from the JSON maps onto HA units.
HA_UNITS: dict[str, str] = {
    "W": UnitOfPower.WATT,
    "kWh": UnitOfEnergy.KILO_WATT_HOUR,
    "V": UnitOfElectricPotential.VOLT,
    "A": UnitOfElectricCurrent.AMPERE,
    "Hz": UnitOfFrequency.HERTZ,
    "%": PERCENTAGE,
    "℃": UnitOfTemperature.CELSIUS,
    "°C": UnitOfTemperature.CELSIUS,
    "dBm": SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
}

SENSOR_DEVICE_CLASSES: dict[str, SensorDeviceClass] = {
    "power": SensorDeviceClass.POWER,
    "energy": SensorDeviceClass.ENERGY,
    "energy_storage": SensorDeviceClass.ENERGY_STORAGE,
    "voltage": SensorDeviceClass.VOLTAGE,
    "current": SensorDeviceClass.CURRENT,
    "frequency": SensorDeviceClass.FREQUENCY,
    "temperature": SensorDeviceClass.TEMPERATURE,
    "signal_strength": SensorDeviceClass.SIGNAL_STRENGTH,
    "enum": SensorDeviceClass.ENUM,
    "battery": SensorDeviceClass.BATTERY,
}

SENSOR_STATE_CLASSES: dict[str, SensorStateClass] = {
    "measurement": SensorStateClass.MEASUREMENT,
    "total_increasing": SensorStateClass.TOTAL_INCREASING,
}

BINARY_DEVICE_CLASSES: dict[str, BinarySensorDeviceClass] = {
    "battery_charging": BinarySensorDeviceClass.BATTERY_CHARGING,
    "power": BinarySensorDeviceClass.POWER,
    "problem": BinarySensorDeviceClass.PROBLEM,
    "running": BinarySensorDeviceClass.RUNNING,
}

NUMBER_DEVICE_CLASSES: dict[str, NumberDeviceClass] = {
    "battery": NumberDeviceClass.BATTERY,
    "current": NumberDeviceClass.CURRENT,
    "energy": NumberDeviceClass.ENERGY,
    "energy_storage": NumberDeviceClass.ENERGY_STORAGE,
    "frequency": NumberDeviceClass.FREQUENCY,
    "power": NumberDeviceClass.POWER,
    "temperature": NumberDeviceClass.TEMPERATURE,
    "voltage": NumberDeviceClass.VOLTAGE,
}

ENTITY_CATEGORIES: dict[str, EntityCategory] = {
    "diagnostic": EntityCategory.DIAGNOSTIC,
}


def _panel_device_id(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Return the device-registry id backing this entry, if it is known."""
    device_entry = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, entry.entry_id)}
    )
    return device_entry.id if device_entry else entry.entry_id


def _panel_configuration_url(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Return an in-app link to the grouping panel for this device.

    The ``homeassistant://`` scheme is resolved by the frontend against the
    current origin, so the link works regardless of which host/port the user
    reached Home Assistant on (unlike an absolute internal-IP URL, which
    lands on a different origin and loses the session).
    """
    device_id = _panel_device_id(hass, entry)
    return f"homeassistant://{PANEL_URL_PATH}?device_id={device_id}"


def build_device_info(hass: HomeAssistant, entry: ConfigEntry) -> DeviceInfo:
    """Return the shared device info with a link to the grouping panel."""
    info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data[CONF_DEVICE_NAME],
        manufacturer="CONOW",
        model="Balcony Solar Storage",
    )
    url = _panel_configuration_url(hass, entry)
    info["configuration_url"] = url
    LOGGER.debug("Device info: panel link %s", url)
    return info


def _entity_category(spec: EntitySpec) -> EntityCategory | None:
    value = spec.register.entity_category
    if not value:
        return None
    try:
        return ENTITY_CATEGORIES[value]
    except KeyError as err:
        raise ValueError(
            f"{spec.code}: unknown entity_category {value!r}"
        ) from err


def _unit(spec: EntitySpec) -> str | None:
    return HA_UNITS.get(spec.register.unit) if spec.register.unit else None


def build_sensor_description(spec: EntitySpec) -> SensorEntityDescription:
    """Build a sensor description from an entity spec."""
    register = spec.register
    kwargs: dict[str, object] = {
        "key": spec.code,
        "translation_key": spec.translation_key,
    }
    if (unit := _unit(spec)) is not None:
        kwargs["native_unit_of_measurement"] = unit
    if register.device_class:
        try:
            kwargs["device_class"] = SENSOR_DEVICE_CLASSES[register.device_class]
        except KeyError as err:
            raise ValueError(
                f"{spec.code}: unknown device_class {register.device_class!r}"
            ) from err
        if register.device_class == "enum":
            kwargs["options"] = list((register.values or {}).values())
    if register.state_class:
        try:
            kwargs["state_class"] = SENSOR_STATE_CLASSES[register.state_class]
        except KeyError as err:
            raise ValueError(
                f"{spec.code}: unknown state_class {register.state_class!r}"
            ) from err
    if not register.values and register.dtype != "string":
        # Render the scale's decimals even when a value happens to be whole
        # (52.00 must not collapse to "52"): the map's precision is part of
        # the measurement, not an artefact of the current reading.
        kwargs["suggested_display_precision"] = number_precision(register)
    if (category := _entity_category(spec)) is not None:
        kwargs["entity_category"] = category
    return SensorEntityDescription(**kwargs)


def build_binary_sensor_description(spec: EntitySpec) -> BinarySensorEntityDescription:
    """Build a binary sensor description for a bit or a boolean register."""
    kwargs: dict[str, object] = {
        "key": spec.code,
        "translation_key": spec.translation_key,
    }
    device_class = spec.bit.device_class if spec.bit is not None else spec.register.device_class
    if device_class:
        try:
            kwargs["device_class"] = BINARY_DEVICE_CLASSES[device_class]
        except KeyError as err:
            raise ValueError(
                f"{spec.code}: unknown binary device_class {device_class!r}"
            ) from err
    if (category := _entity_category(spec)) is not None:
        kwargs["entity_category"] = category
    return BinarySensorEntityDescription(**kwargs)


def build_switch_description(spec: EntitySpec) -> SwitchEntityDescription:
    """Build a switch description from an entity spec."""
    kwargs: dict[str, object] = {
        "key": spec.code,
        "translation_key": spec.translation_key,
    }
    if (category := _entity_category(spec)) is not None:
        kwargs["entity_category"] = category
    return SwitchEntityDescription(**kwargs)


def number_precision(register: PanelRegister) -> int:
    """Return the decimal places implied by the register scale.

    A map without an explicit scale/step treats the value as an integer, so
    both the panel and the Home Assistant device page render ``800`` rather
    than ``800.0``.
    """
    scale = register.scale if register.scale and register.scale > 0 else 1.0
    return max(0, -math.floor(math.log10(scale)))


def display_value(register: PanelRegister, value: float) -> int | float:
    """Round a decoded value like the grouping panel and drop trailing zeros."""
    rounded = round(float(value), max(number_precision(register), 4))
    return int(rounded) if float(rounded).is_integer() else rounded


def _number_max(register: PanelRegister) -> float:
    """Return a display bound for registers whose map has no maximum."""
    if register.max is not None:
        return float(register.max)
    if register.unit == "%":
        return 100.0
    if register.unit == "W":
        return 30000.0
    if register.unit == "s":
        return 3600.0
    if register.unit == "min":
        return 1440.0
    return 65535.0


def build_number_description(spec: EntitySpec) -> NumberEntityDescription:
    """Build a number description for a writable numeric register."""
    register = spec.register
    precision = number_precision(register)
    kwargs: dict[str, object] = {
        "key": spec.code,
        "translation_key": spec.translation_key,
        "mode": NumberMode.AUTO,
        "native_min_value": float(register.min or 0.0),
        "native_max_value": _number_max(register),
        "native_step": 10.0**-precision,
    }
    if (unit := _unit(spec)) is not None:
        kwargs["native_unit_of_measurement"] = unit
    if register.device_class:
        try:
            kwargs["device_class"] = NUMBER_DEVICE_CLASSES[register.device_class]
        except KeyError as err:
            raise ValueError(
                f"{spec.code}: unknown number device_class {register.device_class!r}"
            ) from err
    if (category := _entity_category(spec)) is not None:
        kwargs["entity_category"] = category
    return NumberEntityDescription(**kwargs)


def build_select_description(spec: EntitySpec) -> SelectEntityDescription:
    """Build a select description for a writable enum register."""
    kwargs: dict[str, object] = {
        "key": spec.code,
        "translation_key": spec.translation_key,
        "options": list((spec.register.values or {}).values()),
    }
    if (category := _entity_category(spec)) is not None:
        kwargs["entity_category"] = category
    return SelectEntityDescription(**kwargs)


def build_time_description(spec: EntitySpec) -> TimeEntityDescription:
    """Build a time description from an entity spec."""
    kwargs: dict[str, object] = {
        "key": spec.code,
        "translation_key": spec.translation_key,
    }
    if (category := _entity_category(spec)) is not None:
        kwargs["entity_category"] = category
    return TimeEntityDescription(**kwargs)
