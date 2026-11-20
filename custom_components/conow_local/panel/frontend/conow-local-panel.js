/**
 * Conow Local grouping panel.
 *
 * Renders the grouped finalized protocol map (`panel_registers.json`) with live
 * values read over Modbus by the integration. Writable registers are edited
 * with Home Assistant form controls and sent per group with one batch write.
 */

// Home Assistant resolves entity icons from
// homeassistant/components/<domain>/icons.json.  Keep the same tables here so
// a panel row shows the icon of the entity it links to (registry icon, then
// device_class, then the domain default).
const SENSOR_DEVICE_CLASS_ICONS = {
  battery: "mdi:battery-unknown",
  current: "mdi:current-ac",
  energy: "mdi:lightning-bolt",
  energy_storage: "mdi:car-battery",
  enum: "mdi:eye",
  frequency: "mdi:sine-wave",
  power: "mdi:flash",
  signal_strength: "mdi:wifi",
  temperature: "mdi:thermometer",
  voltage: "mdi:sine-wave",
};
// HA picks the highest threshold that is <= the battery level.
const SENSOR_BATTERY_LEVEL_ICONS = {
  0: "mdi:battery-alert",
  10: "mdi:battery-10",
  20: "mdi:battery-20",
  30: "mdi:battery-30",
  40: "mdi:battery-40",
  50: "mdi:battery-50",
  60: "mdi:battery-60",
  70: "mdi:battery-70",
  80: "mdi:battery-80",
  90: "mdi:battery-90",
  100: "mdi:battery",
};
const BINARY_SENSOR_DEVICE_CLASS_ICONS = {
  battery: { off: "mdi:battery", on: "mdi:battery-outline" },
  battery_charging: { off: "mdi:battery", on: "mdi:battery-charging" },
  connectivity: {
    off: "mdi:close-network-outline",
    on: "mdi:check-network-outline",
  },
  power: { off: "mdi:power-plug-off", on: "mdi:power-plug" },
  problem: { off: "mdi:check-circle", on: "mdi:alert-circle" },
  running: { off: "mdi:stop", on: "mdi:play" },
};
const DOMAIN_ICONS = {
  binary_sensor: { off: "mdi:radiobox-blank", on: "mdi:checkbox-marked-circle" },
  sensor: "mdi:eye",
  switch: { off: "mdi:toggle-switch-variant-off", on: "mdi:toggle-switch-variant" },
  time: "mdi:clock",
};

const PANEL_STYLE = `
  :host {
    display: block;
    padding: 16px;
    color: var(--primary-text-color, #e0e0e0);
    background: var(--primary-background-color, #111);
    min-height: 100%;
    box-sizing: border-box;
    font-family: var(--ha-font-family-body, Roboto, sans-serif);
  }
  h1 { margin: 0 0 4px; font-size: 1.5rem; font-weight: 500; }
  /* Freeze the title, filters and status banners as one block: scrolling the
     groups must never move the filters out of reach.  The negative side
     margins let the background cover the host padding, so cards cannot peek
     through the gutters next to the frozen block. */
  .page-header {
    position: sticky;
    top: 0;
    z-index: 30;
    margin: 0 -16px;
    padding: 8px 16px 0;
    background: var(--primary-background-color, #111);
  }
  .toolbar {
    display: flex; gap: 12px; align-items: center; flex-wrap: nowrap;
    margin-bottom: 16px;
    user-select: none;
    -webkit-user-select: none;
  }
  /* Fixed widths that may shrink, so the refresh button always stays on the
     same row instead of wrapping below the filters. */
  .toolbar .combo { position: relative; flex: 0 1 auto; min-width: 0; }
  .toolbar .combo[data-field="device"] { width: 240px; }
  .toolbar .combo[data-field="group"] { width: 180px; }
  .toolbar .combo[data-field="entity"] { width: 280px; }
  .toolbar .combo[data-field="access"] { width: 130px; }
  .toolbar .combo[data-field="poll"] { width: 120px; }
  .toolbar .combo-input {
    width: 100%;
    min-width: 0;
    box-sizing: border-box;
    padding-right: 34px;
    text-overflow: ellipsis;
    user-select: text;
    -webkit-user-select: text;
  }
  .toolbar .combo > ha-icon {
    position: absolute; right: 10px; top: 50%;
    transform: translateY(-50%);
    pointer-events: none;
    opacity: 0.7;
    --mdc-icon-size: 20px;
  }
  .combo-menu {
    position: absolute;
    z-index: 40;
    top: calc(100% + 4px);
    left: 0; right: 0;
    max-height: 300px;
    overflow-y: auto;
    padding: 4px;
    background: var(--card-background-color, #1c1c1c);
    border: 1px solid var(--divider-color, #333);
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
    user-select: none;
    -webkit-user-select: none;
  }
  .combo-menu[hidden] { display: none; }
  .combo-option {
    padding: 8px 10px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.9rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .combo-option:hover,
  .combo-option.active { background: var(--secondary-background-color, #2a2a2a); }
  .combo-option.selected { color: var(--primary-color, #03a9f4); }
  .combo-heading {
    padding: 8px 10px 4px;
    font-size: 0.75rem;
    opacity: 0.6;
  }
  .combo-empty { padding: 8px 10px; opacity: 0.6; font-size: 0.85rem; }
  .toolbar .icon-btn {
    margin-left: auto;
    width: 40px; height: 40px; padding: 0;
    border-radius: 50%;
    border: 1px solid var(--divider-color, #444);
    background: transparent;
    color: inherit;
    display: inline-flex; align-items: center; justify-content: center;
    flex: none;
  }
  .toolbar .icon-btn:hover { background: var(--secondary-background-color, #1c1c1c); }
  .toolbar .icon-btn ha-icon { --mdc-icon-size: 22px; }
  .toolbar .icon-btn.spinning ha-icon { animation: conow-spin 1s linear infinite; }
  @keyframes conow-spin { to { transform: rotate(360deg); } }
  select, input[type="text"] {
    background: var(--card-background-color, #1c1c1c);
    color: inherit;
    border: 1px solid var(--divider-color, #333);
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 0.95rem;
    min-width: 200px;
  }
  button {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
    border: none; border-radius: 8px;
    padding: 10px 16px; cursor: pointer; font-size: 0.9rem;
  }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .group {
    background: var(--card-background-color, #1c1c1c);
    border-radius: 12px;
    margin-bottom: 16px;
    overflow: hidden;
    border: 1px solid var(--divider-color, #2a2a2a);
  }
  .group-header {
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    padding: 14px 16px;
    border-bottom: 1px solid var(--divider-color, #2a2a2a);
    background: var(--secondary-background-color, #181818);
    cursor: pointer;
    user-select: none;
    -webkit-user-select: none;
  }
  .group-header:focus-visible {
    outline: 2px solid var(--primary-color, #03a9f4);
    outline-offset: -2px;
  }
  .group-header .group-toggle {
    --mdc-icon-size: 20px;
    margin-left: auto;
    color: inherit;
    opacity: 0.7;
    transition: transform 0.2s ease;
  }
  .group.collapsed .group-toggle { transform: rotate(-90deg); }
  .group.collapsed .group-body { display: none; }
  .group-header ha-icon { color: var(--primary-color, #03a9f4); --mdc-icon-size: 22px; }
  .group-title { font-weight: 600; font-size: 1rem; }
  .rows-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    column-gap: 24px;
  }
  .register-row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 16px;
    border-bottom: 1px solid var(--divider-color, #222);
    font-size: 0.9rem;
    min-width: 0;
  }
  .register-row:last-child { border-bottom: none; }
  .register-row.linkable { cursor: pointer; }
  .register-row.linkable:hover { background: var(--secondary-background-color, #1c1c1c); }
  .subgroup {
    margin: 10px 12px;
    border: 1px solid var(--divider-color, #2a2a2a);
    border-radius: 10px;
    overflow: hidden;
    background: color-mix(in srgb, var(--secondary-background-color, #181818) 55%, transparent);
  }
  .subgroup-header {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 14px;
    font-size: 0.84rem;
    font-weight: 600;
    background: var(--secondary-background-color, #181818);
    border-bottom: 1px solid var(--divider-color, #2a2a2a);
  }
  .subgroup .register-row { padding: 8px 14px; }
  .subgroup .register-row:last-child { border-bottom: none; }
  .reg-name { display: flex; gap: 10px; align-items: center; line-height: 1.35; min-width: 0; flex: 0 1 auto; }
  .reg-name ha-icon { flex: none; color: var(--primary-color, #03a9f4); --ha-icon-size: 20px; }
  .reg-name-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .reg-code { display: block; font-size: 0.75rem; opacity: 0.55; margin-top: 2px; }
  .reg-warning {
    color: var(--error-color, #f44336);
    font-size: 0.76rem;
    white-space: nowrap;
  }
  .register-row.invalid-time .reg-name ha-icon { color: var(--error-color, #f44336); }
  .empty, .error, .loading { padding: 24px; text-align: center; opacity: 0.8; }
  .hint {
    border: 1px solid var(--error-color, #f44336);
    background: color-mix(in srgb, var(--error-color, #f44336) 10%, transparent);
    border-radius: 10px;
    padding: 10px 14px;
    margin-bottom: 16px;
    font-size: 0.85rem;
    line-height: 1.45;
  }
  .error { color: var(--error-color, #f44336); }
  .group-footer {
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
    padding: 12px 16px 16px;
    border-top: 1px solid var(--divider-color, #2a2a2a);
    background: var(--secondary-background-color, #181818);
  }
  .group-hint { flex: 1 1 auto; min-width: 0; font-size: 0.8rem; opacity: 0.65; line-height: 1.45; }
  .group-apply { flex: 0 0 auto; margin-left: auto;
    padding: 8px 18px;
    border-radius: 999px;
    border: 1px solid var(--primary-color, #03a9f4);
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
    font-size: 0.88rem;
  }
  .group-apply:disabled {
    background: transparent;
    border-color: var(--divider-color, #3a3a3a);
    color: inherit;
    opacity: 0.45;
    cursor: not-allowed;
  }
  .notice {
    border: 1px solid var(--success-color, #4caf50);
    background: color-mix(in srgb, var(--success-color, #4caf50) 12%, transparent);
    border-radius: 10px;
    padding: 10px 14px;
    margin-bottom: 16px;
    font-size: 0.85rem;
  }
  .notice.error {
    border-color: var(--error-color, #f44336);
    background: color-mix(in srgb, var(--error-color, #f44336) 10%, transparent);
  }
  .modal-backdrop {
    position: fixed; inset: 0; z-index: 100;
    display: flex; align-items: center; justify-content: center;
    background: rgba(0, 0, 0, 0.6);
    padding: 16px;
    box-sizing: border-box;
  }
  .modal {
    width: min(360px, 100%);
    background: var(--card-background-color, #1c1c1c);
    color: var(--primary-text-color, #e0e0e0);
    border: 1px solid var(--divider-color, #333);
    border-radius: 14px;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
    padding: 20px;
    box-sizing: border-box;
  }
  .modal h2 {
    margin: 0 0 8px;
    font-size: 1.05rem;
    font-weight: 500;
  }
  .modal .modal-message {
    margin: 0;
    font-size: 0.9rem;
    color: var(--secondary-text-color, #aaa);
    line-height: 1.5;
  }
  .modal-actions {
    display: flex; justify-content: flex-end; gap: 10px;
    margin-top: 20px;
  }
  .modal-actions button {
    padding: 8px 18px;
    border-radius: 999px;
    font-size: 0.88rem;
    cursor: pointer;
  }
  .modal-actions .modal-cancel {
    background: transparent;
    border: 1px solid var(--divider-color, #3a3a3a);
    color: inherit;
  }
  .modal-actions .modal-confirm {
    border: 1px solid var(--primary-color, #03a9f4);
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
  }
  .reg-control {
    display: flex; align-items: center; justify-content: flex-end;
    gap: 8px; min-width: 0; flex: 0 0 auto;
  }
  /* Field that does not apply to the current mode (TOU charge/discharge). */
  .reg-control.inactive { opacity: 0.45; }
  .reg-control ha-input,
  .reg-control ha-select { flex: 0 1 160px; min-width: 96px; }
  .reg-control ha-slider { flex: 1 1 auto; min-width: 40px; }
  .reg-control .reg-slider-value {
    flex: 0 0 auto;
    min-width: 38px;
    text-align: end;
    color: var(--secondary-text-color);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .reg-control ha-time-input { flex: 0 1 auto; min-width: 132px; }
  .reg-control ha-switch { flex: 0 0 auto; }
  .reg-control.has-slider { flex: 0 1 240px; }
  .reg-control.has-slider ha-input { flex: 0 1 88px; min-width: 64px; }
  .reg-control ha-input::part(wa-input) { text-align: end; }
  .reg-value {
    flex: 0 0 auto;
    margin-left: auto;
    padding-left: 12px;
    text-align: right;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-variant-numeric: tabular-nums;
  }
  .reg-value.empty { opacity: 0.45; }
  @media (max-width: 720px) {
    .register-row { flex-wrap: wrap; gap: 8px; }
    .reg-name { flex: 1 1 100%; }
    .group-footer { flex-direction: column; align-items: stretch; }
  }
`;

