// Small geodesy helpers for the /live map (pure; node --test).
import { nmToUnits, unitsToNm } from "./aircraftModel.js";

const EARTH_RADIUS_NM = 3440.065;

export function destinationPoint(lat, lon, bearingDeg, distanceNm) {
  const toRad = (deg) => (deg * Math.PI) / 180;
  const toDeg = (rad) => (rad * 180) / Math.PI;
  const delta = distanceNm / EARTH_RADIUS_NM;
  const theta = toRad(bearingDeg);
  const phi1 = toRad(lat);
  const lambda1 = toRad(lon);
  const phi2 = Math.asin(Math.sin(phi1) * Math.cos(delta) + Math.cos(phi1) * Math.sin(delta) * Math.cos(theta));
  const lambda2 = lambda1 + Math.atan2(
    Math.sin(theta) * Math.sin(delta) * Math.cos(phi1),
    Math.cos(delta) - Math.sin(phi1) * Math.sin(phi2),
  );
  return [((toDeg(lambda2) + 540) % 360) - 180, toDeg(phi2)];
}

// Range rings around ``center`` ([lon, lat]); distances are in display units.
export function rangeRingCollection(center, distances, units = "nautical", steps = 96) {
  if (!Array.isArray(center)) return { type: "FeatureCollection", features: [] };
  const [lon, lat] = center;
  const unit = { nautical: "nm", imperial: "mi", metric: "km" }[units] || "nm";
  const features = [];
  for (const distance of distances) {
    const nm = unitsToNm(Number(distance), units);
    if (!Number.isFinite(nm) || nm <= 0) continue;
    const coordinates = [];
    for (let i = 0; i <= steps; i += 1) coordinates.push(destinationPoint(lat, lon, (360 * i) / steps, nm));
    features.push({ type: "Feature", properties: { kind: "ring", distance }, geometry: { type: "LineString", coordinates } });
    features.push({
      type: "Feature",
      properties: { kind: "ring-label", label: `${Math.round(nmToUnits(nm, units))} ${unit}` },
      geometry: { type: "Point", coordinates: destinationPoint(lat, lon, 0, nm) },
    });
  }
  return { type: "FeatureCollection", features };
}

// [west, south, east, north] request box for the backend from map bounds.
export function requestBox(bounds) {
  let [west, south, east, north] = bounds;
  south = Math.max(-85, south);
  north = Math.min(85, north);
  if (east - west >= 360 || west > east) return [-180, south, 180, north];
  const wrap = (value) => ((((value + 180) % 360) + 360) % 360) - 180;
  west = wrap(west);
  east = wrap(east);
  if (west > east) return [-180, south, 180, north];
  return [west, south, east, north];
}
