export const VIEWPORT_STORAGE_KEY = "skywatcher.console.viewport.v1";

export const DEFAULT_VIEWPORT = Object.freeze({
  center: [-66.25, 18.22],
  zoom: 7.2,
  bearing: 0,
  pitch: 0,
});

const finite = (value, fallback) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

export function normalizeViewport(value = {}) {
  const center = Array.isArray(value.center) ? value.center : DEFAULT_VIEWPORT.center;
  return {
    center: [
      clamp(finite(center[0], DEFAULT_VIEWPORT.center[0]), -180, 180),
      clamp(finite(center[1], DEFAULT_VIEWPORT.center[1]), -85, 85),
    ],
    zoom: clamp(finite(value.zoom, DEFAULT_VIEWPORT.zoom), 0, 24),
    bearing: ((finite(value.bearing, DEFAULT_VIEWPORT.bearing) % 360) + 360) % 360,
    pitch: clamp(finite(value.pitch, DEFAULT_VIEWPORT.pitch), 0, 85),
  };
}

export function viewportFromMap(map) {
  const center = map.getCenter();
  return normalizeViewport({
    center: [center.lng, center.lat],
    zoom: map.getZoom(),
    bearing: map.getBearing(),
    pitch: map.getPitch(),
  });
}

export function loadViewport(storage = globalThis?.localStorage) {
  if (!storage) return { ...DEFAULT_VIEWPORT, center: [...DEFAULT_VIEWPORT.center] };
  try {
    const raw = storage.getItem(VIEWPORT_STORAGE_KEY);
    return raw ? normalizeViewport(JSON.parse(raw)) : normalizeViewport(DEFAULT_VIEWPORT);
  } catch {
    return normalizeViewport(DEFAULT_VIEWPORT);
  }
}

export function saveViewport(viewport, storage = globalThis?.localStorage) {
  const normalized = normalizeViewport(viewport);
  if (storage) storage.setItem(VIEWPORT_STORAGE_KEY, JSON.stringify(normalized));
  return normalized;
}
