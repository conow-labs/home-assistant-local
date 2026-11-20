"""Register-map registry: map ids, files and firmware routing.

This module is the only place that knows which JSON file backs which map
version.  Every other module asks it for the path/source, so a future map
only changes this file.

``registers.json`` (map version 1, the July protocol) is the default.
``panel_registers.json`` (map version 2, the finalized protocol) is used
whenever the firmware register at ``0x274E-0x274F`` (10062-10063)
answers, whatever value it returns (current machines reply ``0x0000``).
Only a failed probe — timeout, no reply or a Modbus exception — falls
back to the v1 map, never to the newer addresses.

The module deliberately imports stdlib only: ``tools/i18n/build_panel_i18n.py``
imports it outside Home Assistant.
"""

from __future__ import annotations

import re
from pathlib import Path

MAP_V1 = "v1"
MAP_V2 = "v2"

_MAPS_DIR = Path(__file__).resolve().parent
MAP_PATHS: dict[str, Path] = {
    MAP_V1: _MAPS_DIR / "registers.json",
    MAP_V2: _MAPS_DIR / "panel_registers.json",
}
MAP_SOURCES: dict[str, str] = {key: path.name for key, path in MAP_PATHS.items()}

FIRMWARE_VERSION_ADDRESS = 10062  # 0x274E, two 16-bit registers, 4-byte ASCII
FIRMWARE_VERSION_REGISTERS = 2

# A register both maps implement; used as the connectivity probe so the
# config flow works before the map (and its firmware) is known.
CONNECTION_PROBE = (10000, 1)

# Informational only: the panel shows this as the version that introduced the
# finalized map.  Map selection itself depends on the probe succeeding, not on
# the decoded version.
PANEL_MAP_MIN_FIRMWARE = (1, 2)

_VERSION_TEXT = re.compile(r"^[Vv]?(\d{1,2}(?:\.\d{1,2}){0,3}|\d{3,4})$")


def map_path(map_version: str) -> Path:
    """Return the JSON file backing a map version."""
    return MAP_PATHS[map_version]


def map_source(map_version: str) -> str:
    """Return the file name shown in logs and in the panel."""
    return MAP_SOURCES[map_version]


def parse_firmware_version(words: list[int] | tuple[int, ...]) -> tuple[int, ...] | None:
    """Decode a 4-byte ASCII firmware version into comparable components.

    Accepted forms include ``1.2``, ``V1.02``, ``1.2.3`` and compact
    ``0102`` (v1.2).  Anything that does not look like a version returns
    ``None`` so the caller keeps the v1 default.
    """
    if len(words) < FIRMWARE_VERSION_REGISTERS:
        return None
    data = b"".join((int(word) & 0xFFFF).to_bytes(2, "big") for word in words[:2])
    text = data.split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()
    if text:
        match = _VERSION_TEXT.fullmatch(text)
        if match is not None:
            value = match.group(1)
            if "." in value:
                return tuple(int(part) for part in value.split("."))
            if len(value) == 4:
                return (int(value[:2]), int(value[2:]))
            if len(value) == 3:
                return (int(value[0]), int(value[1:]))
            return (int(value),)

    # Some firmware revisions encode the version numerically as 0xMMmm
    # (e.g. 0x0102 for v1.2).  Only accept a plausible major.minor pair.
    raw = int(words[0]) & 0xFFFF
    major, minor = (raw >> 8) & 0xFF, raw & 0xFF
    if int(words[1]) == 0 and 1 <= major <= 9 and minor <= 99:
        return (major, minor)
    return None


def select_map(probe_ok: bool) -> str:
    """Return the map id selected by the firmware probe.

    Any successful response from the firmware register selects the v2 map;
    only a failed probe falls back to v1.  The value itself is used for
    display only.
    """
    return MAP_V2 if probe_ok else MAP_V1


def format_version(version: tuple[int, ...] | None) -> str | None:
    """Render a version tuple for logs and the panel."""
    return ".".join(str(part) for part in version) if version else None
