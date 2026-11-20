"""Build the read model for the Conow Local grouping panel.

The panel consumes the same unified map model and entity specs as the HA
device page.  Loaded entries read through the main coordinator; entries that
are not loaded may be inspected over a short-lived TCP connection (never a
second serial handle).
"""

from __future__ import annotations

import time
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from ..maps import model as map_model
from ..client import (
    CONOW_EXCEPTION_DEVICE_BUSY,
    CONOW_EXCEPTION_EXTERNAL_CONTROL,
    CONOW_EXCEPTION_VERIFICATION_REQUIRED,
    ConowExceptionResponseError,
    ConowModbusClient,
    ConowModbusError,
)
from ..const import (
    CONF_LAST_MAP_VERSION,
    CONF_MODBUS_HOST,
    CONF_MODBUS_MODE,
    CONF_MODBUS_SLAVE,
    CONF_MODBUS_TCP_PORT,
    DEFAULT_TCP_PORT,
    DOMAIN,
    LOGGER,
    MODBUS_MODE_RTU,
    MODBUS_TCP_MODES,
)
from ..device.coordinator import (
    PANEL_POLL_INTERVAL_S,
    ConowLocalCoordinator,
    configured_poll_interval,
    decode_required_blocks,
    read_map_blocks,
    write_register_ops,
)
from ..maps.entity_model import panel_code_map
from ..maps.registry import (
    FIRMWARE_VERSION_ADDRESS,
    FIRMWARE_VERSION_REGISTERS,
    MAP_PATHS,
    MAP_V1,
    PANEL_MAP_MIN_FIRMWARE,
    format_version,
    map_source,
    parse_firmware_version,
    select_map,
)


def _control_kind(register: map_model.PanelRegister) -> str:
    """Return the editor type the panel should render for this register."""
    if register.is_time:
        return "time"
    if register.boolean:
        return "switch"
    if register.values:
        return "enum"
    if register.dtype == "string":
        return "text"
    return "number"


