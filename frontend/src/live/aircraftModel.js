// Aircraft normalization, styling and filtering for the /live map.
// Pure functions only (no DOM, no MapLibre) so they run under node --test.

// Altitude → hue stops and hue → lightness stops of the tar1090 colour scale,
// so altitude bands read the same as on the adsb.lol map.
const HUE_STOPS = [
  [0, 20], [2000, 32.5], [4000, 43], [6000, 54], [8000, 72], [9000, 85],
  [11000, 140], [40000, 300], [51000, 360],
];
const LIGHTNESS_STOPS = [
  [0, 53], [20, 50], [32, 54], [40, 52], [46, 51], [50, 46], [60, 43], [80, 41],
  [100, 41], [120, 41], [140, 41], [160, 40], [180, 40], [190, 44], [198, 50],
  [200, 58], [220, 58], [240, 58], [255, 55], [266, 55], [270, 58], [280, 58],
  [290, 47], [300, 43], [310, 48], [320, 48], [340, 52], [360, 53],
];

function interpolate(stops, value) {
  if (value <= stops[0][0]) return stops[0][1];
  for (let i = 1; i < stops.length; i += 1) {
    const [x1, y1] = stops[i];
    if (value <= x1) {
      const [x0, y0] = stops[i - 1];
      return y0 + ((y1 - y0) * (value - x0)) / (x1 - x0);
    }
  }
  return stops[stops.length - 1][1];
}

export function altitudeHsl(alt) {
  if (alt === "ground") return { h: 220, s: 0, l: 30 };
  if (typeof alt !== "number" || !Number.isFinite(alt)) return { h: 0, s: 0, l: 75 };
  const h = interpolate(HUE_STOPS, alt);
  return { h: Math.round(h * 10) / 10, s: 88, l: Math.round(interpolate(LIGHTNESS_STOPS, h) * 10) / 10 };
}

export function altitudeColor(alt) {
  const { h, s, l } = altitudeHsl(alt);
  return `hsl(${h}, ${s}%, ${l}%)`;
}

// ── shapes ──────────────────────────────────────────────────────────────────
const HELICOPTER_TYPES = new Set([
  "A109", "A119", "A139", "A169", "AS32", "AS50", "AS55", "AS65", "B06", "B105", "B212", "B407",
  "B412", "B429", "B505", "EC20", "EC25", "EC30", "EC35", "EC45", "EC55", "EC75", "H160", "H47",
  "H53", "H60", "H64", "MI8", "R22", "R44", "R66", "S61", "S70", "S76", "S92", "UH1", "V22",
]);
const HEAVY_TYPES = /^(A3[3-5]\d|A38\d|A34\d|B74\w|B76\w|B77\w|B78\w|MD11|DC10|C17|C5M|IL76|A400|K35R|KC10|E3TF|E3CF|B52|AN12|AN22|A124)$/;
const LIGHT_PROP = /^(C1[5-9]\d|C18\d|C20\d|C21\d|PA\d\d|P28\w|SR2\d|DA4\d|BE3\d|BE9\w|M20\w|C68A|PC12|C208|BN2\w|DHC\d|AT\d\d|SH36|SW4)$/;

export const SHAPES = Object.freeze([
  "airliner", "heavy", "jet_small", "prop", "helicopter", "glider", "balloon", "uav", "ground", "unknown",
]);

export function shapeFor(ac = {}) {
  const category = String(ac.category || "").toUpperCase();
  const type = String(ac.t || ac.type || "").toUpperCase();
  if (category === "A7" || HELICOPTER_TYPES.has(type)) return "helicopter";
  if (category === "B2") return "balloon";
  if (category === "B1" || category === "B4") return "glider";
  if (category === "B6") return "uav";
  if (category === "C1" || category === "C2" || category === "C3") return "ground";
  if (category === "A5" || HEAVY_TYPES.test(type)) return "heavy";
  if (category === "A1" || LIGHT_PROP.test(type)) return "prop";
  if (category === "A2" || category === "A6") return "jet_small";
  if (category === "A3" || category === "A4" || type) return "airliner";
  return "unknown";
}

// ── normalization ───────────────────────────────────────────────────────────
const num = (value) => (typeof value === "number" && Number.isFinite(value) ? value : null);

export function isMilitary(ac = {}) {
  return Boolean(Number(ac.dbFlags || 0) & 1);
}

