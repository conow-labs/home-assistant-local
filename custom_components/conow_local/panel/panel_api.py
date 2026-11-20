"""WebSocket API and custom panel for the Conow Local grouping view."""

from __future__ import annotations

import hashlib
from pathlib import Path

import voluptuous as vol

from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.frontend import (
    add_extra_js_url,
    async_panel_exists,
    remove_extra_js_url,
)
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback

from ..maps import model as map_model
from ..client import (
    CONOW_EXCEPTION_DEVICE_BUSY,
    CONOW_EXCEPTION_EXTERNAL_CONTROL,
    CONOW_EXCEPTION_VERIFICATION_REQUIRED,
    ConowExceptionResponseError,
    ConowModbusError,
)
from ..const import (
    CONF_MODBUS_MODE,
    CONF_POLL_INTERVAL,
    DOMAIN,
    LOGGER,
    MODBUS_MODE_RTU,
    PANEL_URL_PATH,
    POLL_INTERVAL_OPTIONS,
)
from ..maps.registry import MAP_PATHS
from .panel_functions import (
    async_build_panel_state,
    async_write_panel_group,
    build_panel_map,
    entry_for_device,
    get_panel_devices,
)

URL_BASE = "/conow_local_panel_static"
PANEL_WEBCOMPONENT = "conow-local-panel"
_FRONTEND_DIR = Path(__file__).parent / "frontend"


def _refusal_code(err: ConowExceptionResponseError, entry) -> str:
    """Pick the panel error code that explains a refused write.

    The machine's private codes 4 and 5 mean "another client is connected"
    and "the verification code is stale"; on an RTU entry 6 also means the
    external-control (Modbus RTU) switch is off in the app.  The panel
    translates each of those instead of showing a generic rejection.
    """
    if err.exception_code == CONOW_EXCEPTION_DEVICE_BUSY:
        return "device_busy"
    if err.exception_code == CONOW_EXCEPTION_VERIFICATION_REQUIRED:
        return "verification_required"
    if (
        err.exception_code == CONOW_EXCEPTION_EXTERNAL_CONTROL
        and entry is not None
        and entry.data.get(CONF_MODBUS_MODE) == MODBUS_MODE_RTU
    ):
        return "external_control_disabled"
    return "write_rejected"


def _static_version() -> str:
    """Return a content hash so a changed asset always reloads in browsers."""
    digest = hashlib.sha256()
    assets = [
        _FRONTEND_DIR / "conow-local-panel.js",
        _FRONTEND_DIR / "conow-local-notify.js",
        *sorted((_FRONTEND_DIR / "i18n").glob("*.json")),
    ]
    for path in assets:
        try:
            digest.update(path.read_bytes())
        except OSError:
            LOGGER.debug("Panel: cannot hash %s", path)
    return digest.hexdigest()[:8]