const ASSET_VERSION = new URL(import.meta.url).searchParams.get("v") || "";
const FALLBACK_LANGUAGE = "en";
// Per-device polling interval choices (seconds), matching
// const.POLL_INTERVAL_OPTIONS on the backend.
const POLL_INTERVAL_OPTIONS = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60];

class ConowLocalPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._deviceId = null;
    this._devices = [];
    this._state = null;
    this._mapState = null;
    this._mapVersion = null;
    this._i18n = null;
    this._language = null;
    this._i18nReady = Promise.resolve();
    this._groupFilter = "";
    this._entityFilter = "";
    this._accessFilter = "all";
    this._collapsed = new Set();
    this._loading = false;
    this._error = null;
    this._drafts = {};
    this._pendingGroups = new Set();
    this._notice = null;
    this._timeLoader = null;
    this._invalidNotified = null;
    this._lastNotice = null;
    this._lastNoticeAt = 0;
    this._styleEl = document.createElement("style");
    this._styleEl.textContent = PANEL_STYLE;
    this._root = document.createElement("div");
    this.shadowRoot.append(this._styleEl, this._root);
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const language = this._normalizeLanguage(hass?.language);
    if (language !== this._language) {
      this._language = language;
      this._i18nReady = this._loadI18n(language).then(() => {
        if (!first) {
          this._render();
        }
      });
    }
    if (first) {
      if (!this._deviceId) {
        this._readDeviceFromUrl();
      }
      this._loadMap();
      this._loadDevices();
    }
  }

  // Home Assistant exposes the profile language; `zh-*` all share one file.
  _normalizeLanguage(language) {
    const value = String(language || "").toLowerCase();
    if (value.startsWith("zh")) {
      return "zh-Hans";
    }
    if (value.startsWith("de")) {
      return "de";
    }
    if (value.startsWith("nl")) {
      return "nl";
    }
    return FALLBACK_LANGUAGE;
  }

  async _loadI18n(language) {
    const load = async (lang) => {
      const url = new URL(
        `i18n/${lang}.json?v=${ASSET_VERSION}`,
        import.meta.url
      );
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.json();
    };
    try {
      this._i18n = await load(language);
    } catch (err) {
      // Fall back to English, then to the Chinese labels carried by the map.
      try {
        this._i18n = await load(FALLBACK_LANGUAGE);
      } catch {
        this._i18n = { ui: {}, groups: {}, registers: {}, values: {}, subgroups: {} };
      }
    }
  }

  _t(key, values) {
    let text = this._i18n?.ui?.[key] ?? key;
    if (values) {
      text = text.replace(/\{(\w+)\}/g, (match, name) =>
        values[name] === undefined ? match : String(values[name])
      );
    }
    return text;
  }

  _regName(register) {
    return this._i18n?.registers?.[register.code] || register.name;
  }

  _groupLabel(group) {
    return this._i18n?.groups?.[group.id] || group.label;
  }

  _subgroupLabel(subgroup, slot) {
    const template = subgroup?.key
      ? this._i18n?.subgroups?.[subgroup.key]
      : null;
    return template ? template.replace("{n}", slot) : subgroup?.label || "";
  }

  _enumLabel(register, raw) {
    const translated = this._i18n?.values?.[register.code]?.[String(raw)];
    if (translated !== undefined) {
      return translated;
    }
    const label = (register.values || {})[String(raw)];
    return label !== undefined ? label : String(raw);
  }

  _bitLabel(register, value) {
    const on = String(value) === "1" || value === true;
    const translated = this._i18n?.values?.[register.code]?.[on ? "1" : "0"];
    if (translated !== undefined) {
      return translated;
    }
    return this._t(on ? "valueOn" : "valueOff");
  }

  async _loadMap(mapVersion = null) {
    await this._i18nReady;
    try {
      this._mapState = await this._callWS(
        "conow_local/get_panel_map",
        mapVersion ? { map_version: mapVersion } : {}
      );
      this._render();
    } catch (err) {
      this._error = this._errorText(err);
      this._render();
    }
  }

  get hass() {
    return this._hass;
  }

  set deviceId(deviceId) {
    this._deviceId = deviceId || null;
    if (this._hass) {
      this._loadFunctions();
    }
  }

  get deviceId() {
    return this._deviceId;
  }

  _readDeviceFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const deviceId = params.get("device_id");
    if (deviceId) {
      this._deviceId = deviceId;
    }
  }

  _syncUrl() {
    const url = new URL(window.location.href);
    if (this._deviceId) {
      url.searchParams.set("device_id", this._deviceId);
    } else {
      url.searchParams.delete("device_id");
    }
    window.history.replaceState(null, "", url);
  }

  async _callWS(type, extra = {}) {
    return this._hass.callWS({ type, ...extra });
  }

  async _loadDevices() {
    await this._i18nReady;
    this._loading = true;
    this._error = null;
    this._render();
    try {
      const result = await this._callWS("conow_local/get_panel_devices");
      this._devices = result.devices || [];
      const current = this._deviceId
        ? this._devices.find(
            (device) =>
              device.device_id === this._deviceId ||
              device.entry_id === this._deviceId
          )
        : null;
      if (current && current.device_id !== this._deviceId) {
        // The URL can carry a config entry id; the selector uses device ids.
        this._deviceId = current.device_id;
        this._syncUrl();
      }
      if (!this._deviceId) {
        // Prefer a device we know is reachable, then a loaded entry, so the
        // page shows values as soon as it opens; the selector switches device.
        const preferred =
          this._devices.find((device) => device.online) ||
          this._devices.find((device) => device.loaded) ||
          this._devices.find((device) => String(device.mode || "").startsWith("tcp")) ||
          this._devices[0] ||
          null;
        if (preferred) {
          this._deviceId = preferred.device_id;
          this._syncUrl();
        }
      }
      if (this._deviceId) {
        await this._loadFunctions();
      } else {
        this._loading = false;
        this._render();
      }
    } catch (err) {
      this._loading = false;
      this._error = this._errorText(err);
      this._render();
    }
  }

  async _loadFunctions() {
    if (!this._deviceId) {
      return;
    }
    await this._i18nReady;
    const hadState = Boolean(this._state);
    this._error = null;
    if (hadState) {
      // Refresh in place: keep the current rows visible and only spin the
      // icon, so a manual refresh never blanks the page.
      this._setRefreshSpinning(true);
    } else {
      this._loading = true;
      this._render();
    }
    try {
      const state = await this._callWS("conow_local/get_panel_functions", {
        device_id: this._deviceId,
      });
      this._state = state;
      this._drafts = {};
      this._pendingGroups.clear();
      this._notice = null;
      this._error = null;
      const mapVersion = state.map_version === 1 ? "v1" : "v2";
      if (mapVersion !== this._mapVersion) {
        // Request the same map the device uses; without a device the server
        // returns an empty map instead of flashing the v2 groups.
        this._mapVersion = mapVersion;
        this._loadMap(mapVersion);
      }
      this._notifyInvalidTimes();
    } catch (err) {
      this._state = null;
      this._error = this._errorText(err);
    } finally {
      this._loading = false;
      this._setRefreshSpinning(false);
      this._render();
    }
  }

  _errorText(err) {
    const message = err?.message || String(err);
    if (message.includes("not_found")) {
      return this._t("errorDeviceNotFound");
    }
    if (message.includes("Unknown command") || message.includes("unknown_command")) {
      return this._t("errorUnknownCommand");
    }
    return message;
  }

  _escape(text) {
    return String(text ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  _entityIcon(register) {
    const entityId = register.entity_id;
    if (!entityId) {
      return "";
    }
    const state = this._hass?.states?.[entityId];
    // Entity-registry icon overrides win in Home Assistant too.
    const custom =
      state?.attributes?.icon || this._hass?.entities?.[entityId]?.icon;
    if (custom) {
      return custom;
    }
    const domain = entityId.slice(0, entityId.indexOf("."));
    const deviceClass = state?.attributes?.device_class;
    const key = state?.state === "on" ? "on" : "off";
    if (domain === "sensor") {
      if (deviceClass === "battery") {
        const level = Number(state?.state);
        if (Number.isFinite(level)) {
          let icon = "";
          for (const [threshold, candidate] of Object.entries(
            SENSOR_BATTERY_LEVEL_ICONS
          )) {
            if (level >= Number(threshold)) {
              icon = candidate;
            }
          }
          if (icon) {
            return icon;
          }
        }
      }
      return (
        (deviceClass && SENSOR_DEVICE_CLASS_ICONS[deviceClass]) ||
        DOMAIN_ICONS.sensor
      );
    }
    if (domain === "binary_sensor") {
      return (
        (deviceClass && BINARY_SENSOR_DEVICE_CLASS_ICONS[deviceClass]) ||
        DOMAIN_ICONS.binary_sensor
      )[key];
    }
    if (domain === "switch") {
      return DOMAIN_ICONS.switch[key];
    }
    return DOMAIN_ICONS[domain] || "";
  }

  _controlIcon(register) {
    switch (register.control) {
      case "time":
        return "mdi:clock-outline";
      case "switch":
        return register.raw
          ? "mdi:toggle-switch-variant"
          : "mdi:toggle-switch-variant-off";
      case "enum":
        return "mdi:format-list-bulleted";
      case "bit": {
        const icons = BINARY_SENSOR_DEVICE_CLASS_ICONS[register.device_class];
        const key = register.raw ? "on" : "off";
        return (
          (icons && icons[key]) ||
          (register.raw ? "mdi:checkbox-marked-circle" : "mdi:radiobox-blank")
        );
      }
      case "text":
        return "mdi:form-textbox";
      default:
        return "mdi:tune-variant";
    }
  }

  _renderRegister(register, group) {
    const invalidTime = this._timeInvalid(register);
    // The tooltip names the address and data type on the first line and, when
    // the map documents one, the direction or other device-specific meaning
    // on a second "desc:" line.
    const dtypeLabel =
      {
        uint16: "U16",
        uint32: "U32",
        int16: "I16",
        int32: "I32",
        float32: "F32",
        string: "STR",
      }[register.dtype] || String(register.dtype || "").toUpperCase();
    const hints = [`Address: ${register.address_hex} · ${dtypeLabel}`];
    if (register.note) {
      hints.push(`desc: ${register.note}`);
    }
    if (invalidTime) {
      hints.push(
        `Invalid device time ${this._rawHex(
          register
        )}: not a valid HH:MM value (00:00–23:59); it is hidden — set a new time before applying.`
      );
    }
    const title = ` title="${this._escape(hints.join("\n"))}"`;
    // Prefer the mapped entity's own icon (registry override, device_class
    // and state), so rows look exactly like the entity list; fall back to a
    // control-type icon for registers without an entity.
    const icon =
      invalidTime
        ? "mdi:alert-outline"
        : this._entityIcon(register) || this._controlIcon(register);
    const bounds = this._effectiveBounds(group.id, register);
    const slider = this._sliderEnabled(register, bounds) ? " has-slider" : "";
    const value = this._controlValue(group.id, register);
    const editable = Boolean(register.writable && this._state?.map_readable);
    const enabled = this._dependencyEnabled(group.id, register);
    const dependsOn = register.enabled_when
      ? ` data-depends-on="${this._escape(register.enabled_when.code)}"`
      : "";
    const entity = register.entity_id
      ? ` data-entity="${this._escape(register.entity_id)}"`
      : "";
    const control = editable
      ? `<div class="reg-control${slider}${
          enabled ? "" : " inactive"
        }" data-group="${group.id}" data-code="${
          register.code
        }" data-value="${this._escape(value)}" data-editable="1"${dependsOn}>${this._renderControl(
          register,
          group.id,
          bounds,
          enabled
        )}</div>`
      : this._renderReadonlyValue(register);
    return `
      <div class="register-row${register.entity_id ? " linkable" : ""}${
        invalidTime ? " invalid-time" : ""
      }"${entity}${title}>
        <div class="reg-name">
          <ha-icon icon="${icon}"></ha-icon>
          <div class="reg-name-text">
            ${this._escape(this._regName(register))}
            <span class="reg-code">${this._escape(register.code)}</span>
          </div>
        </div>
        ${control}
      </div>
    `;
  }

  _renderReadonlyValue(register) {
    const text = this._timeInvalid(register)
      ? ""
      : this._formatRegisterValue(register, this._currentValue(register));
    return `<div class="reg-value${text ? "" : " empty"}">${this._escape(
      text
    )}</div>`;
  }

  _accessMatches(register) {
    // Toolbar access filter: "rw" = 可写 only, "ro" = 只读 only.
    if (this._accessFilter === "rw") {
      return Boolean(register.writable);
    }
    if (this._accessFilter === "ro") {
      return !register.writable;
    }
    return true;
  }

  _slotLimit(group) {
    // Groups whose slots are numbered by a count register (时段数 / 策略数)
    // only render that many slot sections.
    const code = group?.count_register;
    if (!code) {
      return null;
    }
    const register = (group.members || []).find((item) => item.code === code);
    if (!register) {
      return null;
    }
    const raw = this._draftValue(group.id, register);
    if (raw === "" || raw === null || raw === undefined) {
      return null;
    }
    const count = Number(raw);
    if (!Number.isFinite(count)) {
      return null;
    }
    return Math.max(0, Math.min(count, (group.subgroups || []).length));
  }

  _syncSlotVisibility(groupId) {
    const group = this._state?.groups?.[groupId];
    if (!group?.count_register) {
      return;
    }
    const limit = this._slotLimit(group);
    this._root
      .querySelectorAll(`section.subgroup[data-group="${groupId}"]`)
      .forEach((section) => {
        const hidden =
          !this._entityFilter &&
          limit !== null &&
          Number(section.dataset.slot) > limit;
        section.style.display = hidden ? "none" : "";
      });
  }

  _syncAllSlotVisibility() {
    for (const groupId of Object.keys(this._state?.groups || {})) {
      this._syncSlotVisibility(groupId);
    }
  }

  _slotIncluded(group, register) {
    // Slots past the submitted count (时段数 / 策略数) are neither displayed
    // nor written, so their leftover values must not block validation or
    // show up as pending changes.
    const limit = this._slotLimit(group);
    if (limit === null) {
      return true;
    }
    const index = (group.subgroups || []).findIndex((subgroup) =>
      (subgroup.members || []).includes(register.code)
    );
    return index < 0 || index < limit;
  }

  _dependencyValue(groupId, register) {
    // Mode-dependent settings follow the draft of their source register, so
    // switching 工作模式 immediately enables the matching field.
    const dependency = register?.enabled_when;
    if (!dependency) {
      return undefined;
    }
    const source = this._findRegister(groupId, dependency.code);
    return source ? this._draftValue(groupId, source) : undefined;
  }

  _dependencyEnabled(groupId, register) {
    const dependency = register?.enabled_when;
    if (!dependency) {
      return true;
    }
    const value = this._dependencyValue(groupId, register);
    return (dependency.values || []).some(
      (allowed) => String(allowed) === String(value)
    );
  }

  _syncDependencyControls(groupId) {
    // Toggle in place: a full re-render would lose the scroll position and
    // the editor the user is working in.
    if (this._pendingGroups.has(groupId)) {
      return;
    }
    this._root
      .querySelectorAll(
        `.reg-control[data-group="${groupId}"][data-depends-on]`
      )
      .forEach((control) => {
        const register = this._findRegister(groupId, control.dataset.code);
        if (!register) {
          return;
        }
        const enabled = this._dependencyEnabled(groupId, register);
        control.classList.toggle("inactive", !enabled);
        control
          .querySelectorAll(
            "ha-input, ha-select, ha-slider, ha-time-input, ha-switch"
          )
          .forEach((element) => {
            // Set the property as well: these HA controls do not all reflect
            // the attribute in both directions.
            element.disabled = !enabled;
            if (enabled) {
              element.removeAttribute("disabled");
            } else {
              element.setAttribute("disabled", "");
            }
          });
      });
  }

  _syncAllDependencyControls() {
    for (const groupId of Object.keys(this._state?.groups || {})) {
      this._syncDependencyControls(groupId);
    }
  }

  _renderMemberRows(group) {
    const members = (group.members || []).filter(
      (item) =>
        this._accessMatches(item) &&
        (!this._entityFilter || item.code === this._entityFilter)
    );
    const subgroups = group.subgroups || [];
    const subgroupIndex = new Map();
    subgroups.forEach((subgroup, index) => {
      subgroup.members.forEach((code) => {
        if (!subgroupIndex.has(code)) {
          subgroupIndex.set(code, index);
        }
      });
    });
    const byCode = new Map(members.map((item) => [item.code, item]));
    const emitted = new Set();
    const limit = this._slotLimit(group);
    let html = "";
    // Rows flow in a responsive grid so several registers share one line;
    // every run of plain rows between subgroups becomes its own grid.
    let pending = [];
    const flush = () => {
      if (!pending.length) {
        return;
      }
      html += `<div class="rows-grid">${pending.join("")}</div>`;
      pending = [];
    };
    for (const register of members) {
      const index = subgroupIndex.get(register.code);
      if (index === undefined) {
        pending.push(this._renderRegister(register, group));
        continue;
      }
      if (emitted.has(index)) {
        continue;
      }
      emitted.add(index);
      const subgroup = subgroups[index];
      const rows = subgroup.members
        .map((code) => byCode.get(code))
        .filter(Boolean);
      if (!rows.length) {
        continue;
      }
      // The count register ("时段数" / "策略数") decides how many slot
      // sections are active; _syncSlotVisibility() keeps this live while the
      // user edits the count.
      const slot = index + 1;
      // An explicitly picked entity is always shown, even when its slot lies
      // past the device's slot count.
      const hidden =
        !this._entityFilter && limit !== null && slot > limit;
      flush();
      html += `
        <section class="subgroup" data-group="${this._escape(group.id)}"
          data-slot="${slot}"${hidden ? ' style="display: none;"' : ""}>
          <div class="subgroup-header">
            <span class="subgroup-title">${this._escape(
              this._subgroupLabel(subgroup, slot)
            )}</span>
          </div>
          <div class="rows-grid">
            ${rows.map((item) => this._renderRegister(item, group)).join("")}
          </div>
        </section>
      `;
    }
    flush();
    return html;
  }

  _controlValue(groupId, register) {
    const editable = Boolean(register.writable && this._state?.map_readable);
    let value;
    if (editable) {
      value = this._draftValue(groupId, register);
    } else if (
      register.control === "enum" ||
      register.control === "switch"
    ) {
      value = register.raw;
    } else {
      value = register.display;
    }
    if (this._timeInvalid(register)) {
      // Never show (or seed an editor with) an impossible time.
      value = "";
    }
    return value === null || value === undefined ? "" : String(value);
  }

  _sliderText(register, value) {
    if (value === "" || value === null || value === undefined) {
      return "—";
    }
    return `${value}${register?.unit || ""}`;
  }

  _sliderEnabled(register, bounds = register.bounds) {
    if (
      register.control !== "number" ||
      register.unit !== "%" ||
      !register.writable ||
      !this._state?.map_readable ||
      !Array.isArray(bounds)
    ) {
      return false;
    }
    const [min, max] = bounds;
    return Number.isFinite(Number(min)) && Number.isFinite(Number(max));
  }

  _findRegister(groupId, code) {
    const group = this._state?.groups?.[groupId];
    return (group?.members || []).find((item) => item.code === code);
  }

  _draftValue(groupId, register) {
    const draft = this._drafts[groupId];
    if (draft && draft[register.code] !== undefined) {
      return draft[register.code];
    }
    if (this._timeInvalid(register)) {
      // Leave the editor empty so the user has to supply a valid time.
      return "";
    }
    return register.values ? register.raw : register.value;
  }

  _currentValue(register) {
    return register.values ? register.raw : register.value;
  }

  _isLiveValue(register, value) {
    // A value the device already holds is written back unchanged.  Dynamic
    // limits may exclude it (an old schedule below today's SoC), which must
    // not block editing another field of the same group.
    const current = this._currentValue(register);
    return (
      current !== null &&
      current !== undefined &&
      String(value) === String(current)
    );
  }

  _findMember(code) {
    for (const group of Object.values(this._state?.groups || {})) {
      const member = (group.members || []).find((item) => item.code === code);
      if (member) {
        return member;
      }
    }
    return null;
  }

  _draftNumber(code) {
    for (const drafts of Object.values(this._drafts)) {
      const value = drafts?.[code];
      if (value === undefined || value === "") {
        continue;
      }
      const numeric = Number(value);
      if (Number.isFinite(numeric)) {
        return numeric;
      }
    }
    return null;
  }

  _liveNumber(code) {
    const value = this._findMember(code)?.value;
    if (value === null || value === undefined || value === "") {
      // Number(null) is 0, which would silently pin a bound to zero.
      return null;
    }
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }

  _socNumber(...codes) {
    for (const code of codes) {
      const drafted = this._draftNumber(code);
      if (drafted !== null) {
        return drafted;
      }
      const live = this._liveNumber(code);
      if (live !== null) {
        return live;
      }
    }
    return null;
  }

  _effectiveBounds(groupId, register) {
    // The cutoff SoC range follows the forced direction: both directions
    // start at the safety SoC, charging runs up to 100 %, discharging stops
    // at the cutoff so it cannot be raised above the current battery SoC.
    if (!register || !String(register.code).endsWith("cutoff_soc")) {
      return register?.bounds || null;
    }
    // ``bounds`` from the server already reflect the direction the device
    // currently holds, so they cannot be widened again.  Rebase the drafted
    // range on the map's static limits instead.
    const base = Array.isArray(register.static_bounds)
      ? register.static_bounds
      : register.bounds;
    const staticMin = Array.isArray(base) ? base[0] : 0;
    const staticMax = Array.isArray(base) ? base[1] : 100;
    const step = Array.isArray(base) ? base[2] : 1;
    const liveBounds = Array.isArray(register.bounds) ? register.bounds : null;
    const drafted = this._drafts[groupId]?.["charge_discharge_direction"];
    const selected =
      drafted !== undefined && drafted !== ""
        ? drafted
        : this._findMember("charge_discharge_direction")?.raw;
    const direction =
      selected === null || selected === undefined || selected === ""
        ? null
        : Number(selected);
    if (direction !== 1 && direction !== 2) {
      return liveBounds;
    }
    // A missing safety SoC still leaves the direction-dependent maximum
    // (the current battery SoC) in force.
    const safety = this._socNumber("safety_soc");
    const min = safety === null ? staticMin : Math.max(staticMin, safety);
    let max = staticMax;
    if (direction === 2) {
      const soc = this._socNumber("system_soc", "battery_soc");
      if (soc !== null) {
        max = Math.min(staticMax, soc);
      }
    }
    if (max < min) {
      max = min;
    }
    return [min, max, step ?? 1];
  }

  _syncCutoffControls() {
    for (const group of Object.values(this._state?.groups || {})) {
      for (const register of group.members || []) {
        if (!register.writable || !String(register.code).endsWith("cutoff_soc")) {
          continue;
        }
        const bounds = this._effectiveBounds(group.id, register);
        if (!Array.isArray(bounds)) {
          continue;
        }
        const control = this._root.querySelector(
          `.reg-control[data-group="${group.id}"][data-code="${register.code}"]`
        );
        if (!control) {
          continue;
        }
        const [min, max, step] = bounds;
        const slider = control.querySelector("ha-slider");
        const input = control.querySelector("ha-input");
        for (const element of [slider, input]) {
          if (!element) {
            continue;
          }
          element.setAttribute("min", min);
          element.setAttribute("max", max);
          if (step !== undefined) {
            element.setAttribute("step", step);
          }
          if (typeof element.requestUpdate === "function") {
            // ha-slider/ha-input are Lit elements: the rendered track follows
            // the reactive properties, which a late attribute change does not
            // reliably refresh.  Set both and force the update.
            element.min = Number(min);
            element.max = Number(max);
            if (step !== undefined) {
              element.step = Number(step);
            }
            element.requestUpdate();
          }
        }
        const current = this._draftValue(group.id, register);
        const numeric = Number(current);
        if (
          current !== "" &&
          current !== null &&
          current !== undefined &&
          Number.isFinite(numeric) &&
          (numeric < min || numeric > max)
        ) {
          const clamped = Math.min(Math.max(numeric, min), max);
          this._drafts[group.id] = this._drafts[group.id] || {};
          this._drafts[group.id][register.code] = String(clamped);
          const slider = control.querySelector("ha-slider");
          if (slider) {
            slider.value = clamped;
          }
          const badge = control.querySelector(".reg-slider-value");
          if (badge) {
            badge.textContent = this._sliderText(register, clamped);
          }
          this._notify(
            this._t("noticeClamped", {
              name: this._regName(register),
              value: clamped,
              min,
              max,
            }),
            3000
          );
        }
        this._refreshApply(group.id);
      }
    }
  }

  _changedRegisters(group) {
    return (group.members || []).filter((register) => {
      if (
        !register.writable ||
        !this._dependencyEnabled(group.id, register) ||
        !this._slotIncluded(group, register)
      ) {
        // A field that does not apply to the current mode is never written,
        // and neither is a slot past the count; their leftover drafts must
        // not mark the group dirty.
        return false;
      }
      const draft = this._draftValue(group.id, register);
      const current = this._currentValue(register);
      return String(draft ?? "") !== String(current ?? "");
    });
  }

  _isDirty(group) {
    return this._changedRegisters(group).length > 0;
  }

  _formatRegisterValue(register, value) {
    if (value === null || value === undefined || value === "") {
      return "—";
    }
    if (register.control === "bit") {
      return this._bitLabel(register, value);
    }
    if (register.control === "switch") {
      return String(value) === "1" || value === true
        ? this._t("valueOn")
        : this._t("valueOff");
    }
    if (register.control === "enum") {
      return this._enumLabel(register, value);
    }
    if (register.control === "time") {
      return this._normalizeTime(value) || String(value);
    }
    const numeric = Number(value);
    const text =
      Number.isFinite(numeric) && String(value).trim() !== ""
        ? Number(numeric.toFixed(4)).toLocaleString(undefined, {
            maximumFractionDigits: 4,
          })
        : String(value);
    const unit = register.unit || "";
    // Percent stays attached ("50%"); power/energy/voltage read better with a
    // space ("6,000 W").
    return `${text}${unit && unit !== "%" ? ` ${unit}` : unit}`;
  }

  _changedSummary(group) {
    // One "from old to new" entry per staged register, so the footer says what
    // the batch write will actually change.
    return this._changedRegisters(group)
      .map((register) =>
        this._t("changedFromTo", {
          name: this._regName(register),
          old: this._formatRegisterValue(
            register,
            this._currentValue(register)
          ),
          new: this._formatRegisterValue(
            register,
            this._draftValue(group.id, register)
          ),
        })
      )
      .join(this._t("changedSeparator"));
  }

  _normalizeTime(value) {
    if (value === undefined || value === null) {
      return "";
    }
    const parts = String(value).split(":");
    if (parts.length < 2) {
      return "";
    }
    const hour = Number(parts[0]);
    const minute = Number(parts[1]);
    if (!Number.isFinite(hour) || !Number.isFinite(minute)) {
      return "";
    }
    return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
  }

  _clampTime(value) {
    // Registers hold 00:00–23:59; the time widget lets users type past that.
    const normalized = this._normalizeTime(value);
    if (!normalized) {
      return "";
    }
    const [hour, minute] = normalized.split(":").map(Number);
    const clampedHour = Math.min(23, Math.max(0, hour));
    const clampedMinute = Math.min(59, Math.max(0, minute));
    return `${String(clampedHour).padStart(2, "0")}:${String(
      clampedMinute
    ).padStart(2, "0")}`;
  }

  _timeMinutes(value) {
    // Minutes since midnight for a valid HH:MM value, else null.
    const normalized = this._normalizeTime(value);
    if (!normalized) {
      return null;
    }
    const [hour, minute] = normalized.split(":").map(Number);
    if (hour > 23 || minute > 59) {
      return null;
    }
    return hour * 60 + minute;
  }

  _slotTimeCodes(group, members) {
    // A plan-table slot carries one start and one end time register; find
    // them by code rather than by position in the subgroup.
    const registers = members
      .map((code) => this._findRegister(group.id, code))
      .filter((register) => register && register.control === "time");
    return {
      start: registers.find((register) => /_start$/.test(register.code)),
      end: registers.find((register) => /_end$/.test(register.code)),
    };
  }

  _groupTimeOrder(group) {
    // Time slots may leave gaps but must not cross: every start is earlier
    // than its end, and no slot begins before the previous one ends.  Only
    // the submitted count (时段数 / 策略数) is considered.  Returns the
    // affected slot labels for the footer hint.
    const limit = this._slotLimit(group);
    const intervals = [];
    const slots = new Set();
    (group.subgroups || []).forEach((subgroup, index) => {
      if (limit !== null && index >= limit) {
        return;
      }
      const { start, end } = this._slotTimeCodes(group, subgroup.members || []);
      if (!start || !end) {
        return;
      }
      const from = this._timeMinutes(this._draftValue(group.id, start));
      const to = this._timeMinutes(this._draftValue(group.id, end));
      if (from === null || to === null) {
        // Empty or malformed values are reported as incomplete/invalid.
        return;
      }
      const label = subgroup.label || start.code;
      if (from >= to) {
        slots.add(label);
        return;
      }
      intervals.push({ from, to, label });
    });
    intervals.sort((left, right) => left.from - right.from);
    for (let index = 1; index < intervals.length; index += 1) {
      if (intervals[index].from < intervals[index - 1].to) {
        slots.add(intervals[index - 1].label);
        slots.add(intervals[index].label);
      }
    }
    return [...slots];
  }

  _rawHex(register) {
    const raw = Number(register.raw);
    if (!Number.isFinite(raw)) {
      return "";
    }
    return `0x${(raw & 0xffff).toString(16).toUpperCase().padStart(4, "0")}`;
  }

  _timeInvalid(register) {
    // The device can return anything in a time register (e.g. 0xAA16); only
    // high byte 00–23 / low byte 00–59 is a real HH:MM.
    if (register?.control !== "time") {
      return false;
    }
    const raw = Number(register.raw);
    if (!Number.isFinite(raw)) {
      return false;
    }
    return ((raw >> 8) & 0xff) > 23 || (raw & 0xff) > 59;
  }

  _invalidTimeCodes() {
    const codes = new Set();
    for (const group of Object.values(this._state?.groups || {})) {
      for (const register of group.members || []) {
        if (this._timeInvalid(register)) {
          codes.add(register.code);
        }
      }
    }
    return [...codes];
  }

  _groupInvalidTimes(group) {
    // Registers the user still has to fix: invalid on the device and no valid
    // draft typed in yet.
    return (group.members || [])
      .filter(
        (register) =>
          register.writable &&
          this._slotIncluded(group, register) &&
          this._timeInvalid(register) &&
          this._draftValue(group.id, register) === ""
      )
      .map((register) => register.code);
  }

  _groupOutOfRange(group) {
    return (group.members || [])
      .filter((register) => {
        if (
          !register.writable ||
          register.control !== "number" ||
          !Array.isArray(register.bounds) ||
          !this._dependencyEnabled(group.id, register) ||
          !this._slotIncluded(group, register)
        ) {
          return false;
        }
        const value = this._draftValue(group.id, register);
        if (value === "" || value === null || value === undefined) {
          return false;
        }
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) {
          return false;
        }
        if (this._isLiveValue(register, value)) {
          // Unchanged device value written back as-is; not this group's edit.
          return false;
        }
        const bounds = this._effectiveBounds(group.id, register);
        if (!Array.isArray(bounds)) {
          return false;
        }
        const [min, max] = bounds;
        return numeric < min || numeric > max;
      })
      .map((register) => register.code);
  }

  _groupHint(group, valid, dirty) {
    const separator = this._t("codeSeparator");
    const invalid = this._groupInvalidTimes(group);
    if (invalid.length) {
      return this._t("groupHintInvalidTime", { codes: invalid.join(separator) });
    }
    const timeOrder = this._groupTimeOrder(group);
    if (timeOrder.length) {
      return this._t("groupHintTimeOrder", {
        slots: timeOrder.join(separator),
      });
    }
    const outOfRange = this._groupOutOfRange(group);
    if (outOfRange.length) {
      return this._t("groupHintOutOfRange", {
        codes: outOfRange.join(separator),
      });
    }
    if (!valid) {
      return this._t("groupHintIncomplete");
    }
    return dirty ? this._changedSummary(group) : this._t("groupHintUnchanged");
  }

  _notify(message, duration = 5000) {
    // Home Assistant's notification manager listens for this event and shows
    // a toast, so panel-side warnings surface as a real popup.
    const now = Date.now();
    if (message === this._lastNotice && now - this._lastNoticeAt < 2000) {
      return;
    }
    this._lastNotice = message;
    this._lastNoticeAt = now;
    this.dispatchEvent(
      new CustomEvent("hass-notification", {
        detail: { message, duration },
        bubbles: true,
        composed: true,
      })
    );
  }

  _notifyInvalidTimes() {
    const codes = this._invalidTimeCodes().sort();
    if (!codes.length) {
      this._invalidNotified = null;
      return;
    }
    const key = codes.join(",");
    if (key === this._invalidNotified) {
      return;
    }
    this._invalidNotified = key;
    const preview = codes
      .slice(0, 3)
      .join(this._t("codeSeparator"));
    this._notify(
      this._t("noticeInvalidTimes", {
        count: codes.length,
        preview,
        more: codes.length > 3 ? this._t("noticeInvalidTimesMore") : "",
      }),
      10000
    );
  }

  _isValid(group) {
    if (this._groupTimeOrder(group).length) {
      // Slots that cross or end before they start are never sent.
      return false;
    }
    return (group.members || [])
      .filter((register) => register.writable)
      .every((register) => {
        // The field the current mode does not use is not written; its draft
        // must not block the group.  The same goes for slots past the count.
        if (
          !this._dependencyEnabled(group.id, register) ||
          !this._slotIncluded(group, register)
        ) {
          return true;
        }
        const value = this._draftValue(group.id, register);
        if (value === "" || value === null || value === undefined) {
          return false;
        }
        if (register.control === "time") {
          return /^([01]\d|2[0-3]):[0-5]\d$/.test(String(value));
        }
        if (register.control === "number") {
          const numeric = Number(value);
          if (!Number.isFinite(numeric)) {
            return false;
          }
          if (register.bounds && !this._isLiveValue(register, value)) {
            const bounds = this._effectiveBounds(group.id, register);
            const [min, max] = bounds || [];
            if (Number.isFinite(min) && Number.isFinite(max) && (numeric < min || numeric > max)) {
              return false;
            }
          }
        }
        if (register.control === "enum") {
          const options = Object.keys(register.values || {}).map(String);
          if (!options.includes(String(value))) {
            return false;
          }
        }
        return true;
      });
  }

  _renderControl(register, groupId, bounds = register.bounds, enabled = true) {
    const editable = Boolean(register.writable && this._state?.map_readable);
    const pending = this._pendingGroups.has(groupId);
    // ``enabled`` is false for a setting that does not apply to the slot's
    // current mode (TOU charge vs discharge); it stays visible but disabled.
    const active = editable && enabled && !pending;
    const unit = register.unit
      ? `<span slot="end">${this._escape(register.unit)}</span>`
      : "";
    if (register.control === "enum") {
      // ha-select receives its options as a JS property in _syncControls.
      return `<ha-select ${active ? "" : "disabled"}></ha-select>`;
    }
    if (register.control === "switch") {
      // On/off registers use Home Assistant's native toggle.
      return `<ha-switch ${active ? "" : "disabled"}></ha-switch>`;
    }
    if (register.control === "time") {
      // ha-time-input is HA's native time selector (HH:MM fields).
      const warning = this._timeInvalid(register)
        ? `<span class="reg-warning">${this._escape(
            this._t("warningInvalidTime")
          )}</span>`
        : "";
      return `<ha-time-input ${
        active ? "" : "disabled"
      }></ha-time-input>${warning}`;
    }
    const [min, max, step] = bounds || [];
    const boundsAttributes = [
      min !== undefined ? `min="${min}"` : "",
      max !== undefined ? `max="${max}"` : "",
      step !== undefined ? `step="${step}"` : "",
    ]
      .filter(Boolean)
      .join(" ");
    const state = editable ? (active ? "" : "disabled") : "readonly";
    if (this._sliderEnabled(register, bounds)) {
      // Slider rows keep a compact read-only value next to the track: the
      // native tooltip only appears while dragging, and a second editable
      // number box for a percentage setting is redundant.
      return `<ha-slider labeled ${boundsAttributes} ${
        active ? "" : "disabled"
      }></ha-slider><span class="reg-slider-value"></span>`;
    }
    const type = register.control === "number" ? 'type="number"' : "";
    return `<ha-input ${type} ${boundsAttributes} ${state}>${unit}</ha-input>`;
  }

  _ensureTimeInput() {
    if (customElements.get("ha-time-input") || this._timeLoader) {
      return;
    }
    // ha-time-input lives in a lazily loaded chunk. An ha-selector wired to
    // the time selector pulls that chunk in so our own elements can upgrade.
    const loader = document.createElement("ha-selector");
    loader.selector = { time: {} };
    loader.hass = this.hass;
    loader.style.display = "none";
    this._timeLoader = loader;
    // Keep it outside _root: _render() replaces _root's innerHTML.
    this.shadowRoot.appendChild(loader);
    const check = () => {
      if (customElements.get("ha-time-input")) {
        loader.remove();
        this._timeLoader = null;
        this._syncControls();
        return;
      }
      setTimeout(check, 200);
    };
    setTimeout(check, 200);
  }

  _syncControls() {
    this._ensureTimeInput();
    const apply = (attempt = 0) => {
      let waiting = false;
      this._root
        .querySelectorAll(".reg-control[data-code]")
        .forEach((control) => {
          if (control.dataset.synced) {
            return;
          }
          const slider = control.querySelector("ha-slider");
          const time = control.querySelector("ha-time-input");
          if (
            (slider && !customElements.get("ha-slider")) ||
            (time && !customElements.get("ha-time-input"))
          ) {
            // These elements are loaded lazily; wait for the upgrade.
            waiting = true;
            return;
          }
          const value = control.getAttribute("data-value") || "";
          const toggle = control.querySelector("ha-switch");
          if (toggle) {
            toggle.checked = String(value) === "1";
          }
          const select = control.querySelector("ha-select");
          if (select) {
            const register = this._findRegister(
              control.dataset.group,
              control.dataset.code
            );
            const options = Object.keys(register?.values || {}).map((raw) => ({
              value: raw,
              label: this._enumLabel(register, raw),
            }));
            if (options.length) {
              select.options = options;
              select.value = options.some(
                (option) => String(option.value) === value
              )
                ? value
                : undefined;
            }
          }
          const input = control.querySelector("ha-input");
          if (input) {
            input.value = value;
            input.placeholder = value === "" ? "—" : "";
          }
          if (slider) {
            const numeric = Number(value);
            if (value !== "" && Number.isFinite(numeric)) {
              slider.value = numeric;
            }
          }
          const badge = control.querySelector(".reg-slider-value");
          if (badge) {
            badge.textContent = this._sliderText(
              this._findRegister(control.dataset.group, control.dataset.code),
              value
            );
          }
          if (time) {
            // Registers store 00:00–23:59; always show HH:MM (no AM/PM select)
            // regardless of the user's 12/24-hour UI preference.
            time.locale = { ...(this.hass?.locale || {}), time_format: "24" };
            if (value !== "") {
              time.value = this._normalizeTime(value);
            }
          }
          control.dataset.synced = "1";
        });
      if (waiting && attempt < 40) {
        setTimeout(() => apply(attempt + 1), 150);
      }
    };
    apply();
    requestAnimationFrame(() => apply());
    setTimeout(() => apply(), 250);
  }

  _bindEditing() {
    this._root
      .querySelectorAll("section.group > .group-header")
      .forEach((header) => {
        header.addEventListener("click", () => this._toggleGroup(header));
        header.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            this._toggleGroup(header);
          }
        });
      });

    this._root
      .querySelectorAll(".register-row[data-entity]")
      .forEach((row) => {
        row.addEventListener("click", (event) => {
          if (event.target.closest("ha-input, ha-select, ha-slider, ha-time-input, ha-switch")) {
            return;
          }
          this.dispatchEvent(
            new CustomEvent("hass-more-info", {
              detail: { entityId: row.dataset.entity },
              bubbles: true,
              composed: true,
            })
          );
        });
      });

    this._root
      .querySelectorAll(".reg-control[data-editable]")
      .forEach((control) => {
        const groupId = control.dataset.group;
        const code = control.dataset.code;
        const select = control.querySelector("ha-select");
        const input = control.querySelector("ha-input");
        const slider = control.querySelector("ha-slider");
        const time = control.querySelector("ha-time-input");
        const toggle = control.querySelector("ha-switch");
        const badge = control.querySelector(".reg-slider-value");
        const register = this._findRegister(groupId, code);
        const handle = (raw, clamp = true) => {
          let value = raw === undefined || raw === null ? "" : raw;
          const bounds =
            register?.control === "number"
              ? this._effectiveBounds(groupId, register)
              : null;
          if (
            clamp &&
            register?.control === "number" &&
            Array.isArray(bounds) &&
            String(value).trim() !== ""
          ) {
            const numeric = Number(value);
            if (Number.isFinite(numeric)) {
              const [min, max] = bounds;
              const clamped = Math.min(Math.max(numeric, min), max);
              if (clamped !== numeric) {
                value = String(clamped);
                this._notify(
                  this._t("noticeClamped", {
                    name: this._regName(register),
                    value: clamped,
                    min,
                    max,
                  }),
                  3000
                );
              }
            }
          }
          this._drafts[groupId] = this._drafts[groupId] || {};
          this._drafts[groupId][code] = value;
          if (select && select.value !== value) {
            select.value = value;
          }
          if (input && String(input.value ?? "") !== String(value)) {
            input.value = value;
          }
          if (time && this._normalizeTime(time.value) !== String(value)) {
            time.value = value;
          }
          if (toggle) {
            const on = String(value) === "1" || value === true;
            if (toggle.checked !== on) {
              toggle.checked = on;
            }
          }
          const numeric = Number(value);
          if (
            slider &&
            value !== "" &&
            Number.isFinite(numeric) &&
            slider.value !== numeric
          ) {
            slider.value = numeric;
          }
          if (badge) {
            badge.textContent = this._sliderText(register, value);
          }
          if (code === "charge_discharge_direction" || code === "backup_soc") {
            // The cutoff SoC range depends on the direction and the backup
            // reserve; refresh it as soon as either draft changes.
            this._syncCutoffControls();
          }
          if (code === this._state?.groups?.[groupId]?.count_register) {
            this._syncSlotVisibility(groupId);
          }
          if (
            (this._state?.groups?.[groupId]?.members || []).some(
              (item) => item.enabled_when?.code === code
            )
          ) {
            this._syncDependencyControls(groupId);
          }
          this._refreshApply(groupId);
        };
        select?.addEventListener("selected", (event) =>
          handle(event.detail?.value)
        );
        slider?.addEventListener("change", (event) => handle(event.target.value));
        // Keep the read-only value in step with the thumb during a drag; the
        // native tooltip disappears as soon as the pointer is released.
        slider?.addEventListener("input", (event) => {
          if (badge) {
            badge.textContent = this._sliderText(register, event.target.value);
          }
        });
        // Clamp only when the entry is committed: clamping each keystroke turns
        // a typed "60" (6 → 60) into "100" whenever the intermediate digit is
        // outside the bounds.
        input?.addEventListener("input", (event) =>
          handle(event.target.value, false)
        );
        input?.addEventListener("change", (event) => handle(event.target.value));
        toggle?.addEventListener("change", (event) =>
          handle(event.target.checked ? 1 : 0)
        );
        // ha-time-input reports "HH:MM:SS"; the register only holds HH:MM.
        time?.addEventListener("value-changed", (event) => {
          const raw = event.detail?.value ?? "";
          const normalized = this._normalizeTime(raw);
          const clamped = this._clampTime(raw);
          if (normalized && normalized !== clamped) {
            this._notify(
              this._t("noticeTimeClamped", { value: clamped }),
              3000
            );
          }
          handle(clamped);
        });
      });

    this._root.querySelectorAll(".group-apply").forEach((button) => {
      button.addEventListener("click", () => this._applyGroup(button.dataset.group));
    });

    this._syncAllSlotVisibility();
    this._syncAllDependencyControls();
    this._syncControls();
  }

  _refreshApply(groupId) {
    const group = this._state?.groups?.[groupId];
    const button = this._root.querySelector(
      `.group-apply[data-group="${groupId}"]`
    );
    if (!group || !button) {
      return;
    }
    const pending = this._pendingGroups.has(groupId);
    const valid = this._isValid(group);
    const dirty = this._isDirty(group);
    button.disabled = !valid || pending;
    const hint = button.parentElement?.querySelector(".group-hint");
    if (hint) {
      hint.textContent = this._groupHint(group, valid, dirty);
    }
  }

  async _applyGroup(groupId) {
    const group = this._state?.groups?.[groupId];
    if (!group || this._pendingGroups.has(groupId) || !this._state?.map_readable) {
      return;
    }
    const values = {};
    for (const register of group.members || []) {
      if (register.writable) {
        values[register.code] = this._draftValue(groupId, register);
      }
    }
    const groupLabel = this._groupLabel(group);
    if (!(await this._confirmGroupWrite(groupLabel))) {
      return;
    }
    this._pendingGroups.add(groupId);
    this._notice = null;
    this._render();
    try {
      this._state = await this._callWS("conow_local/set_panel_group", {
        device_id: this._deviceId,
        group_id: groupId,
        values,
      });
      this._drafts[groupId] = {};
      this._notice = {
        ok: true,
        text: this._t("noticeApplied", { group: groupLabel }),
      };
    } catch (err) {
      // The backend tags three Conow-specific refusals: 4 = another client
      // holds the device, 5 = the verification code needs refreshing, 6 = the
      // RTU external-control switch is off in the app.
      const noticeKey = {
        device_busy: "noticeDeviceBusy",
        verification_required: "noticeVerificationRequired",
        external_control_disabled: "noticeExternalControl",
        write_rejected: "noticeRejected",
      }[err.code] || "noticeFailed";
      this._notice = {
        ok: false,
        text: this._t(noticeKey, {
          group: groupLabel,
          error: err.message || String(err),
        }),
      };
    } finally {
      this._pendingGroups.delete(groupId);
      this._render();
    }
  }

  _confirmGroupWrite(groupLabel) {
    return new Promise((resolve) => {
      const backdrop = document.createElement("div");
      backdrop.className = "modal-backdrop";
      backdrop.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true">
          <h2>${this._escape(this._t("confirmWriteTitle"))}</h2>
          <p class="modal-message">${this._escape(
            this._t("confirmWrite", { group: groupLabel })
          )}</p>
          <div class="modal-actions">
            <button type="button" class="modal-cancel">${this._escape(
              this._t("actionCancel")
            )}</button>
            <button type="button" class="modal-confirm">${this._escape(
              this._t("actionConfirm")
            )}</button>
          </div>
        </div>`;
      const finish = (confirmed) => {
        document.removeEventListener("keydown", onKey, true);
        backdrop.remove();
        resolve(confirmed);
      };
      const onKey = (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          finish(false);
        }
      };
      backdrop
        .querySelector(".modal-cancel")
        .addEventListener("click", () => finish(false));
      backdrop
        .querySelector(".modal-confirm")
        .addEventListener("click", () => finish(true));
      backdrop.addEventListener("click", (event) => {
        if (event.target === backdrop) {
          finish(false);
        }
      });
      document.addEventListener("keydown", onKey, true);
      this.shadowRoot.appendChild(backdrop);
      backdrop.querySelector(".modal-confirm").focus();
    });
  }

  _renderGroup(group) {
    const writable = (group.members || []).filter((item) => item.writable);
    const rows = this._renderMemberRows(group);
    const hasWritable = writable.length > 0;
    // In the read-only view the editable rows are hidden, so hide the footer
    // too (it would otherwise validate/stage registers the user cannot see).
    const editableHere = this._accessFilter !== "ro";
    let footer = "";
    if (hasWritable && this._state?.map_readable && editableHere) {
      const pending = this._pendingGroups.has(group.id);
      const valid = this._isValid(group);
      const dirty = this._isDirty(group);
      const hint = this._groupHint(group, valid, dirty);
      footer = `
        <div class="group-footer">
          <span class="group-hint">${hint}</span>
          <button type="button" class="group-apply" data-group="${group.id}"
            ${valid && !pending ? "" : "disabled"}>
            ${pending ? this._t("actionApplying") : this._t("actionApply")}
          </button>
        </div>
      `;
    }
    const collapsed = this._collapsed.has(group.id);
    return `
      <section class="group${collapsed ? " collapsed" : ""}" data-group="${this._escape(
        group.id
      )}">
        <div class="group-header" role="button" tabindex="0"
          aria-expanded="${collapsed ? "false" : "true"}"
          title="${this._escape(
            this._t(collapsed ? "titleExpandGroup" : "titleCollapseGroup")
          )}">
          <ha-icon icon="${this._escape(group.icon || "mdi:view-grid-outline")}"></ha-icon>
          <span class="group-title">${this._escape(
            this._groupLabel(group)
          )}</span>
          <ha-icon class="group-toggle" icon="mdi:chevron-down"></ha-icon>
        </div>
        <div class="group-body">
          ${rows}
          ${footer}
        </div>
      </section>
    `;
  }

  _groupIdForEntity(code) {
    if (!code) {
      return null;
    }
    const groups = Object.values(
      this._state?.groups || this._mapState?.groups || {}
    );
    const group = groups.find((item) =>
      (item.members || []).some((member) => member.code === code)
    );
    return group ? group.id : null;
  }

  _toggleGroup(header) {
    const section = header.closest("section.group");
    if (!section) {
      return;
    }
    const collapsed = section.classList.toggle("collapsed");
    const id = section.dataset.group;
    if (collapsed) {
      this._collapsed.add(id);
    } else {
      this._collapsed.delete(id);
    }
    header.setAttribute("aria-expanded", String(!collapsed));
  }

  _mapMismatchHint() {
    if (!this._state) {
      return "";
    }
    // Both maps are grouped now; only warn when the device sent no groups.
    if (Object.keys(this._state.groups || {}).length) {
      return this._state.map_readable === false
        ? this._mapUnreadableHint()
        : "";
    }
    if (this._state.map_version === 1) {
      const firmware = this._state.firmware_version || this._t("unknownFirmware");
      const minimum = this._state.min_firmware || "1.2";
      return `<div class="hint">${this._t("mapMismatchV1", {
        firmware: this._escape(firmware),
        minimum: this._escape(minimum),
      })}</div>`;
    }
    if (this._state.map_readable !== false) {
      return "";
    }
    return this._mapUnreadableHint();
  }

  // Direct-TCP links also depend on the challenge code, so the hint names it.
  _mapUnreadableHint() {
    if (this._state?.read_error === "device_busy") {
      return `<div class="hint">${this._t("mapUnreadableDeviceBusy")}</div>`;
    }
    if (this._state?.read_error === "verification_required") {
      return `<div class="hint">${this._t(
        "mapUnreadableVerificationRequired"
      )}</div>`;
    }
    if (this._state?.read_error === "external_control_disabled") {
      return `<div class="hint">${this._t(
        "mapUnreadableExternalControl"
      )}</div>`;
    }
    const key =
      this._state?.mode === "tcp_direct"
        ? "mapUnreadableTcpDirect"
        : "mapUnreadable";
    return `<div class="hint">${this._t(key)}</div>`;
  }

  _renderGroups() {
    const groups = Object.values(this._state?.groups || this._mapState?.groups || {});
    const visible = groups.filter((group) => {
      const members = group.members || [];
      if (this._groupFilter && group.id !== this._groupFilter) {
        return false;
      }
      if (
        this._entityFilter &&
        !members.some((item) => item.code === this._entityFilter)
      ) {
        return false;
      }
      return members.some((item) => this._accessMatches(item));
    });
    if (!visible.length) {
      return `<div class="empty">${this._escape(
        this._t("emptyNoGroups")
      )}</div>`;
    }
    return visible.map((group) => this._renderGroup(group)).join("");
  }

  // Banners live in the frozen header, above the scrolled group list.
  _renderHeaderNotices() {
    const notice = this._notice
      ? `<div class="notice ${this._notice.ok ? "" : "error"}">${this._escape(
          this._notice.text
        )}</div>`
      : "";
    return this._mapMismatchHint() + notice;
  }

  _setRefreshSpinning(on) {
    const button = this._root.querySelector("#refresh-btn");
    if (button) {
      button.classList.toggle("spinning", Boolean(on));
    }
  }

  _refreshGroupsBody() {
    // Re-render only the group list so filters don't reset the toolbar/device.
    const host = this._root.querySelector("#groups-body");
    if (!host) {
      return;
    }
    host.innerHTML = this._renderGroups();
    this._bindEditing();
  }

  _bindEvents() {
    this._bindToolbar();
    this._bindEditing();
  }

  _bindToolbar() {
    const bind = (field, handler) => {
      const combo = this._root.querySelector(`.combo[data-field="${field}"]`);
      if (combo) {
        this._bindCombo(combo, handler);
      }
    };

    bind("device", (value) => {
      this._deviceId = value || null;
      this._state = null;
      this._drafts = {};
      this._pendingGroups.clear();
      this._notice = null;
      this._groupFilter = "";
      this._entityFilter = "";
      this._syncUrl();
      if (this._deviceId) {
        this._loadFunctions();
      } else {
        this._render();
      }
    });

    bind("group", (value) => {
      this._groupFilter = value || "";
      // Show the group the user just picked, even if it was collapsed.
      if (this._groupFilter) {
        this._collapsed.delete(this._groupFilter);
      }
      // A new group narrows the entity list; drop an entity from another group.
      this._refreshToolbar();
      this._refreshGroupsBody();
    });

    bind("entity", (value) => {
      this._entityFilter = value || "";
      const groupId = this._groupIdForEntity(this._entityFilter);
      if (groupId) {
        this._collapsed.delete(groupId);
      }
      this._refreshGroupsBody();
    });

    bind("access", (value) => {
      this._accessFilter = value || "all";
      this._refreshToolbar();
      this._refreshGroupsBody();
    });

    bind("poll", async (value) => {
      const deviceId = this._deviceId;
      const seconds = Number(value);
      if (!deviceId || !Number.isFinite(seconds)) {
        return;
      }
      try {
        await this._callWS("conow_local/set_poll_interval", {
          device_id: deviceId,
          seconds,
        });
        const device = this._devices.find((item) => item.device_id === deviceId);
        if (device) {
          device.poll_interval = seconds;
        }
        if (this._state) {
          this._state.poll_interval = seconds;
        }
        this._notice = {
          ok: true,
          text: this._t("noticePollInterval", { seconds }),
        };
      } catch (err) {
        this._notice = {
          ok: false,
          text: this._t("noticePollIntervalFailed", {
            error: err.message || String(err),
          }),
        };
      }
      this._render();
    });

    const refresh = this._root.querySelector("#refresh-btn");
    if (refresh) {
      refresh.addEventListener("click", () => this._loadFunctions());
    }
  }

  _bindCombo(combo, onSelect) {
    const input = combo.querySelector(".combo-input");
    const menu = combo.querySelector(".combo-menu");
    const empty = menu.querySelector(".combo-empty");
    const allOptions = () => [...menu.querySelectorAll(".combo-option")];
    const shownOptions = () =>
      allOptions().filter((option) => option.style.display !== "none");

    const choose = (option) => {
      combo.dataset.value = option.dataset.value;
      combo.dataset.label = option.dataset.label;
      input.value = option.dataset.label;
      allOptions().forEach((item) => item.classList.remove("selected"));
      option.classList.add("selected");
      menu.hidden = true;
      onSelect(option.dataset.value);
    };

    const filterMenu = (rawQuery) => {
      const query = String(rawQuery ?? input.value).trim().toLowerCase();
      let visible = 0;
      allOptions().forEach((option) => {
        const hit =
          !query ||
          option.dataset.label.toLowerCase().includes(query) ||
          option.dataset.value.toLowerCase().includes(query);
        option.style.display = hit ? "" : "none";
        option.classList.remove("active");
        if (hit) {
          visible += 1;
        }
      });
      // Hide section headings that lost all their options.
      menu.querySelectorAll(".combo-heading").forEach((heading) => {
        let node = heading.nextElementSibling;
        let any = false;
        while (node && !node.classList.contains("combo-heading")) {
          if (
            node.classList.contains("combo-option") &&
            node.style.display !== "none"
          ) {
            any = true;
            break;
          }
          node = node.nextElementSibling;
        }
        heading.style.display = any ? "" : "none";
      });
      empty.hidden = visible > 0;
      const selected = shownOptions().find(
        (option) => option.dataset.value === combo.dataset.value
      );
      if (selected) {
        selected.classList.add("active");
        selected.scrollIntoView({ block: "nearest" });
      }
    };

    const open = () => {
      // Only one menu is open at a time.
      this._root.querySelectorAll(".combo-menu").forEach((other) => {
        if (other !== menu) {
          other.hidden = true;
        }
      });
      // Focusing a combo shows every option; a typed query filters.
      filterMenu(input.value === combo.dataset.label ? "" : input.value);
      menu.hidden = false;
    };

    const close = () => {
      menu.hidden = true;
      input.value = combo.dataset.label;
    };

    input.addEventListener("focus", () => {
      input.select();
      open();
    });
    input.addEventListener("input", () => {
      filterMenu();
      if (menu.hidden) {
        menu.hidden = false;
      }
    });
    input.addEventListener("keydown", (event) => {
      const items = shownOptions();
      let index = items.findIndex((item) => item.classList.contains("active"));
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (menu.hidden) {
          open();
          return;
        }
        const delta = event.key === "ArrowDown" ? 1 : -1;
        index = index < 0 ? 0 : index + delta;
        index = Math.max(0, Math.min(items.length - 1, index));
        items.forEach((item) => item.classList.remove("active"));
        if (items[index]) {
          items[index].classList.add("active");
          items[index].scrollIntoView({ block: "nearest" });
        }
      } else if (event.key === "Enter") {
        if (!menu.hidden && items[index < 0 ? 0 : index]) {
          event.preventDefault();
          choose(items[index < 0 ? 0 : index]);
        }
      } else if (event.key === "Escape") {
        close();
        input.blur();
      }
    });
    input.addEventListener("blur", () => {
      // Let a click on an option land before restoring the label.
      setTimeout(() => {
        if (!menu.hidden) {
          close();
        }
      }, 140);
    });
    // Keep focus in the search box while an option is pressed.
    menu.addEventListener("mousedown", (event) => {
      if (event.target.closest(".combo-option")) {
        event.preventDefault();
      }
    });
    menu.addEventListener("click", (event) => {
      const option = event.target.closest(".combo-option");
      if (option) {
        choose(option);
      }
    });
  }

  _combo(field, placeholder, items, selectedValue) {
    const itemsHtml = items
      .map((item) =>
        item.heading
          ? `<div class="combo-heading">${this._escape(item.heading)}</div>`
          : `<div class="combo-option${
              item.value === selectedValue ? " selected" : ""
            }" data-value="${this._escape(item.value)}" data-label="${this._escape(
              item.label
            )}" title="${this._escape(item.label)}">${this._escape(item.label)}</div>`
      )
      .join("");
    const selected = items.find(
      (item) => !item.heading && item.value === selectedValue
    );
    const label = selected ? selected.label : placeholder;
    return `
      <div class="combo" data-field="${field}" data-value="${this._escape(
        selectedValue || ""
      )}" data-label="${this._escape(label)}">
        <input class="combo-input" type="text" value="${this._escape(
          label
        )}" placeholder="${this._escape(
          placeholder
        )}" autocomplete="off" spellcheck="false" aria-label="${this._escape(
          placeholder
        )}" />
        <ha-icon icon="mdi:chevron-down"></ha-icon>
        <div class="combo-menu" hidden>
          ${itemsHtml}
          <div class="combo-empty" hidden>${this._escape(
            this._t("comboNoMatch")
          )}</div>
        </div>
      </div>
    `;
  }

  _refreshToolbar() {
    const toolbar = this._root.querySelector("#toolbar");
    if (!toolbar) {
      return;
    }
    toolbar.innerHTML = this._renderToolbar();
    this._bindToolbar();
  }

  _pollIntervalFor(deviceId) {
    const device = this._devices.find((item) => item.device_id === deviceId);
    const seconds = Number(device?.poll_interval ?? this._state?.poll_interval);
    return Number.isFinite(seconds) && seconds > 0 ? seconds : 30;
  }

  _renderToolbar() {
    const groupsSource = this._state?.groups || this._mapState?.groups || {};
    const groups = Object.values(groupsSource);
    if (
      this._groupFilter &&
      !groups.some((group) => group.id === this._groupFilter)
    ) {
      this._groupFilter = "";
    }

    const deviceItems = this._devices.map((device) => {
      const rawMode = String(device.mode || "");
      const mode =
        rawMode === "tcp_direct"
          ? this._t("modeTcpDirect")
          : rawMode.toUpperCase();
      // Unloaded TCP entries are read directly over TCP, so "not loaded" would
      // contradict the reachability shown once the read succeeds; only RTU
      // entries depend on the integration being loaded.
      const state = device.online
        ? ""
        : rawMode.startsWith("tcp") && !device.loaded
          ? ""
          : device.loaded
            ? this._t("stateOffline")
            : this._t("stateUnloaded");
      return {
        value: device.device_id,
        label: `${device.name}${mode ? ` · ${mode}` : ""}${state}`,
      };
    });

    const groupItems = [
      { value: "", label: this._t("allGroups") },
      ...groups.map((group) => ({
        value: group.id,
        label: this._groupLabel(group),
      })),
    ];

    // Entity choices follow the group and read/write filters; without a
    // group they are grouped by their section label.
    const entityCodes = new Set();
    const entityItems = [{ value: "", label: this._t("allEntities") }];
    groups
      .filter((group) => !this._groupFilter || group.id === this._groupFilter)
      .forEach((group) => {
        const members = (group.members || []).filter((item) =>
          this._accessMatches(item)
        );
        members.forEach((item) => entityCodes.add(item.code));
        if (!members.length) {
          return;
        }
        if (!this._groupFilter) {
          entityItems.push({ heading: this._groupLabel(group) });
        }
        members.forEach((item) => {
          entityItems.push({
            value: item.code,
            label: this._t("entityOption", {
              name: this._regName(item),
              code: item.code,
            }),
          });
        });
      });
    if (this._entityFilter && !entityCodes.has(this._entityFilter)) {
      this._entityFilter = "";
    }

    const accessItems = [
      { value: "all", label: this._t("accessAll") },
      { value: "rw", label: this._t("accessRw") },
      { value: "ro", label: this._t("accessRo") },
    ];

    // Polling is stored per device, so the dropdown only makes sense once a
    // device is selected.
    const pollItems = POLL_INTERVAL_OPTIONS.map((seconds) => ({
      value: String(seconds),
      label: this._t("pollIntervalOption", { seconds }),
    }));

    return `
      ${this._combo("device", this._t("selectDevice"), deviceItems, this._deviceId || "")}
      ${this._combo("group", this._t("allGroups"), groupItems, this._groupFilter)}
      ${this._combo("entity", this._t("allEntities"), entityItems, this._entityFilter)}
      ${this._combo("access", this._t("accessAll"), accessItems, this._accessFilter)}
      ${
        this._deviceId
          ? this._combo(
              "poll",
              this._t("pollInterval"),
              pollItems,
              String(this._pollIntervalFor(this._deviceId))
            )
          : ""
      }
      <button id="refresh-btn" class="icon-btn${this._loading ? " spinning" : ""}"
        type="button" title="${this._escape(
          this._t("refresh")
        )}" aria-label="${this._escape(this._t("refresh"))}">
        <ha-icon icon="mdi:refresh"></ha-icon>
      </button>
    `;
  }

  _render() {
    const map = this._state?.map || this._mapState?.map || {};
    const groupsSource = this._state?.groups || this._mapState?.groups || {};
    const groupCount = Object.keys(groupsSource).length;

    let body = "";
    if (this._loading) {
      body = `<div class="loading">${this._escape(
        this._t("loadingRegisters")
      )}</div>`;
    } else if (this._error) {
      body = `<div class="error">${this._escape(this._error)}</div>`;
    } else if (!groupCount) {
      body = `<div class="loading">${this._escape(
        this._t("loadingMap")
      )}</div>`;
    } else {
      body = this._renderGroups();
    }

    this._root.innerHTML = `
      <div class="page-header">
        <h1>${this._escape(this._t("title"))}</h1>
        <div class="toolbar" id="toolbar">${this._renderToolbar()}</div>
        <div id="page-notices">${this._renderHeaderNotices()}</div>
      </div>
      <div id="groups-body">${body}</div>
    `;
    this._bindEvents();
  }
}

if (!customElements.get("conow-local-panel")) {
  customElements.define("conow-local-panel", ConowLocalPanel);
}
