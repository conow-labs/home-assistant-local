"""Map registers to Home Assistant entity specifications.

This module is the single source of truth for **which** entities a map
exposes, their platform and their unique-id suffix.  The platform modules,
the registry pruning in ``__init__`` and the grouping panel all consume
``EntitySpec`` instead of re-deriving the rules.

Classification (identical for both maps):

* a register with ``bits`` yields one read-only binary sensor per bit and no
  entity for the raw register;
* a writable boolean yields a switch;
* a writable ``hhmm`` register yields a time entity;
* a writable numeric register yields a number entity;
* a writable enum yields a select entity;
* a read-only boolean yields a binary sensor;
* anything else read-only (numeric, enum, string) yields a sensor.

Every writable entity is visible on the device page.  The platform actions
themselves refuse to write and point at the grouping panel, where the whole
group is validated and sent atomically.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache

from .model import PanelBit, PanelRegister, get_registers, register_available
from .registry import MAP_V1

SENSOR = "sensor"
BINARY_SENSOR = "binary_sensor"
NUMBER = "number"
SELECT = "select"
SWITCH = "switch"
TIME = "time"


@dataclass(frozen=True, slots=True)
class EntitySpec:
    """One HA entity backed by a register or a status bit."""

    platform: str
    code: str
    unique_code: str
    translation_key: str
    register: PanelRegister
    bit: PanelBit | None = None

    @property
    def unique_id_suffix(self) -> str:
        """Return the suffix used after ``<entry_id>_`` in the registry."""
        return self.unique_code


def _register_platform(register: PanelRegister) -> str | None:
    """Return the platform for a register without bits."""
    if register.writable:
        if register.boolean:
            return SWITCH
        if register.is_time:
            return TIME
        if register.values:
            return SELECT
        if register.dtype != "string":
            return NUMBER
        return None
    if register.boolean:
        return BINARY_SENSOR
    return SENSOR


@lru_cache(maxsize=4)
def _raw_specs(map_version: str, new_model: bool = True) -> tuple[EntitySpec, ...]:
    """Return specs before unique-id disambiguation.

    ``new_model=False`` (an old unit, or an unreadable SN) drops the registers
    flagged ``new_model_only``: the hardware cannot answer them.
    """
    specs: list[EntitySpec] = []
    for register in get_registers(map_version):
        if not register_available(register, new_model):
            continue
        if register.bits:
            # The bitmask register itself never becomes an entity; the panel
            # renders each bit as its own read-only row.
            for bit in register.bits:
                specs.append(
                    EntitySpec(
                        platform=BINARY_SENSOR,
                        code=bit.code,
                        unique_code=bit.code,
                        translation_key=bit.code,
                        register=register,
                        bit=bit,
                    )
                )
            continue
        classified = _register_platform(register)
        if classified is None:
            continue
        specs.append(
            EntitySpec(
                platform=classified,
                code=register.code,
                unique_code=register.code,
                translation_key=register.code,
                register=register,
            )
        )
    return tuple(specs)


@lru_cache(maxsize=4)
def build_entity_specs(
    map_version: str, new_model: bool = True
) -> tuple[EntitySpec, ...]:
    """Return the entity specs of a map with final unique-id suffixes.

    Status bits keep the historical ``status_`` prefix.  On the v2 map a
    register whose ``(platform, code)`` also exists in the v1 map gets the
    ``panel_`` prefix so upgrading from v1 does not collide in the registry.
    """
    specs = _raw_specs(map_version, new_model)
    if map_version == MAP_V1:
        taken: set[tuple[str, str]] = set()
    else:
        taken = {
            (spec.platform, spec.code) for spec in _raw_specs(MAP_V1, new_model)
        }
    result: list[EntitySpec] = []
    for spec in specs:
        if spec.bit is not None:
            unique_code = f"status_{spec.code}"
        elif (spec.platform, spec.code) in taken:
            unique_code = f"panel_{spec.code}"
        else:
            unique_code = spec.code
        result.append(replace(spec, unique_code=unique_code))
    unique_codes = [spec.unique_code for spec in result]
    if len(set(unique_codes)) != len(unique_codes):
        duplicates = sorted(
            {code for code in unique_codes if unique_codes.count(code) > 1}
        )
        raise ValueError(f"{map_version}: duplicate unique codes {duplicates}")
    return tuple(result)


def specs_for_platform(
    map_version: str, platform: str, new_model: bool = True
) -> tuple[EntitySpec, ...]:
    """Return the entity specs of one platform for this hardware generation."""
    return tuple(
        spec
        for spec in build_entity_specs(map_version, new_model)
        if spec.platform == platform
    )


def entity_registry_keys(
    entry_id: str, map_version: str, new_model: bool = True
) -> dict[str, str]:
    """Return ``{unique_id: platform}`` that the active map owns."""
    return {
        f"{entry_id}_{spec.unique_code}": spec.platform
        for spec in build_entity_specs(map_version, new_model)
    }


def panel_code_map(
    map_version: str, new_model: bool = True
) -> dict[str, str]:
    """Return ``{register/bit code: unique_code}`` for panel entity links."""
    return {
        spec.code: spec.unique_code
        for spec in build_entity_specs(map_version, new_model)
    }
