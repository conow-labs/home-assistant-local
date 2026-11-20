"""Unified register-map model for v1 and v2.

Both map files use one schema: every register carries its own ``name``,
decoding metadata (``device_class``, ``state_class``, ``values``, ...),
optional ``bits`` and write bounds.  The model decodes blocks, computes
panel bounds and encodes submitted values; it is the single parser shared
by the coordinator, the HA entity layer and the grouping panel.

The map version is mandatory everywhere: a forgotten argument must fail
loudly instead of silently reading the v2 map.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any

from .registry import MAP_PATHS, map_path, map_source

SUPPORTED_DTYPES = ("uint16", "int16", "uint32", "int32", "string")
MAX_BLOCK_REGISTERS = 125  # Modbus FC 0x03 limit
TIME_FORMAT = "hhmm"  # high byte = hour, low byte = minute
DTYPE_RANGES: dict[str, tuple[int, int]] = {
    "uint16": (0, 0xFFFF),
    "int16": (-0x8000, 0x7FFF),
    "uint32": (0, 0xFFFFFFFF),
    "int32": (-0x80000000, 0x7FFFFFFF),
}


@dataclass(frozen=True, slots=True)
class PanelBit:
    """One binary sensor decomposed from a bitmask register."""

    code: str
    name: str
    bit: int
    device_class: str


@dataclass(frozen=True, slots=True)
class PanelRegister:
    """One register (or multi-register field) from a map."""

    code: str
    name: str
    address: int
    address_hex: str
    block: str
    dtype: str
    length: int
    writable: bool
    scale: float
    offset: float
    unit: str
    device_class: str
    state_class: str
    entity_category: str
    values: dict[int, str] | None
    note: str
    fmt: str
    min: float | None
    max: float | None
    boolean: bool
    new_model_only: bool = False
    hidden: bool = False
    # ``(code, allowed_raw_values)``: the setting only applies when another
    # register of the same group holds one of these raw values.  The panel
    # disables the control otherwise, and the write plan keeps the value the
    # device already holds for the field that does not apply.
    enabled_when: tuple[str, tuple[int, ...]] | None = None
    bits: tuple[PanelBit, ...] = ()

    @property
    def register_count(self) -> int:
        """Number of 16-bit registers occupied."""
        return self.length

    @property
    def is_time(self) -> bool:
        """Return whether the register holds an HH:MM time value."""
        return self.fmt == TIME_FORMAT


@dataclass(frozen=True, slots=True)
class PanelSubgroup:
    """Optional nested section that groups related rows inside a group."""

    label: str
    members: tuple[str, ...]
    key: str = ""


@dataclass(frozen=True, slots=True)
class PanelGroup:
    """Function group from ``groups[]``."""

    id: str
    label: str
    icon: str
    order: int
    atomic: bool
    members: tuple[str, ...]
    subgroups: tuple[PanelSubgroup, ...]
    span_start: int
    span_end: int
    span_registers: int
    note: str
    count_register: str


@lru_cache(maxsize=len(MAP_PATHS))
def _load(map_version: str) -> dict[str, Any]:
    with map_path(map_version).open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=len(MAP_PATHS))
def get_registers(map_version: str) -> tuple[PanelRegister, ...]:
    """Return every register of one map, ordered by address."""
    data = _load(map_version)
    registers: list[PanelRegister] = []
    for item in data["registers"]:
        dtype = item["dtype"]
        if dtype not in SUPPORTED_DTYPES:
            raise ValueError(f"Unsupported dtype {dtype!r} for {item['code']}")
        boolean = bool(item.get("boolean", False))
        if boolean and set(item.get("values", {})) != {"0", "1"}:
            raise ValueError(
                f"{item['code']}: boolean registers need exactly 0/1 values"
            )
        bits = tuple(
            PanelBit(
                code=bit["code"],
                name=bit.get("name") or bit["code"],
                bit=int(bit["bit"]),
                device_class=str(bit.get("device_class") or ""),
            )
            for bit in item.get("bits", ())
        )
        if len({bit.bit for bit in bits}) != len(bits):
            raise ValueError(f"{item['code']}: duplicate bit index in bits[]")
        dependency = item.get("enabled_when")
        enabled_when = (
            (
                str(dependency["code"]),
                tuple(int(value) for value in dependency.get("values", ())),
            )
            if dependency
            else None
        )
        registers.append(
            PanelRegister(
                code=item["code"],
                name=item.get("name") or item["code"],
                address=int(item["address"]),
                address_hex=item.get("address_hex") or f"0x{int(item['address']):04X}",
                block=item["block"],
                dtype=dtype,
                length=int(item.get("length", 2 if dtype in ("uint32", "int32") else 1)),
                writable=bool(item.get("writable", False)),
                scale=float(item.get("scale", 1.0)),
                offset=float(item.get("offset", 0.0)),
                unit=item.get("unit", ""),
                device_class=str(item.get("device_class") or ""),
                state_class=str(item.get("state_class") or ""),
                entity_category=str(item.get("entity_category") or ""),
                values=(
                    {int(key): str(value) for key, value in item["values"].items()}
                    if item.get("values")
                    else None
                ),
                note=item.get("note", ""),
                fmt=str(item.get("format", "")),
                min=None if item.get("min") is None else float(item["min"]),
                max=None if item.get("max") is None else float(item["max"]),
                boolean=boolean,
                new_model_only=bool(item.get("new_model_only", False)),
                hidden=bool(item.get("hidden", False)),
                enabled_when=enabled_when,
                bits=bits,
            )
        )
    registers.sort(key=lambda reg: reg.address)
    return tuple(registers)


@lru_cache(maxsize=len(MAP_PATHS))
def get_register_index(map_version: str) -> dict[str, PanelRegister]:
    return {reg.code: reg for reg in get_registers(map_version)}


@lru_cache(maxsize=len(MAP_PATHS))
def get_groups(map_version: str) -> tuple[PanelGroup, ...]:
    """Return groups ordered by ``order``."""
    index = get_register_index(map_version)
    groups: list[PanelGroup] = []
    for item in _load(map_version).get("groups", ()):
        members = tuple(item["members"])
        missing = [code for code in members if code not in index]
        if missing:
            raise ValueError(f"Group {item['id']} references unknown registers {missing}")
        span = item.get("span", {})
        subgroups: list[PanelSubgroup] = []
        for sub in item.get("subgroups", ()):
            sub_members = tuple(sub["members"])
            unknown = [code for code in sub_members if code not in members]
            if unknown:
                raise ValueError(
                    f"Group {item['id']} subgroup references foreign registers {unknown}"
                )
            subgroups.append(
                PanelSubgroup(
                    label=sub.get("label") or "",
                    members=sub_members,
                    key=str(sub.get("key") or ""),
                )
            )
        count_register = str(
            item.get("count_register")
            or item.get("write_chunk", {}).get("count_register", "")
        )
        if count_register and count_register not in members:
            raise ValueError(
                f"Group {item['id']} counts slots with foreign register {count_register}"
            )
        groups.append(
            PanelGroup(
                id=item["id"],
                label=item.get("label") or item["id"],
                icon=item.get("icon", "mdi:view-grid-plus-outline"),
                order=int(item.get("order", 0)),
                atomic=bool(item.get("atomic", False)),
                members=members,
                subgroups=tuple(subgroups),
                span_start=int(span.get("start", index[members[0]].address)),
                span_end=int(span.get("end", index[members[-1]].address)),
                span_registers=int(span.get("registers", 0)),
                note=item.get("note", ""),
                count_register=count_register,
            )
        )
    groups.sort(key=lambda group: (group.order, group.id))
    return tuple(groups)


OLD_MODEL_SN_LETTERS = frozenset("ABCDEFGHIJ")


def is_new_model(serial: str | None) -> bool:
    """Return whether a device serial number marks a new-model unit.

    The third character encodes the hardware generation: ``A``–``J`` is the
    old model, whose firmware does not implement the registers flagged
    ``new_model_only``.  A missing or too-short serial number is treated as
    the old model, so unreadable device data never exposes controls the
    hardware cannot honour.
    """
    if not serial or len(serial) < 3:
        return False
    return serial[2].upper() not in OLD_MODEL_SN_LETTERS


def values_new_model(values: dict[str, dict[str, Any]] | None) -> bool:
    """Return the hardware generation implied by a decoded snapshot."""
    serial = ((values or {}).get("device_serial") or {}).get("value")
    return is_new_model(serial if isinstance(serial, str) else None)


def register_available(register: PanelRegister, new_model: bool) -> bool:
    """Return whether the register is exposed for this hardware generation.

    ``hidden`` registers are not implemented yet: they stay decoded but are
    kept out of the panel and the entity layer on every model.
    """
    if register.hidden:
        return False
    return new_model or not register.new_model_only


def get_groups_for_model(
    map_version: str, new_model: bool
) -> tuple[PanelGroup, ...]:
    """Return groups with registers this hardware generation lacks removed.

    A group whose every member is new-model-only (the generator/DO block on an
    old unit) is dropped entirely; subgroups follow the same rule.
    """
    index = get_register_index(map_version)
    groups: list[PanelGroup] = []
    for group in get_groups(map_version):
        members = tuple(
            code
            for code in group.members
            if register_available(index[code], new_model)
        )
        if not members:
            continue
        subgroups = tuple(
            PanelSubgroup(
                label=subgroup.label,
                members=tuple(
                    code
                    for code in subgroup.members
                    if register_available(index[code], new_model)
                ),
                key=subgroup.key,
            )
            for subgroup in group.subgroups
        )
        groups.append(
            replace(
                group,
                members=members,
                subgroups=tuple(subgroup for subgroup in subgroups if subgroup.members),
                count_register=(
                    group.count_register if group.count_register in members else ""
                ),
            )
        )
    return tuple(groups)


def get_group(group_id: str, map_version: str) -> PanelGroup | None:
    return next(
        (group for group in get_groups(map_version) if group.id == group_id), None
    )


@lru_cache(maxsize=len(MAP_PATHS))
def get_block_spans(map_version: str) -> dict[str, tuple[int, int]]:
    """Return ``block -> (start, register count)`` for FC 0x03 reads."""
    spans: dict[str, tuple[int, int]] = {}
    for register in get_registers(map_version):
        start, count = spans.get(register.block, (register.address, 0))
        start = min(start, register.address)
        end = max(register.address + register.register_count, start + count)
        spans[register.block] = (start, end - start)
    for block, (_, count) in spans.items():
        if not 1 <= count <= MAX_BLOCK_REGISTERS:
            raise ValueError(
                f"Block {block!r} spans {count} registers (FC 0x03 max "
                f"{MAX_BLOCK_REGISTERS})"
            )
    return spans


def get_map_meta(map_version: str) -> dict[str, Any]:
    """Return version/meta/protocol information for the frontend."""
    data = _load(map_version)
    return {
        "version": data.get("version"),
        "meta": data.get("meta", {}),
        "protocol": data.get("protocol", {}),
        "blocks": data.get("blocks", {}),
        "source": map_source(map_version),
    }


def preload() -> None:
    """Load and validate every map; call from an executor thread, not the loop."""
    for map_version in MAP_PATHS:
        get_registers(map_version)
        get_register_index(map_version)
        get_groups(map_version)
        get_block_spans(map_version)
        _load(map_version)


def decode_raw(register: PanelRegister, words: list[int], index: int) -> int | str | None:
    """Decode one field starting at ``index`` in a block read."""
    length = register.register_count
    if index + length > len(words):
        return None
    chunk = words[index : index + length]
    if register.dtype in ("uint32", "int32"):
        raw = (chunk[0] << 16) | chunk[1]
        if register.dtype == "int32" and raw & 0x80000000:
            raw -= 0x100000000
        return raw
    if register.dtype == "int16":
        return struct.unpack(">h", struct.pack(">H", chunk[0] & 0xFFFF))[0]
    if register.dtype == "string":
        data = b"".join(struct.pack(">H", word & 0xFFFF) for word in chunk)
        return data.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    return chunk[0]


def to_physical(register: PanelRegister, raw: int | str) -> float | str:
    """Apply scale/offset for numeric registers."""
    if isinstance(raw, str):
        return raw
    if register.is_time:
        return f"{(raw >> 8) & 0xFF:02d}:{raw & 0xFF:02d}"
    return (raw - register.offset) * register.scale


def _physical_value(values: dict[str, dict[str, Any]], code: str) -> float | None:
    """Return a decoded live value in physical units, if it is numeric."""
    value = (values.get(code) or {}).get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _positive_value(values: dict[str, dict[str, Any]], code: str) -> float | None:
    """Return a live value only when it is a usable positive limit."""
    value = _physical_value(values, code)
    return value if value is not None and value > 0 else None


def _max_ac_power(values: dict[str, dict[str, Any]]) -> float | None:
    """Return the larger of the two AC power limits currently configured."""
    limits = [
        _positive_value(values, code)
        for code in ("ac_charge_power_limit", "ac_discharge_power_limit")
    ]
    limits = [limit for limit in limits if limit is not None]
    return max(limits) if limits else None


def _cutoff_direction(values: dict[str, dict[str, Any]]) -> int | None:
    """Return the forced charge/discharge direction (1=charge, 2=discharge)."""
    direction = _physical_value(values, "charge_discharge_direction")
    return int(direction) if direction is not None else None


def _cutoff_soc_min(values: dict[str, dict[str, Any]]) -> float | None:
    """Lower bound of the cutoff SoC while a forced run is active.

    Both directions start at the safety SoC: charging must not stop below
    it, and a forced discharge must not drain below it either.
    """
    return _physical_value(values, "safety_soc")


def _cutoff_soc_max(values: dict[str, dict[str, Any]]) -> float | None:
    """Upper bound of the cutoff SoC while a forced run is active.

    Charging may go up to 100 %; a forced discharge stops at the cutoff, so
    it cannot be set above the current battery SoC.
    """
    if _cutoff_direction(values) == 2:
        return _battery_soc(values)
    return None


def _grid_export_limit(
    values: dict[str, dict[str, Any]],
) -> float | None:
    """Return the grid-tied output limit currently in force.

    Until it is unlocked in the app this register holds the local regulatory
    value; afterwards it reports the hardware maximum AC discharge power.
    """
    return _positive_value(values, "grid_code_export_limit")


def _battery_soc(values: dict[str, dict[str, Any]]) -> float | None:
    """Return the live battery SoC, favouring the v2 ``system_soc`` code."""
    for code in ("system_soc", "battery_soc"):
        soc = _physical_value(values, code)
        if soc is not None:
            return soc
    return None


# Some writable registers are not bounded by the protocol table alone: their
# limit comes from another register's live value (hardware capability, grid
# code, safety SoC).  Keys are the constrained register; each callable returns
# the effective lower or upper limit in physical units.  Read-only registers
# are decoded from the same block read, so no extra Modbus traffic is needed.
_DYNAMIC_MIN = {
    "battery_cutoff_soc": _cutoff_soc_min,
    "charge_discharge_cutoff_soc": _cutoff_soc_min,
    "backup_soc": lambda values: _physical_value(values, "safety_soc"),
}
_DYNAMIC_MAX = {
    "battery_cutoff_soc": _cutoff_soc_max,
    "charge_discharge_cutoff_soc": _cutoff_soc_max,
    "ac_charge_power_limit": lambda values: _positive_value(
        values, "hardware_max_ac_charge_power"
    ),
    "ac_discharge_power_limit": lambda values: _positive_value(
        values, "grid_code_export_limit"
    ),
    "allow_reverse_power": lambda values: _positive_value(
        values, "grid_code_export_limit"
    ),
    "battery_target_power": _max_ac_power,
}
# A TOU slot only uses one of its two power/SoC fields, depending on its
# 工作模式: charging may only raise the SoC above the current level, and a
# discharge slot may only ask for what may be exported to the grid right now.
for _slot in range(1, 9):
    _DYNAMIC_MIN[f"tou_slot{_slot}_target_soc"] = _battery_soc
    _DYNAMIC_MAX[f"tou_slot{_slot}_power"] = _grid_export_limit


def numeric_bounds(
    register: PanelRegister,
    values: dict[str, dict[str, Any]] | None = None,
) -> tuple[float, float, float] | None:
    """Return (min, max, step) in physical units for numeric registers.

    Percent registers get an explicit 0–100 range so the panel can render
    them as a slider instead of a free-form number field.  When ``values``
    holds the decoded live map, limits that depend on another register (for
    example ``backup_soc`` >= ``safety_soc`` or the AC power limit capped by
    the hardware maximum) are narrowed to the current device state.
    """
    if register.dtype == "string" or register.values or register.is_time:
        return None
    if register.scale:
        low, high = DTYPE_RANGES[register.dtype]
        fallback = (
            round(low * register.scale + register.offset, 6),
            round(high * register.scale + register.offset, 6),
        )
    else:
        fallback = (0.0, 0.0)
    if register.min is not None or register.max is not None:
        # Explicit device-documented limits (e.g. slot count 1–8) win over
        # the dtype range, which is meaningless for such small integers.
        low = float(register.min) if register.min is not None else fallback[0]
        high = float(register.max) if register.max is not None else fallback[1]
        step = register.scale or 1.0
    elif register.unit == "%":
        low, high, step = 0.0, 100.0, 1.0
    elif not register.scale:
        return None
    else:
        low, high, step = fallback[0], fallback[1], register.scale

    if values:
        dynamic_min = _DYNAMIC_MIN.get(register.code)
        if dynamic_min is not None:
            limit = dynamic_min(values)
            if limit is not None:
                low = max(low, limit)
        dynamic_max = _DYNAMIC_MAX.get(register.code)
        if dynamic_max is not None:
            limit = dynamic_max(values)
            if limit is not None:
                high = min(high, limit)
        if high < low:
            high = low
    return (low, high, step)


def encode_value(register: PanelRegister, value: Any) -> list[int]:
    """Encode a physical/enum value into the register's 16-bit words.

    Raises ``ValueError`` when the value is missing, not a valid enum option,
    or outside the dtype range.
    """
    if register.dtype == "string":
        text = "" if value is None else str(value)
        try:
            encoded = text.encode("ascii")
        except UnicodeEncodeError as err:
            raise ValueError(f"{register.code}: only ASCII is supported") from err
        size = register.register_count * 2
        if len(encoded) > size:
            raise ValueError(f"{register.code}: string longer than {size} bytes")
        encoded = encoded.ljust(size, b"\x00")
        return [
            (encoded[index] << 8) | encoded[index + 1]
            for index in range(0, size, 2)
        ]

    if register.is_time:
        parts = str(value).strip().split(":")
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except (IndexError, TypeError, ValueError) as err:
            raise ValueError(f"{register.code}: expected HH:MM, got {value!r}") from err
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"{register.code}: time out of range {value!r}")
        return [(hour << 8) | minute]

    if register.values:
        if isinstance(value, str) and not value.isdigit():
            for raw_key, label in register.values.items():
                if label == value:
                    raw_value = raw_key
                    break
            else:
                raise ValueError(
                    f"{register.code}: {value!r} is not one of " +
                    ", ".join(register.values.values())
                )
        else:
            raw_value = int(value)
        if raw_value not in register.values:
            raise ValueError(f"{register.code}: unknown enum value {raw_value}")
    else:
        try:
            physical = float(value)
        except (TypeError, ValueError) as err:
            raise ValueError(f"{register.code}: {value!r} is not a number") from err
        if not register.scale:
            raise ValueError(f"{register.code}: register has no scale")
        if register.min is not None and physical < register.min:
            raise ValueError(
                f"{register.code}: {physical:g} is below minimum {register.min:g}"
            )
        if register.max is not None and physical > register.max:
            raise ValueError(
                f"{register.code}: {physical:g} is above maximum {register.max:g}"
            )
        raw_value = round((physical - register.offset) / register.scale)

    low, high = DTYPE_RANGES[register.dtype]
    if not low <= raw_value <= high:
        raise ValueError(
            f"{register.code}: raw {raw_value} outside {register.dtype} range"
        )
    if register.dtype in ("uint32", "int32"):
        unsigned = raw_value & 0xFFFFFFFF
        return [(unsigned >> 16) & 0xFFFF, unsigned & 0xFFFF]
    return [raw_value & 0xFFFF]


def describe_value(register: PanelRegister, raw: int | str | None) -> str:
    """Render a register value for the panel."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if register.values and raw in register.values:
        return register.values[raw]
    value = to_physical(register, raw)
    if isinstance(value, float):
        rounded = round(value, 4)
        if rounded == int(rounded):
            return str(int(rounded))
        return f"{rounded:g}"
    return str(value)


def decode_block(
    block: str, words: list[int], map_version: str
) -> dict[str, dict[str, Any]]:
    """Decode a raw block read into ``{code: {raw, value, display}}``."""
    result: dict[str, dict[str, Any]] = {}
    start, _ = get_block_spans(map_version)[block]
    for register in get_registers(map_version):
        if register.block != block:
            continue
        index = register.address - start
        raw = decode_raw(register, words, index)
        result[register.code] = {
            "raw": raw,
            "value": to_physical(register, raw) if raw is not None else None,
            "display": describe_value(register, raw),
        }
    return result