def _enum_raw(register: map_model.PanelRegister, value: Any) -> int | None:
    """Resolve a submitted enum value (raw number or translated label)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    for raw, label in (register.values or {}).items():
        if label == value:
            return raw
    return None


def _device_name(entry, device_entry) -> str:
    return (
        device_entry.name_by_user
        or device_entry.name
        or entry.title
        or entry.entry_id
    )


def _poll_interval(entry, coordinator: ConowLocalCoordinator | None) -> int:
    """Return the interval the coordinator polls at, or what its next setup uses."""
    if coordinator is not None:
        return coordinator.poll_interval_seconds
    return configured_poll_interval(entry) or PANEL_POLL_INTERVAL_S


# finalized-map codes that back a differently named v1 entity. Clicking the
# panel row opens the entity's more-info dialog, so the alias only covers
# registers whose meaning is identical across both maps.
ENTITY_CODE_ALIASES = {
    "ac_charge_power_limit": "grid_charge_power_limit",
    "ac_discharge_power_limit": "battery_discharge_power_limit",
    "charge_discharge_cutoff_soc": "battery_cutoff_soc",
    "system_soc": "battery_soc",
    "device_fault_code": "fault_code",
    "bypass_power": "backup_load_power",
}


def _entity_code_map(
    hass: HomeAssistant,
    entry_id: str,
    device_entry,
    map_version: str,
    new_model: bool,
) -> dict[str, str]:
    """Map register/entity codes to the entity_id backing them on this device."""
    registry = er.async_get(hass)
    if device_entry is not None:
        entries = er.async_entries_for_device(registry, device_entry.id)
    else:
        entries = er.async_entries_for_config_entry(registry, entry_id)
    unique_prefix = f"{entry_id}_"
    by_unique = {
        (item.unique_id or "")[len(unique_prefix) :]: item.entity_id
        for item in entries
        if (item.unique_id or "").startswith(unique_prefix)
    }
    mapping: dict[str, str] = {}
    for code, unique_code in panel_code_map(map_version, new_model).items():
        entity_id = by_unique.get(unique_code)
        if entity_id is not None:
            mapping[code] = entity_id
    return mapping


def _entity_id_for(register: map_model.PanelRegister, mapping: dict[str, str]) -> str | None:
    """Return the entity_id for a panel register, if one exists."""
    if register.code in mapping:
        return mapping[register.code]
    alias = ENTITY_CODE_ALIASES.get(register.code)
    return mapping.get(alias) if alias else None


def _serialize_group(
    group: map_model.PanelGroup,
    decoded: dict[str, dict[str, Any]] | None = None,
    entities: dict[str, str] | None = None,
    *,
    map_version: str,
    new_model: bool = True,
) -> dict[str, Any]:
    decoded = decoded or {}
    entities = entities or {}
    index = map_model.get_register_index(map_version)
    members: list[dict[str, Any]] = []
    for code in group.members:
        register = index[code]
        if not map_model.register_available(register, new_model):
            continue
        value = decoded.get(code, {})
        if register.bits:
            # The register is a bitmask; expose the individual bits as
            # read-only boolean rows instead of the raw number.
            raw = value.get("raw")
            known = isinstance(raw, int)
            for bit in register.bits:
                is_on = known and bool(raw & (1 << bit.bit))
                members.append(
                    {
                        "code": bit.code,
                        "name": bit.name,
                        "address": register.address,
                        "address_hex": register.address_hex,
                        "dtype": register.dtype,
                        "length": 1,
                        "writable": False,
                        "unit": "",
                        "scale": 1,
                        "values": None,
                        "note": "",
                        "control": "bit",
                        "device_class": bit.device_class,
                        "bounds": None,
                        "raw": (1 if is_on else 0) if known else None,
                        "value": is_on if known else None,
                        "display": ("1" if is_on else "0") if known else "",
                        "entity_id": entities.get(bit.code),
                    }
                )
            continue
        members.append(
            {
                "code": register.code,
                "name": register.name,
                "address": register.address,
                "address_hex": register.address_hex,
                "dtype": register.dtype,
                "length": register.length,
                "writable": register.writable,
                "unit": register.unit,
                "scale": register.scale,
                "values": register.values,
                "note": register.note,
                "control": _control_kind(register),
                "enabled_when": (
                    {
                        "code": register.enabled_when[0],
                        "values": list(register.enabled_when[1]),
                    }
                    if register.enabled_when
                    else None
                ),
                "bounds": map_model.numeric_bounds(register, decoded),
                # Limits without live narrowing: the panel rebases dynamic
                # ranges (cutoff SoC, TOU SoC) on these when the user drafts a
                # different direction than the one the device currently holds.
                "static_bounds": map_model.numeric_bounds(register),
                "raw": value.get("raw"),
                "value": value.get("value"),
                "display": value.get("display", ""),
                "entity_id": _entity_id_for(register, entities),
            }
        )
    return {
        "id": group.id,
        "label": group.label,
        "icon": group.icon,
        "order": group.order,
        "atomic": group.atomic,
        "span": {
            "start": group.span_start,
            "end": group.span_end,
            "start_hex": f"0x{group.span_start:04X}",
            "end_hex": f"0x{group.span_end:04X}",
            "registers": group.span_registers,
        },
        "note": group.note,
        "count_register": group.count_register or None,
        "members": members,
        "subgroups": [
            {
                "label": subgroup.label,
                "key": subgroup.key or None,
                "members": [
                    code
                    for code in subgroup.members
                    if map_model.register_available(index[code], new_model)
                ],
            }
            for subgroup in group.subgroups
            if any(
                map_model.register_available(index[code], new_model)
                for code in subgroup.members
            )
        ],
    }


def build_panel_map(map_version: str | None = None) -> dict[str, Any]:
    """Return the static grouped map of one map version (no device values).

    Without a known map version the result is empty: the frontend requests the
    map again once the device state tells it whether this is v1 or v2, so it
    never flashes the wrong map's groups.
    """
    if map_version not in MAP_PATHS:
        return {"map": {}, "groups": {}}
    return {
        "map": map_model.get_map_meta(map_version),
        "groups": {
            group.id: _serialize_group(group, map_version=map_version)
            for group in map_model.get_groups(map_version)
        },
    }


def get_panel_devices(hass: HomeAssistant) -> list[dict[str, Any]]:
    """List config entries that can be inspected through the grouping panel."""
    device_registry = dr.async_get(hass)
    devices: list[dict[str, Any]] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        device_entry = device_registry.async_get_device(
            identifiers={(DOMAIN, entry.entry_id)}
        )
        coordinator = getattr(entry, "runtime_data", None)
        loaded = entry.state is ConfigEntryState.LOADED
        devices.append(
            {
                "device_id": device_entry.id if device_entry else entry.entry_id,
                "entry_id": entry.entry_id,
                "name": _device_name(entry, device_entry) if device_entry else entry.title,
                "online": bool(
                    loaded
                    and coordinator is not None
                    and coordinator.last_update_success
                ),
                "loaded": loaded,
                "mode": entry.data.get(CONF_MODBUS_MODE, "rtu"),
                "slave": entry.data.get(CONF_MODBUS_SLAVE),
                "poll_interval": _poll_interval(entry, coordinator),
            }
        )
    devices.sort(key=lambda item: item["name"].lower())
    return devices


def entry_for_device(hass: HomeAssistant, device_id: str):
    """Resolve a panel ``device_id`` (HA device id or entry id) to an entry."""
    device_registry = dr.async_get(hass)
    device_entry = device_registry.async_get(device_id)
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == device_id:
            return entry
        if device_entry and (DOMAIN, entry.entry_id) in device_entry.identifiers:
            return entry
    return None


def _probe_map_version(
    client: ConowModbusClient,
) -> tuple[str, tuple[int, ...] | None]:
    """Probe firmware and return the selected map plus decoded version.

    Any reply from the firmware register selects v2, including current
    machines that answer 0x0000.  A single-word read is retried because some
    firmware exposes only 0x274E.
    """
    words: list[int] | None = None
    for count in (FIRMWARE_VERSION_REGISTERS, 1):
        try:
            words = client.read_holding_registers(
                FIRMWARE_VERSION_ADDRESS,
                count,
                retries=2,
            )
        except ConowModbusError:
            continue
        break
    if words is None:
        return MAP_V1, None
    return select_map(True), parse_firmware_version(words)


MAX_WRITE_REGISTERS = 123  # FC 0x10 quantity limit


def _stored_map_version(entry) -> str:
    """Map this entry last read successfully (v1 when nothing is stored).

    The device answers the firmware probe with v2 or not at all; while it is
    unreachable the panel keeps the last confirmed structure instead of
    dropping to v1, which has no schedule groups.
    """
    remembered = entry.options.get(CONF_LAST_MAP_VERSION)
    return remembered if remembered in MAP_PATHS else MAP_V1


def _remember_map_version(hass: HomeAssistant, entry, map_version: str) -> None:
    """Store the map a panel read just confirmed."""
    if map_version not in MAP_PATHS:
        return
    if entry.options.get(CONF_LAST_MAP_VERSION) == map_version:
        return
    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, CONF_LAST_MAP_VERSION: map_version},
    )


def _merge_contiguous(
    ops: list[tuple[int, list[int]]],
) -> list[tuple[int, list[int]]]:
    """Merge neighbouring per-register writes into FC 0x10 frames.

    A group can contain a read-only register in the middle — ``work_strategy``
    has ``allow_battery_export`` between two writable runs — so merging only
    when *every* address touches would degrade such a group to one frame per
    register.  Merge each contiguous run instead, starting a new frame when
    the addresses jump or the FC 0x10 limit is reached.
    """
    merged: list[tuple[int, list[int]]] = []
    for address, chunk in ops:
        if merged:
            start, words = merged[-1]
            if (
                address == start + len(words)
                and len(words) + len(chunk) <= MAX_WRITE_REGISTERS
            ):
                merged[-1] = (start, words + chunk)
                continue
        merged.append((address, list(chunk)))
    return merged


def _active_members(
    group: map_model.PanelGroup,
    values: dict[str, Any],
    index: dict[str, map_model.PanelRegister],
) -> set[str]:
    """Return the members that belong to the submitted slot count.

    Plan-table groups carry a count register followed by fixed-size slots.
    The device evaluates only the slots below the count, and checks the frame
    against it, so a schedule with one strategy must not drag the unused
    strategies along.
    """
    if not group.count_register or not group.subgroups:
        return set(group.members)
    count_register = index.get(group.count_register)
    if count_register is None:
        return set(group.members)
    raw = _enum_raw(count_register, values.get(group.count_register))
    if raw is None:
        return set(group.members)
    count = max(0, min(raw, len(group.subgroups)))
    active = {group.count_register}
    for subgroup in group.subgroups[:count]:
        active.update(subgroup.members)
    return active


def _mode_allows(
    register: map_model.PanelRegister,
    values: dict[str, Any],
    index: dict[str, map_model.PanelRegister],
) -> bool:
    """Return whether a mode-dependent register applies to this submission.

    A TOU slot carries both a target SoC and a discharge power, but only the
    one matching the slot's mode is meaningful: 0 = charge (target SoC),
    1 = discharge (power).
    """
    dependency = register.enabled_when
    if dependency is None:
        return True
    code, allowed = dependency
    source = index.get(code)
    if source is None:
        return True
    raw = _enum_raw(source, values.get(code))
    return raw is not None and raw in allowed


def _keeps_live_value(
    register: map_model.PanelRegister,
    value: Any,
    live: dict[str, dict[str, Any]] | None,
) -> bool:
    """Return whether the submission simply repeats the device's current value.

    Dynamic limits (TOU target SoC above the current SoC, discharge power
    within what the battery allows) also apply to values the device already
    holds.  A schedule written earlier may sit outside today's limit; editing
    another field of the same group must not be blocked by it, since the
    register is written unchanged.
    """
    held = ((live or {}).get(register.code) or {}).get("value")
    if isinstance(held, bool) or not isinstance(held, (int, float)):
        return False
    try:
        return abs(float(value) - float(held)) < 1e-9
    except (TypeError, ValueError):
        return False


def _time_minutes(value: Any) -> int | None:
    """Return an ``HH:MM`` submission as minutes since midnight, else None."""
    parts = str(value).strip().split(":")
    if len(parts) < 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _validate_slot_times(
    group: map_model.PanelGroup,
    values: dict[str, Any],
    index: dict[str, map_model.PanelRegister],
    active: set[str],
) -> None:
    """Reject active slots that are reversed or cross each other.

    A plan table may leave gaps between slots and need not list them in clock
    order, but every slot must start before it ends and no two active slots
    may overlap.  Only the slots covered by the submitted count are checked;
    the ones past it are not written anyway.
    """
    if not group.subgroups:
        return
    intervals: list[tuple[int, int, str, str]] = []
    for subgroup in group.subgroups:
        times = [
            index[code]
            for code in subgroup.members
            if code in active and code in index and index[code].is_time
        ]
        starts = [register for register in times if register.code.endswith("_start")]
        ends = [register for register in times if register.code.endswith("_end")]
        if not starts or not ends:
            continue
        start, end = starts[0], ends[0]
        start_minutes = _time_minutes(values.get(start.code))
        end_minutes = _time_minutes(values.get(end.code))
        if start_minutes is None or end_minutes is None:
            # Missing or malformed times are rejected by encode_value later.
            continue
        if start_minutes >= end_minutes:
            raise ValueError(
                f"{group.id}: {start.code} ({values[start.code]}) must be "
                f"earlier than {end.code} ({values[end.code]})"
            )
        intervals.append((start_minutes, end_minutes, start.code, end.code))
    intervals.sort()
    for previous, current in zip(intervals, intervals[1:]):
        if current[0] < previous[1]:
            raise ValueError(
                f"{group.id}: {current[2]} starts before {previous[3]} ends"
            )


def plan_group_writes(
    group: map_model.PanelGroup,
    values: dict[str, Any],
    live: dict[str, dict[str, Any]] | None = None,
    *,
    map_version: str,
    new_model: bool = True,
) -> list[tuple[int, list[int]]]:
    """Validate a group submission and return ``(address, words)`` writes.

    Consecutive writable registers are sent as one FC 0x10 frame per
    contiguous run; only isolated registers need their own frame.  ``live``
    holds the decoded device state so limits that depend on another register
    (safety SoC, hardware power capability) can be enforced before anything
    is sent.  New-model-only registers are skipped on an old unit: the
    submission then simply has nothing to write for them.  Plan-table groups
    only write the slots covered by the submitted count.
    """
    index = map_model.get_register_index(map_version)
    active = _active_members(group, values, index)
    registers = [
        index[code]
        for code in group.members
        if code in active
        and index[code].writable
        and map_model.register_available(index[code], new_model)
    ]
    if not registers:
        raise ValueError(f"Group {group.id} has no writable registers")
    missing = [register.code for register in registers if register.code not in values]
    if missing:
        raise ValueError("Missing value for " + ", ".join(missing))
    if live is not None:
        # The cutoff SoC limits depend on the direction being written in this
        # same group, so validate against the submitted value, not the stale
        # reading.
        direction = index.get("charge_discharge_direction")
        submitted = values.get("charge_discharge_direction")
        if direction is not None and submitted is not None:
            raw = _enum_raw(direction, submitted)
            if raw is not None:
                live = dict(live)
                live["charge_discharge_direction"] = {"value": float(raw)}
    _validate_slot_times(group, values, index, active)
    ops: list[tuple[int, list[int]]] = []
    for register in registers:
        value = values[register.code]
        applies = _mode_allows(register, values, index)
        if not applies:
            # Do not change the field the slot's mode does not use: keep the
            # value the device already holds so the whole schedule still goes
            # out as one contiguous FC 0x10 frame.  Its value is not validated:
            # the device may hold a stale 0 there.
            held = ((live or {}).get(register.code) or {}).get("value")
            if held is not None:
                value = held
        bounds = map_model.numeric_bounds(register, live)
        if (
            applies
            and bounds is not None
            and not register.values
            and not register.is_time
            and not _keeps_live_value(register, value, live)
        ):
            try:
                physical = float(value)
            except (TypeError, ValueError):
                physical = None
            if physical is not None:
                low, high, _step = bounds
                if not low <= physical <= high:
                    raise ValueError(
                        f"{register.code}: {physical:g} is outside the allowed "
                        f"range {low:g}–{high:g}"
                    )
        ops.append((register.address, map_model.encode_value(register, value)))
    return _merge_contiguous(ops)


def _short_lived_client(entry) -> ConowModbusClient:
    """Build a TCP client for an entry the coordinator does not own.

    The challenge code is never written here: only the config flow sends it.
    """
    return ConowModbusClient(
        host=entry.data[CONF_MODBUS_HOST],
        tcp_port=entry.data.get(CONF_MODBUS_TCP_PORT, DEFAULT_TCP_PORT),
        slave=entry.data[CONF_MODBUS_SLAVE],
    )


def _write_ops_direct(entry, ops: list[tuple[int, list[int]]]) -> None:
    """Write through a short-lived TCP client when the entry is not loaded."""
    if entry.data.get(CONF_MODBUS_MODE) not in MODBUS_TCP_MODES:
        raise ConowModbusError("RTU entry must finish setup before writing")
    with _short_lived_client(entry) as client:
        write_register_ops(client, ops)


async def async_write_panel_group(
    hass: HomeAssistant,
    device_id: str,
    group_id: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Write one group atomically and return the refreshed panel state."""
    entry = entry_for_device(hass, device_id)
    if entry is None:
        raise LookupError(f"No {DOMAIN} entry for {device_id}")

    coordinator: ConowLocalCoordinator | None = getattr(entry, "runtime_data", None)
    loaded = entry.state is ConfigEntryState.LOADED and coordinator is not None
    live: dict[str, dict[str, Any]] = {}
    if loaded:
        map_version = coordinator.map_version
        live = dict(coordinator.data or {})
    else:
        try:
            map_version, _firmware, live = await hass.async_add_executor_job(
                _read_blocks_direct, entry
            )
        except (ConowModbusError, OSError):
            map_version = _stored_map_version(entry)
            live = {}

    group = map_model.get_group(group_id, map_version)
    if group is None:
        raise LookupError(f"Unknown group {group_id}")
    new_model = map_model.values_new_model(live)
    ops = plan_group_writes(
        group, values, live, map_version=map_version, new_model=new_model
    )

    if loaded:
        await coordinator.async_write_panel_ops(ops)
    else:
        await hass.async_add_executor_job(_write_ops_direct, entry, ops)

    LOGGER.info(
        "Panel: wrote group %s (%s register frames) to %s",
        group_id,
        len(ops),
        entry.entry_id,
    )
    return await async_build_panel_state(hass, device_id)