export function normalizeAircraft(raw = {}, nowMs = Date.now()) {
  const hex = String(raw.hex || "").toLowerCase();
  const lat = num(raw.lat ?? raw.lastPosition?.lat);
  const lon = num(raw.lon ?? raw.lastPosition?.lon);
  const alt = raw.alt_baro === "ground" ? "ground" : num(raw.alt_baro ?? raw.alt_geom);
  return {
    hex,
    flight: String(raw.flight || "").trim() || null,
    registration: raw.r || null,
    type: raw.t || null,
    description: raw.desc || null,
    operator: raw.ownOp || null,
    category: raw.category || null,
    lat,
    lon,
    alt_baro: alt,
    alt_geom: num(raw.alt_geom),
    gs: num(raw.gs),
    track: num(raw.track ?? raw.true_heading ?? raw.mag_heading),
    baro_rate: num(raw.baro_rate ?? raw.geom_rate),
    squawk: raw.squawk || null,
    emergency: raw.emergency && raw.emergency !== "none" ? raw.emergency : null,
    source_type: raw.type || null,
    military: isMilitary(raw),
    seen: num(raw.seen),
    seen_pos: num(raw.seen_pos),
    rssi: num(raw.rssi),
    messages: num(raw.messages),
    outside_view: Boolean(raw.outside_view),
    updated_ms: nowMs - (num(raw.seen_pos) ?? 0) * 1000,
    shape: shapeFor(raw),
  };
}

// ── units ───────────────────────────────────────────────────────────────────
export const UNIT_SYSTEMS = Object.freeze({
  nautical: { altitude: "ft", speed: "kt", distance: "nm", scale: "nautical" },
  imperial: { altitude: "ft", speed: "mph", distance: "mi", scale: "imperial" },
  metric: { altitude: "m", speed: "km/h", distance: "km", scale: "metric" },
});

export function formatAltitude(alt, units = "nautical") {
  if (alt === "ground") return "ground";
  if (typeof alt !== "number") return "n/a";
  if (UNIT_SYSTEMS[units]?.altitude === "m") return `${Math.round(alt * 0.3048).toLocaleString("en-US")} m`;
  return `${Math.round(alt).toLocaleString("en-US")} ft`;
}

export function formatSpeed(kt, units = "nautical") {
  if (typeof kt !== "number") return "n/a";
  const unit = UNIT_SYSTEMS[units]?.speed || "kt";
  const factor = unit === "km/h" ? 1.852 : unit === "mph" ? 1.15078 : 1;
  return `${Math.round(kt * factor)} ${unit}`;
}

export function nmToUnits(nm, units = "nautical") {
  const unit = UNIT_SYSTEMS[units]?.distance || "nm";
  return unit === "km" ? nm * 1.852 : unit === "mi" ? nm * 1.15078 : nm;
}

export function unitsToNm(value, units = "nautical") {
  return value / nmToUnits(1, units);
}

export function formatDistanceNm(nm, units = "nautical") {
  if (typeof nm !== "number") return "n/a";
  const unit = UNIT_SYSTEMS[units]?.distance || "nm";
  return `${nmToUnits(nm, units).toFixed(1)} ${unit}`;
}

export function distanceNm(lat1, lon1, lat2, lon2) {
  const toRad = (deg) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * 3440.065 * Math.asin(Math.min(1, Math.sqrt(a)));
}

