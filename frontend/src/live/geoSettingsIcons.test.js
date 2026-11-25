import { describe, expect, it } from "vitest";
import { destinationPoint, rangeRingCollection, requestBox } from "./geo";
import { DEFAULT_SETTINGS, SETTINGS_STORAGE_KEY, loadSettings, normalizeSettings, saveSettings } from "./liveSettings";
import { ICON_SIZE, SDF_RADIUS, SHAPE_PATHS, maskToSdf } from "./aircraftIcons";
import { SHAPES } from "./aircraftModel";

const memoryStorage = () => {
  const values = new Map();
  return { getItem: (k) => values.get(k) ?? null, setItem: (k, v) => values.set(k, String(v)) };
};

describe("geo helpers", () => {
  it("draws closed range rings with labels in display units", () => {
    const fc = rangeRingCollection([-66.4, 18.2], [100, 150], "nautical", 32);
    const rings = fc.features.filter((f) => f.properties.kind === "ring");
    expect(rings).toHaveLength(2);
    expect(rings[0].geometry.coordinates).toHaveLength(33);
    expect(fc.features.find((f) => f.properties.kind === "ring-label").properties.label).toBe("100 nm");
    const [lon, lat] = destinationPoint(18.2, -66.4, 0, 60);
    expect(lon).toBeCloseTo(-66.4, 6);
    expect(lat).toBeCloseTo(19.2, 1);
    expect(rangeRingCollection(null, [1]).features).toEqual([]);
  });

  it("produces backend-safe request boxes", () => {
    expect(requestBox([-68, 17, -65, 19])).toEqual([-68, 17, -65, 19]);
    expect(requestBox([-200, -90, 200, 90])).toEqual([-180, -85, 180, 85]);
    expect(requestBox([170, 0, 190, 10])).toEqual([-180, 0, 180, 10]);
  });
});

describe("live settings", () => {
  it("defaults to the adsb.lol-like setup over Puerto Rico", () => {
    expect(DEFAULT_SETTINGS.baseLayer).toBe("esri_satellite");
    expect(DEFAULT_SETTINGS.mapDim).toBe(true);
    expect(DEFAULT_SETTINGS.rangeRings).toEqual([100, 150, 200]);
  });

  it("drops unknown or unsafe values when loading", () => {
    const normalized = normalizeSettings({ baseLayer: "nope", overlays: ["noaa_radar", "evil"], units: "parsecs", customTemplate: "http://x/{z}/{x}/{y}", refreshS: 0.1, rangeRings: [50, -1, "x"] });
    expect(normalized.baseLayer).toBe("esri_satellite");
    expect(normalized.overlays).toEqual(["noaa_radar"]);
    expect(normalized.units).toBe("nautical");
    expect(normalized.customTemplate).toBe("");
    expect(normalized.refreshS).toBe(2);
    expect(normalized.rangeRings).toEqual([50]);
    expect(normalizeSettings({ baseLayer: "custom_tiles" }).baseLayer).toBe("esri_satellite");
  });

  it("round-trips through storage and survives corrupt JSON", () => {
    const storage = memoryStorage();
    saveSettings({ ...DEFAULT_SETTINGS, overlays: ["noaa_sat", "noaa_radar"], labels: true }, storage);
    expect(loadSettings(storage)).toMatchObject({ overlays: ["noaa_sat", "noaa_radar"], labels: true });
    storage.setItem(SETTINGS_STORAGE_KEY, "{oops");
    expect(loadSettings(storage).overlays).toEqual([]);
  });
});

describe("aircraft icons", () => {
  it("defines a silhouette for every shape the model can emit", () => {
    expect(Object.keys(SHAPE_PATHS).sort()).toEqual([...SHAPES].sort());
  });

  it("encodes a signed distance field with the MapLibre edge at 0.75", () => {
    const size = 24;
    const mask = new Float32Array(size * size);
    for (let y = 8; y < 16; y += 1) for (let x = 8; x < 16; x += 1) mask[y * size + x] = 1;
    const sdf = maskToSdf(mask, size, size);
    const alpha = (x, y) => sdf[(y * size + x) * 4 + 3];
    expect(alpha(12, 12)).toBeGreaterThan(192);
    expect(alpha(0, 0)).toBe(0);
    expect(Math.abs(alpha(8, 12) - 199)).toBeLessThan(10);
    expect(ICON_SIZE).toBe(48 + 2 * SDF_RADIUS);
  });
});