def _read_blocks_direct(entry) -> tuple[str, tuple[int, ...] | None, dict[str, dict[str, Any]]]:
    """Open a short-lived TCP client for entries the coordinator does not own."""
    if entry.data.get(CONF_MODBUS_MODE) not in MODBUS_TCP_MODES:
        # Never open a second handle on the serial port.
        return MAP_V1, None, {}
    with _short_lived_client(entry) as client:
        map_version, version = _probe_map_version(client)
        blocks = read_map_blocks(client, map_version)
        return map_version, version, decode_required_blocks(blocks, map_version)


def _read_error_code(err: Exception, entry) -> str | None:
    """Name the link-level cause of a failed panel read, if it has one."""
    if isinstance(err, ConowExceptionResponseError):
        if err.exception_code == CONOW_EXCEPTION_DEVICE_BUSY:
            return "device_busy"
        if err.exception_code == CONOW_EXCEPTION_VERIFICATION_REQUIRED:
            return "verification_required"
        if (
            err.exception_code == CONOW_EXCEPTION_EXTERNAL_CONTROL
            and entry.data.get(CONF_MODBUS_MODE) == MODBUS_MODE_RTU
        ):
            # Code 6 means the RS-485 external-control switch is off, which
            # only applies to an RTU entry; TCP keeps the generic hint.
            return "external_control_disabled"
    return None


