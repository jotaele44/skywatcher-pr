// Persisted, per-browser preferences for the /live map (non-evidentiary UI
// state, stored in localStorage like the console viewport).
import { DEFAULT_BASE_LAYER, OVERLAYS, findBaseLayer, validateCustomTemplate } from "./sourceCatalog.js";
import { UNIT_SYSTEMS } from "./aircraftModel.js";

export const SETTINGS_STORAGE_KEY = "skywatcher.live.settings.v1";

export const PUERTO_RICO_HOME = Object.freeze({ center: [-66.45, 18.22], zoom: 7.4 });

export const DEFAULT_SETTINGS = Object.freeze({
  baseLayer: DEFAULT_BASE_LAYER,
  overlays: [],
  features: { aircraftWebGL: true, aircraftPositions: true, aircraftTrails: true, yourPosition: true, rangeRings: true },
  units: "nautical",
  mapDim: true,
  mapDimAmount: 0.45,
  rangeRings: [100, 150, 200],
  home: PUERTO_RICO_HOME,
  refreshS: 5,
  labels: false,
  extendedLabels: false,
  trackLabels: false,
  customTemplate: "",
  timeZone: "",
});

const clampNumber = (value, min, max, fallback) => {
  const n = Number(value);
  return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
};

export function normalizeSettings(value = {}) {
  const overlayIds = new Set(OVERLAYS.map((entry) => entry.id));
  const customTemplate = typeof value.customTemplate === "string" && !validateCustomTemplate(value.customTemplate)
    ? value.customTemplate.trim()
    : "";
  let baseLayer = typeof value.baseLayer === "string" ? value.baseLayer : DEFAULT_SETTINGS.baseLayer;
  if (baseLayer === "custom_tiles" ? !customTemplate : !findBaseLayer(baseLayer)) baseLayer = DEFAULT_SETTINGS.baseLayer;
  const home = value.home && Array.isArray(value.home.center) ? {
    center: [clampNumber(value.home.center[0], -180, 180, PUERTO_RICO_HOME.center[0]), clampNumber(value.home.center[1], -85, 85, PUERTO_RICO_HOME.center[1])],
    zoom: clampNumber(value.home.zoom, 1, 18, PUERTO_RICO_HOME.zoom),
  } : { ...PUERTO_RICO_HOME, center: [...PUERTO_RICO_HOME.center] };
  const rings = Array.isArray(value.rangeRings)
    ? value.rangeRings.map(Number).filter((n) => Number.isFinite(n) && n > 0 && n <= 2000).slice(0, 8)
    : [...DEFAULT_SETTINGS.rangeRings];
  return {
    baseLayer,
    overlays: Array.isArray(value.overlays) ? [...new Set(value.overlays.filter((id) => overlayIds.has(id)))] : [],
    features: { ...DEFAULT_SETTINGS.features, ...Object.fromEntries(Object.entries(value.features || {}).map(([k, v]) => [k, Boolean(v)])) },
    units: UNIT_SYSTEMS[value.units] ? value.units : DEFAULT_SETTINGS.units,
    mapDim: value.mapDim === undefined ? DEFAULT_SETTINGS.mapDim : Boolean(value.mapDim),
    mapDimAmount: clampNumber(value.mapDimAmount, 0, 0.9, DEFAULT_SETTINGS.mapDimAmount),
    rangeRings: rings,
    home,
    refreshS: clampNumber(value.refreshS, 2, 60, DEFAULT_SETTINGS.refreshS),
    labels: Boolean(value.labels),
    extendedLabels: Boolean(value.extendedLabels),
    trackLabels: Boolean(value.trackLabels),
    customTemplate,
    timeZone: typeof value.timeZone === "string" ? value.timeZone : "",
  };
}

export function loadSettings(storage = globalThis?.localStorage) {
  try {
    const raw = storage?.getItem(SETTINGS_STORAGE_KEY);
    return normalizeSettings(raw ? JSON.parse(raw) : {});
  } catch {
    return normalizeSettings({});
  }
}

export function saveSettings(settings, storage = globalThis?.localStorage) {
  const normalized = normalizeSettings(settings);
  try {
    storage?.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(normalized));
  } catch {
    // Private mode / blocked storage: settings stay in memory for this visit.
  }
  return normalized;
}

export function browserTimeZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
