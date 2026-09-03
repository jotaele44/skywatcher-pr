import test from "node:test";
import assert from "node:assert/strict";
import { assertOfflineStyle, getBasemap, LOCAL_BLANK_STYLE_ID } from "../basemapRegistry.js";
import { indexCapabilities, isCapabilityEnabled } from "../capabilityGate.js";
import { availableLayers } from "../layerRegistry.js";
import { createMapRuntime } from "../mapRuntimeAdapter.js";
import { EMPTY_SELECTION, selectionReducer, selectionToGeoJSON } from "../selectionState.js";
import { DEFAULT_VIEWPORT, normalizeViewport } from "../viewportState.js";

const capabilities = indexCapabilities({ capabilities: [
  { id: "map_navigation", status: "available" },
  { id: "geolocation", status: "available" },
  { id: "airport_detail", status: "available" },
  { id: "aircraft_viewport_list", status: "unavailable_no_artifact" },
  { id: "playback_timeline", status: "unavailable_no_artifact" },
] });

test("local diagnostic style is offline and credential free", () => {
  const basemap = getBasemap(LOCAL_BLANK_STYLE_ID);
  assert.equal(basemap.networkRequired, false);
  assert.equal(basemap.providerKeysRequired, false);
  assert.equal(assertOfflineStyle(basemap.style), true);
  assert.match(basemap.attribution, /MapLibre GL JS/);
});

test("viewport normalization clamps unsafe values", () => {
  const value = normalizeViewport({ center: [999, -999], zoom: 100, bearing: -10, pitch: 120 });
  assert.deepEqual(value.center, [180, -85]);
  assert.equal(value.zoom, 24);
  assert.equal(value.bearing, 350);
  assert.equal(value.pitch, 85);
  assert.deepEqual(normalizeViewport({}), DEFAULT_VIEWPORT);
});

test("selection reducer emits local GeoJSON without source mutation", () => {
  const selected = selectionReducer(EMPTY_SELECTION, { type: "coordinate", coordinate: [-66.1, 18.4] });
  const geojson = selectionToGeoJSON(selected);
  assert.equal(geojson.features.length, 1);
  assert.deepEqual(geojson.features[0].geometry.coordinates, [-66.1, 18.4]);
  assert.deepEqual(selectionReducer(selected, { type: "clear" }), { ...EMPTY_SELECTION, properties: {} });
});

test("capability gating suppresses unavailable operational layers", () => {
  assert.equal(isCapabilityEnabled(capabilities, "map_navigation"), true);
  assert.equal(isCapabilityEnabled(capabilities, "aircraft_viewport_list"), false);
  const ids = availableLayers(capabilities).map((layer) => layer.id);
  assert.deepEqual(ids, ["diagnostic-pr-extent", "selection", "airports"]);
});

test("map runtime installs attribution and performs deterministic WebGL cleanup", () => {
  class FakeMap {
    constructor(options) {
      this.options = options;
      this.handlers = new Map();
      this.controls = [];
      this.sources = new Map();
      this.layers = new Map();
      this.removed = false;
    }
    on(event, handler) { this.handlers.set(event, handler); }
    off(event, handler) { if (this.handlers.get(event) === handler) this.handlers.delete(event); }
    emit(event, payload) { this.handlers.get(event)?.(payload); }
    addControl(control, position) { this.controls.push([control, position]); }
    removeControl(control) { this.controls = this.controls.filter(([item]) => item !== control); }
    addSource(id, source) { this.sources.set(id, { ...source, setData(data) { this.data = data; } }); }
    getSource(id) { return this.sources.get(id); }
    addLayer(layer) { this.layers.set(layer.id, layer); }
    getLayer(id) { return this.layers.get(id); }
    setLayoutProperty(id, key, value) { this.layers.get(id).layout[key] = value; }
    getCenter() { return { lng: -66.25, lat: 18.22 }; }
    getZoom() { return 7.2; }
    getBearing() { return 0; }
    getPitch() { return 0; }
    jumpTo() {}
    resize() {}
    remove() { this.removed = true; }
  }
  class Control { constructor(options) { this.options = options; } }
  const maplibregl = { Map: FakeMap, AttributionControl: Control, NavigationControl: Control, GeolocateControl: Control };
  const selections = [];
  const runtime = createMapRuntime({
    maplibregl,
    container: {},
    capabilityIndex: capabilities,
    viewport: DEFAULT_VIEWPORT,
    selection: EMPTY_SELECTION,
    geolocationAvailable: true,
    onSelectionChange: (action) => selections.push(action),
  });
  runtime.map.emit("load");
  runtime.map.emit("click", { lngLat: { lng: -66.0, lat: 18.3 } });
  assert.equal(runtime.map.controls.length, 3);
  assert.equal(runtime.map.options.attributionControl, false);
  assert.deepEqual(selections[0], { type: "coordinate", coordinate: [-66.0, 18.3] });
  runtime.destroy();
  assert.equal(runtime.map.handlers.size, 0);
  assert.equal(runtime.map.controls.length, 0);
  assert.equal(runtime.map.removed, true);
  runtime.destroy();
});
