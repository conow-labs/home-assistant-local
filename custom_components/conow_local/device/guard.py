"""Keep single-register writes out of the HA device page.

The finalized map is written one group at a time so a schedule or strategy is
applied atomically; toggling one register from the device page would split a
group across several frames. Every write attempt from a panel-backed entity
is refused and points the user at the grouping panel instead.
"""

from __future__ import annotations

from typing import NoReturn

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from ..const import DOMAIN, PANEL_URL_PATH

NOTIFICATION_TITLE = "Conow Local"

NOTIFICATION_MESSAGES = {
    "en": (
        "For atomic writes, apply the whole group in the "
        "[Conow Local panel]({url}). Single controls on the device page do "
        "not write directly."
    ),
    "de": (
        "Für atomare Schreibvorgänge senden Sie die ganze Gruppe im "
        "[Conow Local Gruppenpanel]({url}). Einzelne Bedienelemente auf der "
        "Geräteseite schreiben nicht direkt."
    ),
    "nl": (
        "Voor atomaire schrijfacties verzendt u de hele groep in het "
        "[Conow Local paneel]({url}). Losse bedieningselementen op de "
        "apparaatpagina schrijven niet direct."
    ),
    "zh-Hans": (
        "为保证原子性，请在 [Conow Local 面板]({url}) 中按分组整组下发；"
        "设备页上的单个控件不会直接写入。"
    ),
}


def _language(hass: HomeAssistant) -> str:
    """Return one of the supported notification languages."""
    language = str(hass.config.language or "")
    if language in NOTIFICATION_MESSAGES:
        return language
    if language.startswith("zh"):
        return "zh-Hans"
    base = language.split("-")[0]
    return base if base in NOTIFICATION_MESSAGES else "en"


def panel_url(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Return the same-origin panel link that preselects this device."""
    device_entry = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, entry.entry_id)}
    )
    device_id = device_entry.id if device_entry else entry.entry_id
    return f"/{PANEL_URL_PATH}?device_id={device_id}"


def async_refuse_device_write(hass: HomeAssistant, entry: ConfigEntry) -> NoReturn:
    """Tell the user to use the grouping panel and refuse the write."""
    url = panel_url(hass, entry)
    persistent_notification.async_create(
        hass,
        NOTIFICATION_MESSAGES[_language(hass)].format(url=url),
        title=NOTIFICATION_TITLE,
        notification_id=f"{DOMAIN}_panel_write_{entry.entry_id}",
    )
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="panel_write_required",
        translation_placeholders={"url": url},
    )
