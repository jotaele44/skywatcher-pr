export const CONSOLE_FEATURE_FLAG = 'VITE_SKYWATCHER_CONSOLE_ENABLED';

export const DEFAULT_VIEWPORT = Object.freeze({
  longitude: -66.45,
  latitude: 18.22,
  zoom: 7,
  bearing: 0,
  pitch: 0,
});

export const DEFAULT_MAX_BOUNDS = Object.freeze([
  [-69.5, 16.5],
  [-63.0, 20.5],
]);

export const MAP_CAPABILITY_IDS = Object.freeze({
  navigation: 'map_navigation',
  geolocation: 'geolocation',
  basemaps: 'basemap_controls',
});

const moduleMeta = /** @type {{env?: Record<string, unknown>}} */ (import.meta);

export function isConsoleEnabled(env = moduleMeta.env || {}) {
  return String(env?.[CONSOLE_FEATURE_FLAG] ?? 'true').toLowerCase() !== 'false';
}

