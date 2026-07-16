"""Load Modbus register and entity definitions from registers.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

RegisterType = Literal["uint16", "int16", "uint32"]
EntityPlatform = Literal["sensor", "binary_sensor", "number", "switch", "select"]

DEFAULT_SLAVE = 0xA0
DEFAULT_BAUDRATE = 38400

_MAP_PATH = Path(__file__).with_name("registers.json")


@dataclass(frozen=True, slots=True)
class RegisterDef:
    """Single Modbus register or 32-bit pair definition."""

    address: int
    name: str
    block: str
    dtype: RegisterType
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    writable: bool = False
    decode: str = ""

    @property
    def register_count(self) -> int:
        """Return number of 16-bit registers occupied."""
        return 2 if self.dtype == "uint32" else 1


@dataclass(frozen=True, slots=True)
class EntityDef:
    """Home Assistant entity backed by a register or status bit."""

    code: str
    platform: EntityPlatform
    register: str
    bit: int | None = None
    device_class: str | None = None
    state_class: str | None = None
    entity_category: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    options: dict[str, int] | None = None
    write_handler: str | None = None


@dataclass(frozen=True, slots=True)
class ForceModeSequence:
    """Ordered register write sequence for forced charge/discharge."""

    register_names: tuple[str, ...]
    idle_register: str
    idle_value: int


def _block_count(registers: list[RegisterDef], block: str, start: int) -> int:
    """Compute Modbus read count for a contiguous register block."""
    block_regs = [item for item in registers if item.block == block]
    if not block_regs:
        return 0
    end = max(item.address + item.register_count for item in block_regs)
    return end - start


@lru_cache(maxsize=1)
def _load_map() -> dict[str, Any]:
    """Parse registers.json once per process."""
    with _MAP_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _build_registers() -> tuple[list[RegisterDef], dict[str, RegisterDef], dict[int, RegisterDef]]:
    """Build register definitions and lookup tables."""
    data = _load_map()
    registers: list[RegisterDef] = []
    for item in data["registers"]:
        registers.append(
            RegisterDef(
                address=int(item["address"]),
                name=item["code"],
                block=item["block"],
                dtype=item["dtype"],
                scale=float(item.get("scale", 1.0)),
                offset=float(item.get("offset", 0.0)),
                unit=item.get("unit", ""),
                writable=bool(item.get("writable", False)),
                decode=item.get("decode", ""),
            )
        )
    registers.sort(key=lambda reg: reg.address)
    by_name = {item.name: item for item in registers}
    by_address = {item.address: item for item in registers}
    return registers, by_name, by_address


@lru_cache(maxsize=1)
def _build_entities() -> tuple[list[EntityDef], dict[str, list[EntityDef]]]:
    """Build entity definitions grouped by platform."""
    data = _load_map()
    entities: list[EntityDef] = []
    for item in data["entities"]:
        options = item.get("options")
        entities.append(
            EntityDef(
                code=item["code"],
                platform=item["platform"],
                register=item["register"],
                bit=item.get("bit"),
                device_class=item.get("device_class"),
                state_class=item.get("state_class"),
                entity_category=item.get("entity_category"),
                min_value=item.get("min"),
                max_value=item.get("max"),
                step=item.get("step"),
                options=dict(options) if options else None,
                write_handler=item.get("write_handler"),
            )
        )
    by_platform: dict[str, list[EntityDef]] = {}
    for entity in entities:
        by_platform.setdefault(entity.platform, []).append(entity)
    return entities, by_platform


def get_block_starts() -> dict[str, int]:
    """Return Modbus block start addresses from JSON."""
    blocks = _load_map()["blocks"]
    return {name: int(cfg["start"]) for name, cfg in blocks.items()}


_BLOCK_STARTS = get_block_starts()
MONITORING_START = _BLOCK_STARTS["monitoring"]
CONTROL_START = _BLOCK_STARTS["control"]

_ALL_REGISTERS, REGISTERS_BY_NAME, REGISTERS_BY_ADDRESS = _build_registers()
_ALL_ENTITIES, ENTITIES_BY_PLATFORM = _build_entities()

MONITORING_REGISTERS = [item for item in _ALL_REGISTERS if item.block == "monitoring"]
CONTROL_REGISTERS = [item for item in _ALL_REGISTERS if item.block == "control"]

MONITORING_COUNT = _block_count(_ALL_REGISTERS, "monitoring", MONITORING_START)
CONTROL_COUNT = _block_count(_ALL_REGISTERS, "control", CONTROL_START)


def get_entities(platform: EntityPlatform) -> list[EntityDef]:
    """Return entity definitions for a Home Assistant platform."""
    return list(ENTITIES_BY_PLATFORM.get(platform, []))


@lru_cache(maxsize=1)
def get_status_bits() -> dict[int, str]:
    """Return system status bit index to entity code mapping."""
    bits: dict[int, str] = {}
    for entity in get_entities("binary_sensor"):
        if entity.bit is not None:
            bits[entity.bit] = entity.code
    return bits


# Backward-compatible alias used by client.py
SYSTEM_STATUS_BITS = get_status_bits()


@lru_cache(maxsize=1)
def get_force_mode_sequence() -> ForceModeSequence:
    """Return force charge/discharge write sequence from JSON."""
    data = _load_map()["sequences"]["force_mode"]
    register_names = tuple(data["registers"])
    return ForceModeSequence(
        register_names=register_names,
        idle_register=data["idle_register"],
        idle_value=int(data["idle_value"]),
    )


def get_direction_entity() -> EntityDef:
    """Return the charge/discharge direction select entity."""
    for entity in get_entities("select"):
        if entity.write_handler == "force_mode":
            return entity
    raise RuntimeError("force_mode select entity not found in registers.json")


_DIRECTION_ENTITY = get_direction_entity()
DIRECTION_IDLE = (_DIRECTION_ENTITY.options or {}).get("idle", 0)
DIRECTION_FORCE_CHARGE = (_DIRECTION_ENTITY.options or {}).get("force_charge", 1)
DIRECTION_FORCE_DISCHARGE = (_DIRECTION_ENTITY.options or {}).get("force_discharge", 2)
