"""Hand a verified probe connection over to the config entry that polls it.

The direct-TCP machine closes the door on every new TCP connection until the
verification code is written again, and it accepts a single client.  Probing
in the config flow and then polling from the coordinator would therefore send
the code twice.  Instead the probe hands its open, already-verified link over
here; the coordinator created moments later adopts it.  Stale entries are
closed when they expire or before a newer probe of the same endpoint replaces
them.
"""

from __future__ import annotations

import threading
import time

from ..client import ConowModbusClient
from ..const import MODBUS_MODE_TCP_DIRECT

_LOCK = threading.Lock()
_TTL_S = 30.0
_pending: dict[tuple[str, str, int, int, str], tuple[float, ConowModbusClient]] = {}

ConnectionKey = tuple[str, str, int, int, str]


def connection_key(
    mode: str,
    host: str,
    tcp_port: int,
    slave: int,
    verify_code: str | None = None,
) -> ConnectionKey:
    """Identify a TCP endpoint exactly as the entry will describe it."""
    code = ""
    if mode == MODBUS_MODE_TCP_DIRECT:
        # The device treats the hex code case-insensitively.
        code = str(verify_code or "").strip().lower()
    return (mode, host, int(tcp_port), int(slave), code)


def stash(key: ConnectionKey, client: ConowModbusClient) -> None:
    """Park a verified client for the entry setup that follows immediately."""
    now = time.monotonic()
    with _LOCK:
        _purge_expired(now)
        previous = _pending.pop(key, None)
        _pending[key] = (now, client)
    _close(previous)


def take(key: ConnectionKey) -> ConowModbusClient | None:
    """Return the parked client when it is still fresh and open."""
    now = time.monotonic()
    with _LOCK:
        _purge_expired(now)
        item = _pending.pop(key, None)
    if item is None:
        return None
    stamp, client = item
    if now - stamp > _TTL_S or not client.connected:
        _close(client)
        return None
    return client


def _purge_expired(now: float) -> None:
    """Close entries whose setup never came (caller holds the lock)."""
    for key in [k for k, (stamp, _) in _pending.items() if now - stamp > _TTL_S]:
        _close(_pending.pop(key))


def _close(item: tuple[float, ConowModbusClient] | None) -> None:
    """Close a parked client, ignoring failures during teardown."""
    if item is None:
        return
    try:
        item[1].close()
    except Exception:  # noqa: BLE001 - teardown must not raise
        pass
