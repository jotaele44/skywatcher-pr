import { afterEach, describe, expect, it, vi } from "vitest";
import { LiveMapEngine, rasterBaseStyle } from "./liveMapEngine";
import { BASE_LAYERS, GLYPHS_URL } from "./sourceCatalog";

vi.mock("./aircraftIcons.js", () => ({
  createAircraftImages: () => [{ id: "sw-ac-airliner", image: { width: 1, height: 1, data: new Uint8ClampedArray(4) }, options: { sdf: true } }],
}));

class FakeMap {
  constructor(options) {
    this.options = options;
    this.handlers = {};
    this.sources = {};
    this.layers = [];
    this.images = new Set();
    this.layout = {};
    this.paint = {};
    this.controls = [];
    this.removed = false;
    this.style = typeof options.style === "string" ? { sources: {}, layers: [] } : structuredClone(options.style);
  }
  on(event, layerOrHandler, handler) {
    const key = handler ? `${event}:${layerOrHandler}` : event;
    (this.handlers[key] ||= []).push(handler || layerOrHandler);
  }
  fire(event, payload) { for (const h of this.handlers[event] || []) h(payload); }
  addControl(control) { this.controls.push(control); }
  addSource(id, source) { this.sources[id] = { ...source, setData: vi.fn(), setTiles: vi.fn() }; }
  getSource(id) { return this.sources[id]; }
  removeSource(id) { delete this.sources[id]; }
  addLayer(layer, before) {
    const index = before ? this.layers.findIndex((l) => l.id === before) : -1;
    if (index >= 0) this.layers.splice(index, 0, layer);
    else this.layers.push(layer);
  }
  getLayer(id) { return this.layers.find((l) => l.id === id); }
  removeLayer(id) { this.layers = this.layers.filter((l) => l.id !== id); }
  setLayoutProperty(id, key, value) { this.layout[`${id}.${key}`] = value; }
  setPaintProperty(id, key, value) { this.paint[`${id}.${key}`] = value; }
  hasImage(id) { return this.images.has(id); }
  addImage(id) { this.images.add(id); }
  getCanvas() { return { style: {} }; }
  getBounds() { return { getWest: () => -68, getSouth: () => 17, getEast: () => -65, getNorth: () => 19 }; }
  getCenter() { return { lng: -66.5, lat: 18 }; }
  getZoom() { return 8; }
  queryRenderedFeatures() { return this.hit || []; }
  getStyle() { return { sources: { ...this.sources }, layers: [...this.layers] }; }
  setStyle(style, options) { this.lastSetStyle = { style, options }; }
  easeTo(options) { this.lastEase = options; }
  panTo(center) { this.lastPan = center; }
  resize() {}
  remove() { this.removed = true; }
}

const maplibregl = {
  Map: FakeMap,
  AttributionControl: class { constructor(o) { this.o = o; } },
  ScaleControl: class { constructor(o) { this.o = o; } setUnit(u) { this.unit = u; } },
};

function makeEngine(overrides = {}) {
  const engine = new LiveMapEngine({
    maplibregl, container: {}, viewport: { center: [-66.4, 18.2], zoom: 8 }, baseLayerId: "esri_satellite", ...overrides,
  });
  engine.map.fire("style.load");
  return engine;
}

afterEach(() => vi.useRealTimers());

