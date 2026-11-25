// Sky Target Finder favorites, kept in this browser's localStorage.
//
// Each entry stores the target id plus the time-independent part of the last-known
// target object, so the Favorites tab can still list a favorite when it cannot be
// re-resolved (for example a satellite whose elements are no longer frozen
// locally). Live altitude and visibility are always re-fetched, never stored.
// Every storage access is guarded: private windows, disabled storage and quota
// errors degrade to an in-memory list instead of breaking the page.

export const FAVORITES_STORAGE_KEY = "skywatcher.sky-favorites.v1";

const SNAPSHOT_FIELDS = [
  "id",
  "kind",
  "designation",
  "long_designation",
  "name",
  "display",
  "aliases",
  "object_type",
  "constellation",
  "magnitude",
  "size_arcmin",
  "ra_j2000_deg",
  "dec_j2000_deg",
  "filter_hint",
];

const SEARCH_KIND = {
  star: "star",
  messier: "messier",
  caldwell: "caldwell",
  planet: "solar_system",
  moon: "solar_system",
  sun: "solar_system",
  satellite: "satellite",
};

function getStorage() {
  try {
    return typeof window !== "undefined" && window.localStorage ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function favoriteSnapshot(target) {
  const snapshot = {};
  for (const field of SNAPSHOT_FIELDS) {
    if (target?.[field] !== undefined) snapshot[field] = target[field];
  }
  if (!snapshot.display) snapshot.display = snapshot.designation || snapshot.id;
  return snapshot;
}

export function loadFavorites() {
  try {
    const storage = getStorage();
    const raw = storage ? storage.getItem(FAVORITES_STORAGE_KEY) : null;
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    const items = Array.isArray(parsed?.items) ? parsed.items : [];
    const seen = new Set();
    const favorites = [];
    for (const item of items) {
      if (!item || typeof item.id !== "string" || !item.id || seen.has(item.id)) continue;
      seen.add(item.id);
      favorites.push(favoriteSnapshot(item));
    }
    return favorites;
  } catch {
    return [];
  }
}

// Returns true when the list was persisted, false when storage is unavailable.
export function saveFavorites(favorites) {
  try {
    const storage = getStorage();
    if (!storage) return false;
    storage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify({ version: 1, items: favorites }));
    return true;
  } catch {
    return false;
  }
}

export function isFavorite(favorites, id) {
  return favorites.some((favorite) => favorite.id === id);
}

// Pure: returns the new list with `target` added (at the front) or removed.
export function toggleFavorite(favorites, target) {
  if (!target?.id) return favorites;
  if (isFavorite(favorites, target.id)) {
    return favorites.filter((favorite) => favorite.id !== target.id);
  }
  return [favoriteSnapshot(target), ...favorites];
}

// The targets-search query that re-resolves a stored favorite to a live target:
// satellites by NORAD id, everything else by its designation within its own kind.
export function favoriteLookup(favorite) {
  const kind = SEARCH_KIND[favorite?.kind] || "all";
  const norad = /^satellite:norad:(\d+)$/.exec(favorite?.id || "");
  const q = norad ? norad[1] : favorite?.designation || favorite?.display || "";
  return { q, kind };
}
