import { describe, expect, it } from "vitest";
import {
  aircraftFeatureCollection, altitudeColor, altitudeHsl, appendTrailPoint, bearingDeg, distanceNm,
  formatAltitude, formatDistanceNm, formatSpeed, isMilitary, labelText, mergeSnapshot, normalizeAircraft,
  shapeFor, sortAircraft, trailSegments, visibleAircraft,
} from "./aircraftModel";

const RAW = {
  hex: "A37F12", flight: "AAL1512 ", r: "N123AA", t: "B738", category: "A3", alt_baro: 36000, alt_geom: 36500,
  gs: 430, track: 92.4, baro_rate: -64, squawk: "3037", emergency: "none", type: "adsb_icao", lat: 18.4,
  lon: -66.1, seen: 0.2, seen_pos: 1.0, dbFlags: 0,
};

describe("aircraft model", () => {
  it("normalizes adsb.lol aircraft records", () => {
    const ac = normalizeAircraft(RAW, 10_000);
    expect(ac).toMatchObject({
      hex: "a37f12", flight: "AAL1512", registration: "N123AA", type: "B738", alt_baro: 36000, gs: 430,
      track: 92.4, squawk: "3037", emergency: null, source_type: "adsb_icao", military: false, shape: "airliner",
      updated_ms: 9_000,
    });
    expect(normalizeAircraft({ hex: "x", alt_baro: "ground", lat: 1, lon: 2 }).alt_baro).toBe("ground");
  });

  it("colours by altitude on the tar1090 scale", () => {
    expect(altitudeHsl("ground")).toEqual({ h: 220, s: 0, l: 30 });
    expect(altitudeHsl(null)).toEqual({ h: 0, s: 0, l: 75 });
    expect(altitudeHsl(0).h).toBe(20);
    expect(altitudeHsl(40000).h).toBe(300);
    expect(altitudeHsl(60000).h).toBe(360);
    expect(altitudeHsl(10000).h).toBeCloseTo(112.5, 1);
    expect(altitudeColor(0)).toMatch(/^hsl\(20, 88%, 50%\)$/);
  });

  it("picks silhouettes from category and type", () => {
    expect(shapeFor({ category: "A7" })).toBe("helicopter");
    expect(shapeFor({ t: "EC35" })).toBe("helicopter");
    expect(shapeFor({ t: "B77W" })).toBe("heavy");
    expect(shapeFor({ category: "A5" })).toBe("heavy");
    expect(shapeFor({ t: "C172" })).toBe("prop");
    expect(shapeFor({ category: "B2" })).toBe("balloon");
    expect(shapeFor({ category: "C1" })).toBe("ground");
    expect(shapeFor({ category: "B6" })).toBe("uav");
    expect(shapeFor({})).toBe("unknown");
  });

  it("flags military aircraft from dbFlags bit 0", () => {
    expect(isMilitary({ dbFlags: 1 })).toBe(true);
    expect(isMilitary({ dbFlags: 8 })).toBe(false);
  });

  it("formats units", () => {
    expect(formatAltitude(36000)).toBe("36,000 ft");
    expect(formatAltitude(1000, "metric")).toBe("305 m");
    expect(formatAltitude("ground")).toBe("ground");
    expect(formatSpeed(100, "metric")).toBe("185 km/h");
    expect(formatSpeed(100, "imperial")).toBe("115 mph");
    expect(formatDistanceNm(10, "metric")).toBe("18.5 km");
    expect(distanceNm(18, -66, 19, -66)).toBeCloseTo(60, 0);
    expect(bearingDeg(18, -66, 19, -66)).toBeCloseTo(0, 5);
  });

  it("builds L / O labels", () => {
    const ac = normalizeAircraft(RAW);
    expect(labelText(ac)).toBe("");
    expect(labelText(ac, { labels: true })).toBe("AAL1512");
    expect(labelText(ac, { labels: true, extended: true })).toBe("AAL1512\n36,000 ft  430 kt\nB738");
    expect(labelText(ac, { selected: true })).toBe("AAL1512");
  });

  it("isolates selection and filters military", () => {
    const a = normalizeAircraft({ hex: "aaaaaa", lat: 1, lon: 1 });
    const b = normalizeAircraft({ hex: "bbbbbb", lat: 1, lon: 1, dbFlags: 1 });
    const c = normalizeAircraft({ hex: "cccccc" });
    expect(visibleAircraft([a, b, c]).map((x) => x.hex)).toEqual(["aaaaaa", "bbbbbb"]);
    expect(visibleAircraft([a, b], { isolate: true, selected: new Set(["aaaaaa"]) }).map((x) => x.hex)).toEqual(["aaaaaa"]);
    expect(visibleAircraft([a, b], { military: true }).map((x) => x.hex)).toEqual(["bbbbbb"]);
  });

  it("keeps vanished aircraft only briefly unless persistence mode is on", () => {
    const store = mergeSnapshot(new Map(), [{ hex: "aaaaaa" }], { nowMs: 0 });
    expect(mergeSnapshot(store, [], { nowMs: 30_000 }).get("aaaaaa").stale).toBe(true);
    expect(mergeSnapshot(store, [], { nowMs: 120_000 }).has("aaaaaa")).toBe(false);
    expect(mergeSnapshot(store, [], { nowMs: 120_000, persistence: true }).has("aaaaaa")).toBe(true);
  });

  it("accumulates trails and breaks them at gaps and new legs", () => {
    const trails = new Map();
    appendTrailPoint(trails, { hex: "a", lat: 1, lon: 1, alt_baro: 1000 }, 0);
    appendTrailPoint(trails, { hex: "a", lat: 1, lon: 1, alt_baro: 1000 }, 1000);
    appendTrailPoint(trails, { hex: "a", lat: 1.1, lon: 1, alt_baro: 2000 }, 2000);
    expect(trails.get("a")).toHaveLength(2);
    const segments = trailSegments([
      { lat: 0, lon: 0, alt: 0, t: 0 }, { lat: 0, lon: 1, alt: 0, t: 1000 },
      { lat: 0, lon: 2, alt: 0, t: 2_000_000 }, { lat: 0, lon: 3, alt: 0, t: 2_001_000, new_leg: true },
    ]);
    expect(segments).toHaveLength(1);
  });

  it("emits GeoJSON with icon, colour, rotation and selection", () => {
    const fc = aircraftFeatureCollection([normalizeAircraft(RAW)], { selected: new Set(["a37f12"]), labels: true });
    const props = fc.features[0].properties;
    expect(props).toMatchObject({ icon: "sw-ac-airliner", track: 92.4, selected: true, label: "AAL1512" });
    expect(fc.features[0].geometry.coordinates).toEqual([-66.1, 18.4]);
    const emergency = aircraftFeatureCollection([normalizeAircraft({ ...RAW, squawk: "7700" })]);
    expect(emergency.features[0].properties.emergency).toBe(true);
  });

  it("sorts the aircraft table", () => {
    const list = [{ hex: "b", alt_baro: 100 }, { hex: "a", alt_baro: "ground" }, { hex: "c", alt_baro: 900 }];
    expect(sortAircraft(list, "altitude", "desc").map((x) => x.hex)).toEqual(["c", "b", "a"]);
  });
});