describe("LiveMapEngine", () => {
  it("starts on a raster basemap with glyphs and installs aircraft layers in order", () => {
    const engine = makeEngine();
    expect(engine.map.options.style.glyphs).toBe(GLYPHS_URL);
    expect(engine.map.options.style.sources["sw-base"].tiles[0]).toContain("World_Imagery");
    const ids = engine.map.layers.map((l) => l.id);
    expect(ids.indexOf("sw-dim")).toBeLessThan(ids.indexOf("sw-rings-line"));
    expect(ids.indexOf("sw-trails")).toBeLessThan(ids.indexOf("sw-aircraft"));
    expect(engine.map.sources["sw-aircraft"].attribution).toMatch(/adsb\.lol.*ODbL/);
  });

  it("adds overlays beneath aircraft and removes them cleanly", () => {
    vi.useFakeTimers();
    const engine = makeEngine();
    engine.setOverlay("noaa_radar", true);
    engine.setOverlay("us_artcc", true);
    const ids = engine.map.layers.map((l) => l.id);
    expect(ids.indexOf("sw-ov-noaa_radar")).toBeLessThan(ids.indexOf("sw-aircraft"));
    expect(engine.map.sources["sw-ov-noaa_radar"].tiles[0]).toContain("nowcoast.noaa.gov");
    expect(ids).toContain("sw-ov-us_artcc-line");
    vi.advanceTimersByTime(5 * 60_000);
    expect(engine.map.sources["sw-ov-noaa_radar"].setTiles).toHaveBeenCalled();
    engine.setOverlay("noaa_radar", false);
    expect(engine.map.getLayer("sw-ov-noaa_radar")).toBeUndefined();
    expect(engine.map.getSource("sw-ov-noaa_radar")).toBeUndefined();
  });

  it("switches to vector basemaps while keeping its own layers", () => {
    const engine = makeEngine();
    engine.setBaseLayer("ofm_liberty");
    const { style, options } = engine.map.lastSetStyle;
    expect(style).toBe("https://tiles.openfreemap.org/styles/liberty");
    const merged = options.transformStyle(
      { sources: { "sw-base": {}, "sw-aircraft": { type: "geojson" } }, layers: [{ id: "sw-base" }, { id: "sw-aircraft" }] },
      { sources: { openmaptiles: {} }, layers: [{ id: "water" }], glyphs: "g" },
    );
    expect(Object.keys(merged.sources)).toEqual(["openmaptiles", "sw-aircraft"]);
    expect(merged.layers.map((l) => l.id)).toEqual(["water", "sw-aircraft"]);
    engine.setBaseLayer("vfr_sectional");
    expect(engine.map.lastSetStyle.style.sources["sw-base"].minzoom).toBe(8);
  });

  it("applies feature visibility, dimming, scale units and data", () => {
    const engine = makeEngine();
    engine.setFeatureVisibility({ aircraftWebGL: false, rangeRings: false });
    expect(engine.map.layout["sw-aircraft.visibility"]).toBe("none");
    expect(engine.map.layout["sw-aircraft-dots.visibility"]).toBe("visible");
    expect(engine.map.layout["sw-rings-line.visibility"]).toBe("none");
    engine.setDim(true, 0.6);
    expect(engine.map.paint["sw-dim.fill-opacity"]).toBe(0.6);
    engine.setDim(false, 0.6);
    expect(engine.map.paint["sw-dim.fill-opacity"]).toBe(0);
    engine.setScaleUnit("metric");
    expect(engine.scale.unit).toBe("metric");
    const fc = { type: "FeatureCollection", features: [] };
    engine.setAircraft(fc);
    expect(engine.map.sources["sw-aircraft"].setData).toHaveBeenCalledWith(fc);
  });

  it("reports clicked aircraft and loads icons on demand", () => {
    const onSelect = vi.fn();
    const engine = makeEngine({ onSelect });
    engine.map.hit = [{ properties: { hex: "a37f12" } }];
    engine.handleClick({ point: { x: 10, y: 10 }, originalEvent: { ctrlKey: true } });
    expect(onSelect).toHaveBeenCalledWith("a37f12", { additive: true });
    engine.map.hit = [];
    engine.handleClick({ point: { x: 1, y: 1 }, originalEvent: {} });
    expect(onSelect).toHaveBeenLastCalledWith(null, { additive: false });
    engine.addMissingImage("sw-ac-airliner");
    expect(engine.map.hasImage("sw-ac-airliner")).toBe(true);
  });

  it("cleans up timers and the map exactly once", () => {
    const engine = makeEngine();
    engine.setOverlay("nexrad", true);
    engine.destroy();
    engine.destroy();
    expect(engine.map.removed).toBe(true);
    expect(engine.timers.size).toBe(0);
  });

  it("builds raster styles for every raster base layer", () => {
    for (const entry of BASE_LAYERS.filter((e) => e.kind === "raster")) {
      const style = rasterBaseStyle(entry, "");
      expect(style.sources["sw-base"].tiles.length, entry.id).toBeGreaterThan(0);
    }
  });
});