PANEL_STATIC_VERSION = _static_version()
PANEL_SCRIPT_URL = f"{URL_BASE}/conow-local-panel.js?v={PANEL_STATIC_VERSION}"
NOTIFY_SCRIPT_URL = f"{URL_BASE}/conow-local-notify.js?v={PANEL_STATIC_VERSION}"
PANEL_SIDEBAR_ENABLED = True
SIDEBAR_TITLES = {
    "de": "Conow Local Gruppen",
    "nl": "Conow Local groepen",
    "zh-Hans": "Conow Local 分组",
}


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/get_panel_devices"}
)
@websocket_api.async_response
async def websocket_get_panel_devices(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Return Conow Local devices available for the grouping panel."""
    connection.send_result(msg["id"], {"devices": get_panel_devices(hass)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_panel_map",
        vol.Optional("map_version"): vol.In(list(MAP_PATHS)),
    }
)
@websocket_api.async_response
async def websocket_get_panel_map(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Return the grouped map (v1 or v2) without device values."""
    result = await hass.async_add_executor_job(
        build_panel_map, msg.get("map_version")
    )
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_panel_functions",
        vol.Required("device_id"): str,
    }
)
@websocket_api.async_response
async def websocket_get_panel_functions(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Return the grouped finalized-map read model for one device."""
    try:
        state = await async_build_panel_state(hass, msg["device_id"])
    except LookupError:
        connection.send_error(msg["id"], "not_found", "Device not found")
        return
    connection.send_result(msg["id"], state)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_panel_group",
        vol.Required("device_id"): str,
        vol.Required("group_id"): str,
        vol.Required("values"): {str: vol.Any(int, float, str)},
    }
)
@websocket_api.async_response
async def websocket_set_panel_group(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Write every writable register of a group in one request."""
    try:
        state = await async_write_panel_group(
            hass, msg["device_id"], msg["group_id"], msg["values"]
        )
    except LookupError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_value", str(err))
        return
    except ConowExceptionResponseError as err:
        # The device answered and refused the group; the link stays usable.
        connection.send_error(
            msg["id"],
            _refusal_code(err, entry_for_device(hass, msg["device_id"])),
            str(err),
        )
        return
    except (ConowModbusError, OSError) as err:
        connection.send_error(msg["id"], "write_failed", str(err))
        return
    state["source"] = "local"
    connection.send_result(msg["id"], state)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_poll_interval",
        vol.Required("device_id"): str,
        vol.Required("seconds"): vol.All(
            vol.Coerce(int), vol.In(POLL_INTERVAL_OPTIONS)
        ),
    }
)
@websocket_api.async_response
async def websocket_set_poll_interval(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Store one device's polling interval and apply it without a reload."""
    entry = entry_for_device(hass, msg["device_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Device not found")
        return
    seconds = msg["seconds"]
    # Options survive a restart; the entry data stays untouched.
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_POLL_INTERVAL: seconds}
    )
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is not None:
        await coordinator.async_set_poll_interval(seconds)
    LOGGER.info("Panel: poll interval for %s set to %ss", entry.entry_id, seconds)
    connection.send_result(msg["id"], {"seconds": seconds})


@callback
def _register_websocket_api(hass: HomeAssistant) -> None:
    if hass.data.get(f"{DOMAIN}_panel_ws_registered"):
        return
    websocket_api.async_register_command(hass, websocket_get_panel_devices)
    websocket_api.async_register_command(hass, websocket_get_panel_map)
    websocket_api.async_register_command(hass, websocket_get_panel_functions)
    websocket_api.async_register_command(hass, websocket_set_panel_group)
    websocket_api.async_register_command(hass, websocket_set_poll_interval)
    hass.data[f"{DOMAIN}_panel_ws_registered"] = True


async def async_register_local_panel(hass: HomeAssistant) -> None:
    """Register the grouping panel, its static assets and websocket API."""
    # Parse and validate the maps off the event loop so WS calls stay cheap.
    try:
        await hass.async_add_executor_job(map_model.preload)
    except (OSError, ValueError, KeyError) as err:
        LOGGER.error("Panel: cannot load the grouped register maps: %s", err)
    _register_websocket_api(hass)

    frontend_dir = _FRONTEND_DIR
    if not hass.data.get(f"{DOMAIN}_panel_static_registered"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, str(frontend_dir), cache_headers=False)]
        )
        hass.data[f"{DOMAIN}_panel_static_registered"] = True

    # Adds the "Open panel" action to the device-page write-guard toast.
    previous_js = hass.data.get(f"{DOMAIN}_notify_js")
    if previous_js != NOTIFY_SCRIPT_URL:
        if previous_js:
            remove_extra_js_url(hass, previous_js)
        add_extra_js_url(hass, NOTIFY_SCRIPT_URL)
        hass.data[f"{DOMAIN}_notify_js"] = NOTIFY_SCRIPT_URL

    if hass.data.get(f"{DOMAIN}_panel_registered"):
        return

    if PANEL_SIDEBAR_ENABLED and not async_panel_exists(hass, PANEL_URL_PATH):
        language = str(hass.config.language or "")
        sidebar_title = (
            SIDEBAR_TITLES.get(language)
            or SIDEBAR_TITLES.get(language.split("-")[0])
            or "Conow Local"
        )
        # No config_panel_domain: a registered config panel would take over the
        # gear icon on every config entry, hiding the options flow that updates
        # the direct-TCP verification code.  The panel stays in the sidebar.
        await panel_custom.async_register_panel(
            hass=hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name=PANEL_WEBCOMPONENT,
            module_url=PANEL_SCRIPT_URL,
            sidebar_title=sidebar_title,
            sidebar_icon="mdi:format-list-group",
            embed_iframe=False,
            require_admin=False,
        )

    hass.data[f"{DOMAIN}_panel_registered"] = True