export function bearingDeg(lat1, lon1, lat2, lon2) {
  const toRad = (deg) => (deg * Math.PI) / 180;
  const y = Math.sin(toRad(lon2 - lon1)) * Math.cos(toRad(lat2));
  const x = Math.cos(toRad(lat1)) * Math.sin(toRad(lat2))
    - Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(toRad(lon2 - lon1));
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

// ── labels ──────────────────────────────────────────────────────────────────
export function callsignOf(ac) {
  return ac.flight || ac.registration || ac.hex?.toUpperCase() || "";
}

export function labelText(ac, { labels = false, extended = false, selected = false, units = "nautical" } = {}) {
  if (!labels && !selected) return "";
  const lines = [callsignOf(ac)];
  if (extended) {
    const alt = ac.alt_baro === "ground" ? "GND" : typeof ac.alt_baro === "number" ? formatAltitude(ac.alt_baro, units) : "";
    const speed = typeof ac.gs === "number" ? formatSpeed(ac.gs, units) : "";
    lines.push([alt, speed].filter(Boolean).join("  "));
    if (ac.type) lines.push(ac.type);
  }
  return lines.filter(Boolean).join("\n");
}

// ── visibility / filtering ──────────────────────────────────────────────────
export function visibleAircraft(aircraft, { isolate = false, selected = new Set(), military = false } = {}) {
  return aircraft.filter((ac) => {
    if (ac.lat === null || ac.lon === null) return false;
    if (isolate && selected.size && !selected.has(ac.hex)) return false;
    if (military && !ac.military && !selected.has(ac.hex)) return false;
    return true;
  });
}

// Merge a fresh feed snapshot into the store. In persistence mode aircraft
// that dropped out of the feed are kept (marked stale) instead of removed.
export function mergeSnapshot(store, incoming, { nowMs = Date.now(), persistence = false, staleAfterMs = 60_000 } = {}) {
  const next = new Map();
  for (const ac of incoming) {
    if (!ac.hex) continue;
    next.set(ac.hex, { ...ac, stale: false, last_seen_ms: nowMs });
  }
  for (const [hex, previous] of store) {
    if (next.has(hex)) continue;
    const age = nowMs - (previous.last_seen_ms ?? nowMs);
    if (persistence || age < staleAfterMs) next.set(hex, { ...previous, stale: true });
  }
  return next;
}

// ── trails ──────────────────────────────────────────────────────────────────
export function appendTrailPoint(trails, ac, tMs, maxPoints = 600) {
  if (ac.lat === null || ac.lon === null) return trails;
  const points = trails.get(ac.hex) || [];
  const last = points[points.length - 1];
  if (last && last.lat === ac.lat && last.lon === ac.lon) return trails;
  const nextPoints = [...points, { lat: ac.lat, lon: ac.lon, alt: ac.alt_baro, t: tMs }];
  trails.set(ac.hex, nextPoints.length > maxPoints ? nextPoints.slice(-maxPoints) : nextPoints);
  return trails;
}

// Split a trail into coloured segments; an altitude change re-colours, and a
// gap longer than gapMs (or an explicit new leg) breaks the line.
export function trailSegments(points, { gapMs = 10 * 60_000 } = {}) {
  const features = [];
  for (let i = 1; i < points.length; i += 1) {
    const a = points[i - 1];
    const b = points[i];
    if (b.new_leg || (a.t && b.t && b.t - a.t > gapMs)) continue;
    features.push({
      type: "Feature",
      properties: { color: altitudeColor(b.alt), stale: Boolean(b.stale) },
      geometry: { type: "LineString", coordinates: [[a.lon, a.lat], [b.lon, b.lat]] },
    });
  }
  return features;
}

// ── GeoJSON ─────────────────────────────────────────────────────────────────
export function aircraftFeatureCollection(aircraft, { labels, extended, selected = new Set(), units = "nautical" } = {}) {
  return {
    type: "FeatureCollection",
    features: aircraft.map((ac) => {
      const isSelected = selected.has(ac.hex);
      return {
        type: "Feature",
        id: ac.hex,
        properties: {
          hex: ac.hex,
          shape: ac.shape || "unknown",
          icon: `sw-ac-${ac.shape || "unknown"}`,
          color: altitudeColor(ac.alt_baro),
          track: ac.track ?? 0,
          selected: isSelected,
          stale: Boolean(ac.stale),
          military: Boolean(ac.military),
          emergency: Boolean(ac.emergency) || ["7500", "7600", "7700"].includes(ac.squawk),
          label: labelText(ac, { labels, extended, selected: isSelected, units }),
          sortKey: isSelected ? 1e6 : typeof ac.alt_baro === "number" ? ac.alt_baro : 0,
        },
        geometry: { type: "Point", coordinates: [ac.lon, ac.lat] },
      };
    }),
  };
}

const TABLE_SORTERS = {
  flight: (ac) => callsignOf(ac),
  type: (ac) => ac.type || "",
  squawk: (ac) => ac.squawk || "",
  altitude: (ac) => (ac.alt_baro === "ground" ? 0 : typeof ac.alt_baro === "number" ? ac.alt_baro : -1),
  speed: (ac) => ac.gs ?? -1,
  distance: (ac) => ac.distance_nm ?? Infinity,
  track: (ac) => ac.track ?? -1,
  hex: (ac) => ac.hex,
};

export function sortAircraft(aircraft, column = "distance", direction = "asc") {
  const key = TABLE_SORTERS[column] || TABLE_SORTERS.distance;
  const sign = direction === "desc" ? -1 : 1;
  return [...aircraft].sort((a, b) => {
    const va = key(a);
    const vb = key(b);
    if (va < vb) return -1 * sign;
    if (va > vb) return 1 * sign;
    return a.hex < b.hex ? -1 : 1;
  });
}
