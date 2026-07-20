import { assertOfflineStyle, BLANK_OFFLINE_STYLE } from './BlankOfflineStyle';

export const BASEMAP_REGISTRY = Object.freeze([
  Object.freeze({
    id: 'skywatcher-blank-offline',
    label: 'Offline diagnostic blank',
    configured: true,
    offline: true,
    attribution: 'Skywatcher-PR diagnostic console · MapLibre GL JS',
    style: BLANK_OFFLINE_STYLE,
  }),
]);

export function validateBasemapRegistry(registry = BASEMAP_REGISTRY) {
  const ids = new Set();
  registry.forEach((entry) => {
    if (!entry?.id || ids.has(entry.id)) throw new Error(`invalid or duplicate basemap id: ${entry?.id || '<missing>'}`);
    ids.add(entry.id);
    if (!entry.attribution?.trim()) throw new Error(`basemap ${entry.id} must declare attribution`);
    if (entry.configured && !entry.style) throw new Error(`configured basemap ${entry.id} must include a style`);
    if (entry.offline && entry.style) assertOfflineStyle(entry.style);
  });
  return true;
}

export function getBasemap(id, registry = BASEMAP_REGISTRY) {
  validateBasemapRegistry(registry);
  return registry.find((entry) => entry.id === id) || registry[0];
}
