// Pure sky geometry and formatting helpers for the Sky Target Finder.
//
// The backend returns apparent (refracted) altitude/azimuth for everything a chart
// draws; the browser only projects. The chart uses a gnomonic (tangent-plane)
// projection centred on the selected target in the horizon frame: screen up is
// towards the zenith and screen right is towards increasing azimuth. Projected
// coordinates are tangent-plane offsets expressed in degrees (tan(angle) * 180/pi),
// which track the true angular offset closely near the centre, so FOV and zoom
// changes only re-project and never need a refetch.

const DEG = Math.PI / 180;
const RAD = 180 / Math.PI;

// Rounding guard so exact half-units (59.95 s, 59.5") carry upward even when the
// degree-to-unit conversion lands a hair below the half in floating point.
const ROUND_EPSILON = 1e-6;

const CARDINALS = [
  ["N", 0],
  ["E", 90],
  ["S", 180],
  ["W", 270],
];

const pad2 = (value) => String(value).padStart(2, "0");

export function normalizeAzimuth(az) {
  return ((az % 360) + 360) % 360;
}

// Forward gnomonic projection of (alt, az) about (centerAlt, centerAz), all degrees.
// Returns tangent-plane x (right, increasing azimuth) and y (up, towards zenith) in
// degrees. Points 90 degrees or more from the centre cannot be projected and come
// back with visible=false.
export function gnomonic(alt, az, centerAlt, centerAz) {
  const phi = alt * DEG;
  const phi0 = centerAlt * DEG;
  const dLambda = (az - centerAz) * DEG;
  const cosC =
    Math.sin(phi0) * Math.sin(phi) + Math.cos(phi0) * Math.cos(phi) * Math.cos(dLambda);
  if (!(cosC > 1e-9)) return { x: Number.NaN, y: Number.NaN, visible: false, cosC };
  const x = (Math.cos(phi) * Math.sin(dLambda)) / cosC;
  const y =
    (Math.cos(phi0) * Math.sin(phi) - Math.sin(phi0) * Math.cos(phi) * Math.cos(dLambda)) / cosC;
  return { x: x * RAD, y: y * RAD, visible: true, cosC };
}

// Inverse of gnomonic(): tangent-plane degrees back to (alt, az) in degrees.
export function inverseGnomonic(x, y, centerAlt, centerAz) {
  const px = x * DEG;
  const py = y * DEG;
  const rho = Math.hypot(px, py);
  if (rho < 1e-12) return { alt: centerAlt, az: normalizeAzimuth(centerAz) };
  const c = Math.atan(rho);
  const sinC = Math.sin(c);
  const cosC = Math.cos(c);
  const phi0 = centerAlt * DEG;
  const phi = Math.asin(cosC * Math.sin(phi0) + (py * sinC * Math.cos(phi0)) / rho);
  const lambda =
    centerAz * DEG +
    Math.atan2(px * sinC, rho * Math.cos(phi0) * cosC - py * Math.sin(phi0) * sinC);
  return { alt: phi * RAD, az: normalizeAzimuth(lambda * RAD) };
}

// Screen directions of the true horizon directions N/E/S/W (and the zenith, Z) as
// seen at the chart centre. Each cardinal is the horizontal unit vector towards that
// azimuth projected onto the chart's right/up basis at the centre:
//   x = sin(A - az0), y = -sin(alt0) * cos(A - az0);  zenith: x = 0, y = cos(alt0).
// Facing south (az0 = 180) with the target above the horizon, E lands on the left,
// W on the right, S points down towards the southern horizon and N points up over
// the zenith. The N/S axis foreshortens by sin(alt0); minFlatten keeps a drawn rose
// legible near the horizon without changing any direction's sign.
export function compassVectors(centerAlt, centerAz, minFlatten = 0) {
  const s = Math.sin(centerAlt * DEG);
  const k = (s < 0 ? -1 : 1) * Math.max(Math.abs(s), minFlatten);
  const vectors = {};
  for (const [letter, azimuth] of CARDINALS) {
    const d = (azimuth - centerAz) * DEG;
    vectors[letter] = { x: Math.sin(d), y: -k * Math.cos(d) };
  }
  vectors.Z = { x: 0, y: Math.cos(centerAlt * DEG) };
  return vectors;
}

// Width/height in tangent-plane degrees of a 3:2 sensor rectangle whose long side
// spans fovDeg on the sky.
export function fovRectangle(fovDeg) {
  const half = (fovDeg / 2) * DEG;
  const halfHeight = (fovDeg / 3) * DEG;
  return { width: 2 * Math.tan(half) * RAD, height: 2 * Math.tan(halfHeight) * RAD };
}

