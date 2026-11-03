// Replay timing helpers for the /live map. Pure functions (node --test).
//
// adsb.lol publishes history as half-hour chunks; the chunk for the half hour
// in progress is not available yet, so a request for "now" lands one minute
// into the newest complete chunk, as on the adsb.lol map.

export const CHUNK_MS = 30 * 60_000;
export const SPEED_SLIDER_BASE = 3; // cubic slider: fine control near 1x, up to 1000x
export const SPEED_MIN = 1;
export const SPEED_MAX = 1000;
export const DEFAULT_SPEED = 30;

export function latestReplayStart(nowMs = Date.now()) {
  const floor = nowMs - (nowMs % CHUNK_MS);
  return floor - CHUNK_MS;
}

export function clampReplayTime(tsMs, nowMs = Date.now()) {
  const latestEnd = latestReplayStart(nowMs) + CHUNK_MS;
  if (!Number.isFinite(tsMs) || tsMs >= latestEnd) {
    return { ts: latestReplayStart(nowMs) + 60_000, clamped: true };
  }
  return { ts: tsMs, clamped: false };
}

export function speedFromSlider(value) {
  const speed = Math.pow(Number(value), SPEED_SLIDER_BASE);
  return Math.min(SPEED_MAX, Math.max(SPEED_MIN, Math.round(speed * 10) / 10));
}

export function sliderFromSpeed(speed) {
  return Math.pow(Math.min(SPEED_MAX, Math.max(SPEED_MIN, Number(speed))), 1 / SPEED_SLIDER_BASE);
}

export const SPEED_SLIDER = Object.freeze({
  min: sliderFromSpeed(SPEED_MIN),
  max: sliderFromSpeed(SPEED_MAX),
  step: 0.07,
});

// Build a UTC instant from the replay bar's date (YYYY-MM-DD) + hour/minute.
export function composeReplayTime(dateText, hours, minutes) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateText || ""));
  if (!match) return NaN;
  return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(hours) || 0, Number(minutes) || 0, 0);
}

export function utcParts(tsMs) {
  const d = new Date(tsMs);
  return { date: d.toISOString().slice(0, 10), hours: d.getUTCHours(), minutes: d.getUTCMinutes(), seconds: d.getUTCSeconds() };
}

const pad = (value) => String(value).padStart(2, "0");

export function utcClock(tsMs) {
  const p = utcParts(tsMs);
  return `${pad(p.hours)}:${pad(p.minutes)}:${pad(p.seconds)}`;
}

export function localClock(tsMs, timeZone) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).format(new Date(tsMs));
}

export function localDate(tsMs, timeZone) {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" })
    .formatToParts(new Date(tsMs));
  const get = (type) => parts.find((p) => p.type === type)?.value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}

export function timeZoneAbbreviation(tsMs, timeZone) {
  const part = new Intl.DateTimeFormat("en-US", { timeZone, timeZoneName: "short" })
    .formatToParts(new Date(tsMs))
    .find((p) => p.type === "timeZoneName");
  return part?.value || "Local";
}

// Index of the frame to show at tsMs (last frame whose time <= ts).
export function frameIndexAt(frames, tsMs) {
  let lo = 0;
  let hi = frames.length - 1;
  let best = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (frames[mid].t * 1000 <= tsMs) {
      best = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return best;
}

// Expand compact replay rows ([hex, lat, lon, alt, gs, type, flight, squawk])
// into aircraft records; headings come from the previous frame's position
// because replay chunks carry no track field.
export function frameToAircraft(frame, fields, previousPositions = new Map()) {
  const index = Object.fromEntries(fields.map((name, i) => [name, i]));
  return frame.aircraft.map((row) => {
    const hex = row[index.hex];
    const lat = row[index.lat];
    const lon = row[index.lon];
    const previous = previousPositions.get(hex);
    let track = previous?.track ?? null;
    if (previous && (previous.lat !== lat || previous.lon !== lon)) {
      const toRad = (deg) => (deg * Math.PI) / 180;
      const y = Math.sin(toRad(lon - previous.lon)) * Math.cos(toRad(lat));
      const x = Math.cos(toRad(previous.lat)) * Math.sin(toRad(lat))
        - Math.sin(toRad(previous.lat)) * Math.cos(toRad(lat)) * Math.cos(toRad(lon - previous.lon));
      track = ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
    }
    return {
      hex,
      lat,
      lon,
      alt_baro: row[index.alt_baro],
      gs: row[index.gs],
      type: row[index.source_type],
      flight: row[index.flight] || undefined,
      squawk: row[index.squawk] || undefined,
      track,
    };
  });
}
