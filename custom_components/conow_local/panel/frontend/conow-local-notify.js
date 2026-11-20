// Turn the Conow Local write-guard toast into a link to the grouping panel.
//
// The integration refuses single-register writes on the device page and raises
// a HomeAssistantError whose message ends with the panel URL. Home Assistant
// shows that message as a toast; the toast itself supports an action button, so
// this module adds "Open panel" to the notification before it is rendered.

const LABELS = {
  en: "Open panel",
  de: "Panel öffnen",
  nl: "Paneel openen",
  "zh-Hans": "打开面板",
};

const PANEL_URL = /\/conow-local-panel\?device_id=[A-Za-z0-9]+/;

function label() {
  const hass = document.querySelector("home-assistant")?.hass;
  const language = String(hass?.language || navigator.language || "en");
  if (LABELS[language]) {
    return LABELS[language];
  }
  const base = language.split("-")[0];
  if (base === "zh") {
    return LABELS["zh-Hans"];
  }
  return LABELS[base] || LABELS.en;
}

function addPanelAction(event) {
  const detail = event.detail;
  if (!detail || detail.conowPanelAction || typeof detail.message !== "string") {
    return;
  }
  const match = detail.message.match(PANEL_URL);
  if (!match) {
    return;
  }
  const url = match[0];
  // The URL only exists so this module gets the exact device; the action
  // button replaces it, so keep it out of the visible toast.
  detail.message = detail.message.replace(url, "").trimEnd();
  detail.conowPanelAction = true;
  detail.dismissable = true;
  detail.action = {
    text: label(),
    action: () => {
      window.location.assign(url);
    },
  };
}

// Capture phase: mutate the detail object before notification-manager reads it.
window.addEventListener("hass-notification", addPanelAction, true);