async def async_build_panel_state(hass: HomeAssistant, device_id: str) -> dict[str, Any]:
    """Read the selected grouped map and serialize the grouped values."""
    device_registry = dr.async_get(hass)
    entry = entry_for_device(hass, device_id)
    if entry is None:
        raise LookupError(f"No {DOMAIN} entry for {device_id}")
    device_entry = device_registry.async_get_device(
        identifiers={(DOMAIN, entry.entry_id)}
    )

    coordinator: ConowLocalCoordinator | None = getattr(entry, "runtime_data", None)
    loaded = entry.state is ConfigEntryState.LOADED and coordinator is not None
    read_ok = False
    read_error: str | None = None
    if loaded:
        map_version = coordinator.map_version
        firmware = coordinator.firmware_version
        try:
            decoded = await coordinator.async_read_snapshot()
            read_ok = bool(decoded)
        except (ConowModbusError, OSError) as err:
            # Never fall back to the previous poll: the panel shows "—" for a
            # device that cannot be read right now.
            LOGGER.debug("Panel: fresh read failed for %s: %s", entry.entry_id, err)
            decoded = {}
            read_error = _read_error_code(err, entry)
        if read_ok:
            _remember_map_version(hass, entry, map_version)
    else:
        try:
            map_version, firmware, decoded = await hass.async_add_executor_job(
                _read_blocks_direct, entry
            )
            read_ok = bool(decoded)
            if read_ok:
                _remember_map_version(hass, entry, map_version)
        except (ConowModbusError, OSError) as err:
            LOGGER.debug("Panel: direct read failed for %s: %s", entry.entry_id, err)
            map_version = _stored_map_version(entry)
            firmware, decoded = None, {}
            read_error = _read_error_code(err, entry)

    new_model = map_model.values_new_model(decoded)
    entities = _entity_code_map(
        hass, entry.entry_id, device_entry, map_version, new_model
    )
    LOGGER.debug(
        "Panel: read %s codes for %s (map=%s, firmware=%s)",
        len(decoded),
        entry.entry_id,
        map_version,
        format_version(firmware) or "unknown",
    )
    map_info = dict(map_model.get_map_meta(map_version))
    map_info.update(
        {
            "selected": map_version,
            "source": map_source(map_version),
            "firmware_version": format_version(firmware),
            "min_firmware": format_version(PANEL_MAP_MIN_FIRMWARE),
        }
    )
    return {
        "device_id": device_id,
        "name": _device_name(entry, device_entry) if device_entry else entry.title,
        # Reachability is the fresh read, not the cached firmware version: a
        # loaded entry whose device stopped answering must not look online.
        "online": read_ok,
        "map_readable": read_ok,
        # Link-level refusal (4 = another client, 5 = stale verification
        # code, 6 = RTU external control off) so the panel can name the cause
        # instead of a generic hint.
        "read_error": read_error,
        "map_version": 2 if map_version != MAP_V1 else 1,
        "map_source": map_info["source"],
        "firmware_version": map_info["firmware_version"],
        "min_firmware": map_info["min_firmware"],
        "mode": entry.data.get(CONF_MODBUS_MODE, "rtu"),
        "slave": entry.data.get(CONF_MODBUS_SLAVE),
        "poll_interval": _poll_interval(entry, coordinator if loaded else None),
        "map": map_info,
        "groups": {
            group.id: _serialize_group(
                group,
                decoded,
                entities,
                map_version=map_version,
                new_model=new_model,
            )
            for group in map_model.get_groups_for_model(map_version, new_model)
        },
    }
