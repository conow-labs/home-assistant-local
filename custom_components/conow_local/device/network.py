"""Resolve the Modbus TCP peer's MAC address from the host ARP table.

A MAC address only exists on the local layer-2 segment.  After a successful
TCP connection the neighbour entry is warm, so the peer's MAC can be read
from the kernel table without sending anything extra.  When the peer is
routed, the table holds the gateway's address instead of the peer's, and
nothing is returned: showing the router's MAC as the inverter's would be
wrong.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from ..const import (
    CONF_MODBUS_HOST,
    CONF_MODBUS_MODE,
    DOMAIN,
    LOGGER,
    MODBUS_MODE_TCP,
    MODBUS_MODE_TCP_DIRECT,
    MODBUS_TCP_MODES,
)

# The config-entry unique id starts with the connection mode.  The rest used to
# be host/port/slave; those move with a DHCP lease or an adapter swap, so the
# MAC address (when the peer is on the local segment) is the stable part.
_TCP_UNIQUE_PREFIX = {
    MODBUS_MODE_TCP: "modbus_tcp",
    MODBUS_MODE_TCP_DIRECT: "modbus_tcp_direct",
}

# macOS `arp` drops leading zeros ("a8:c:ca:6f:88:97"), so an octet is one or
# two digits; every match is normalised back to the zero-padded form.
_MAC_RE = re.compile(r"\b([0-9a-fA-F]{1,2}(?::[0-9a-fA-F]{1,2}){5})\b")
_UNSET_MACS = {"00:00:00:00:00:00"}


def _normalise(mac: str) -> str:
    """Return a zero-padded lowercase MAC, or "" when it is unusable."""
    if not _MAC_RE.fullmatch(mac):
        return ""
    padded = ":".join(octet.zfill(2) for octet in mac.lower().split(":"))
    return "" if padded in _UNSET_MACS else padded



def _from_proc(host: str) -> str | None:
    """Read Linux's /proc/net/arp, which needs no external command."""
    try:
        lines = Path("/proc/net/arp").read_text(encoding="ascii").splitlines()
    except OSError:
        return None
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 4 or fields[0] != host:
            continue
        mac = _normalise(fields[3])
        if mac:
            return mac
    return None


def _run(command: list[str]) -> str | None:
    """Run a table query, returning stdout only when it succeeded."""
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _mac_in(output: str | None, host: str) -> str | None:
    """Return the MAC mentioned next to ``host`` in a table dump."""
    if not output or host not in output:
        return None
    for match in _MAC_RE.finditer(output):
        mac = _normalise(match.group(1))
        if mac:
            return mac
    return None


def _from_neigh(host: str) -> str | None:
    """Read the neighbour table through iproute2 (Linux)."""
    return _mac_in(_run(["ip", "neigh", "show", host]), host)


def _from_arp(host: str) -> str | None:
    """Read the ARP cache through arp(8) (macOS and many Linux images)."""
    return _mac_in(_run(["arp", "-n", host]), host)


def resolve_mac(host: str) -> str | None:
    """Return the peer's MAC address when it sits on the local segment."""
    for resolver in (_from_proc, _from_neigh, _from_arp):
        mac = resolver(host)
        if mac is not None:
            return mac
    return None


def tcp_unique_id(
    mode: str, mac: str | None, host: str, tcp_port: int, slave: int
) -> str:
    """Return the entry's unique id.

    A known MAC is the device's identity: re-addressing the peer or changing
    the port/slave edits the same entry instead of creating a second one.  The
    old host/port/slave form is only a fallback for peers the host cannot see
    at layer 2, where no MAC can be resolved.
    """
    prefix = _TCP_UNIQUE_PREFIX[mode]
    if mac:
        return f"{prefix}_{mac}"
    return f"{prefix}_{host}_{tcp_port}_{slave}"


def _async_migrate_unique_id(
    hass: HomeAssistant, entry: ConfigEntry, mode: str, mac: str
) -> None:
    """Move an IP-derived entry unique id over to the MAC address."""
    new_id = f"{_TCP_UNIQUE_PREFIX[mode]}_{mac}"
    if entry.unique_id == new_id:
        return
    existing = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, new_id)
    if existing is not None and existing.entry_id != entry.entry_id:
        # Two entries resolve to one MAC (one machine added twice); leave both
        # unique ids alone rather than raising inside setup.
        LOGGER.debug("TCP: unique id %s already belongs to another entry", new_id)
        return
    previous = entry.unique_id
    hass.config_entries.async_update_entry(entry, unique_id=new_id)
    LOGGER.debug("TCP: unique id %s -> %s", previous, new_id)


async def async_register_device_mac(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Adopt the TCP peer's MAC as the entry's identity.

    The MAC becomes the config-entry unique id (so a new address or port edits
    the existing entry) and is stored as a device-registry connection (so Home
    Assistant shows it on the device page).  The call runs after the first
    successful read, which warms the ARP entry; a routed peer or serial entry
    has no MAC and is left as it is.
    """
    mode = entry.data.get(CONF_MODBUS_MODE)
    if mode not in MODBUS_TCP_MODES:
        return
    host = entry.data.get(CONF_MODBUS_HOST)
    if not isinstance(host, str) or not host:
        return

    mac = await hass.async_add_executor_job(resolve_mac, host)
    if mac is None:
        LOGGER.debug("TCP: no ARP entry for %s, MAC not registered", host)
        return

    _async_migrate_unique_id(hass, entry, mode, mac)

    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    if device is None:
        return
    connection = (dr.CONNECTION_NETWORK_MAC, mac)
    if connection in device.connections:
        return
    try:
        registry.async_update_device(device.id, merge_connections={connection})
    except dr.DeviceConnectionCollisionError:
        # Another HA device already claims this MAC (two entries for one unit);
        # leave the registry untouched instead of failing the setup.
        LOGGER.debug("TCP: MAC %s already belongs to another device", mac)
        return
    LOGGER.debug("TCP: registered device MAC %s for %s", mac, host)