// "20h 56m 19.1s" (J2000 right ascension, tenths of a second, with carry).
export function formatRaHms(raDeg) {
  if (!Number.isFinite(raDeg)) return "—";
  // 1 degree of RA = 240 s of time = 2400 tenths of a second.
  const tenths = Math.round(normalizeAzimuth(raDeg) * 2400 + ROUND_EPSILON) % 864000;
  const hours = Math.floor(tenths / 36000);
  const minutes = Math.floor((tenths % 36000) / 600);
  const seconds = ((tenths % 600) / 10).toFixed(1).padStart(4, "0");
  return `${pad2(hours)}h ${pad2(minutes)}m ${seconds}s`;
}

// "+31° 44′ 34″" (J2000 declination, whole arcseconds, with carry).
export function formatDecDms(decDeg) {
  if (!Number.isFinite(decDeg)) return "—";
  const total = Math.round(Math.abs(decDeg) * 3600 + ROUND_EPSILON);
  const sign = decDeg < 0 && total > 0 ? "-" : "+";
  const degrees = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return `${sign}${pad2(degrees)}° ${pad2(minutes)}′ ${pad2(seconds)}″`;
}

// "∠ 75°" — the altitude badge used on rows and on the chart card.
export function formatAltitudeBadge(altDeg) {
  if (!Number.isFinite(altDeg)) return "∠ —";
  return `∠ ${Math.round(altDeg) || 0}°`;
}

function formatDegrees1(value, { azimuth = false } = {}) {
  if (!Number.isFinite(value)) return "—";
  let text = value.toFixed(1);
  if (azimuth && text === "360.0") text = "0.0";
  return `${text}°`;
}

function formatObserverCoordinate(value) {
  return Number.isFinite(value) ? value.toFixed(4) : "—";
}

function formatElevation(value) {
  if (!Number.isFinite(value)) return "—";
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

// ISO-8601 UTC at seconds precision with a trailing Z ("2026-10-20T00:30:00Z").
export function toUtcSeconds(value) {
  if (value === null || value === undefined || value === "") return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toISOString().replace(/\.\d{3}Z$/, "Z");
}

// The five-line clipboard block (CONTRACT section 3). `observer` accepts the API echo
// ({lat_deg, lon_deg, elev_m}) or the request shape ({lat, lon, elev_m}).
export function formatCoordinateClipboard(target, atUtc, observer = {}) {
  const lat = observer?.lat_deg ?? observer?.lat;
  const lon = observer?.lon_deg ?? observer?.lon;
  const elev = observer?.elev_m ?? observer?.elev;
  return [
    target?.display || target?.designation || target?.id || "",
    `RA (J2000): ${formatRaHms(target?.ra_j2000_deg)}  Dec (J2000): ${formatDecDms(target?.dec_j2000_deg)}`,
    `Alt: ${formatDegrees1(target?.alt_deg)}  Az: ${formatDegrees1(target?.az_deg, { azimuth: true })}`,
    `Observer: ${formatObserverCoordinate(lat)}, ${formatObserverCoordinate(lon)} · ${formatElevation(elev)} m`,
    `UTC: ${toUtcSeconds(atUtc)}`,
  ].join("\n");
}

// "7:59 PM" in the browser's local time zone (or an explicit one for tests).
export function formatLocalTime(value, options = {}) {
  const date = value instanceof Date ? value : new Date(value);
  if (value === null || value === undefined || Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", ...options }).format(date);
}

// "Oct 19, 8:30 PM" in the browser's local time zone.
export function formatLocalDateTime(value, options = {}) {
  const date = value instanceof Date ? value : new Date(value);
  if (value === null || value === undefined || Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    ...options,
  }).format(date);
}

// "00:30:00" — the UTC clock part of an instant.
export function formatUtcClock(value) {
  const iso = toUtcSeconds(value);
  const match = /T(\d{2}:\d{2}:\d{2})Z$/.exec(iso);
  return match ? match[1] : "—";
}

// What a row says about a target's visibility: the live altitude when it is above
// the horizon, otherwise its rise–set window in local time or a state label.
export function describeVisibility(target, options = {}) {
  const visibility = target?.visibility || {};
  const state = visibility.state || (target?.above_horizon ? "UP" : "DOWN");
  if (target?.above_horizon && Number.isFinite(target?.alt_deg)) {
    let note = "";
    if (state === "ALWAYS_UP") note = "Always up";
    else if (visibility.set_utc) note = `sets ${formatLocalTime(visibility.set_utc, options)}`;
    return { state: state === "ALWAYS_UP" ? "ALWAYS_UP" : "UP", text: formatAltitudeBadge(target.alt_deg), note };
  }
  if (state === "NEVER_UP") return { state, text: "Never rises", note: "" };
  if (state === "ALWAYS_UP") return { state, text: "Always up", note: "" };
  if (visibility.rise_utc && visibility.set_utc) {
    return {
      state: "DOWN",
      text: `${formatLocalTime(visibility.rise_utc, options)}–${formatLocalTime(visibility.set_utc, options)}`,
      note: "",
    };
  }
  if (visibility.rise_utc) {
    return { state: "DOWN", text: `rises ${formatLocalTime(visibility.rise_utc, options)}`, note: "" };
  }
  return { state: "DOWN", text: "Below horizon", note: "" };
}
