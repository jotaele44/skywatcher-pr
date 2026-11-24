// MapLibre runtime for the /live airspace map. Owns every source and layer;
// React components only call the methods below. All ids start with "sw-" so
// they survive basemap switches (vector basemaps replace the whole style).
import {
  BASE_LAYERS, GLYPHS_URL, LABEL_FONT, OVERLAYS, customBaseLayer, findBaseLayer, findOverlay, resolveTiles,
} from "./sourceCatalog.js";
import { createAircraftImages } from "./aircraftIcons.js";

const EMPTY = Object.freeze({ type: "FeatureCollection", features: [] });
const WORLD = { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]]] } }] };
const TOP_LAYER = "sw-rings-line";
const AIRCRAFT_LAYERS = ["sw-aircraft", "sw-aircraft-dots"];
const AIRCRAFT_ATTRIBUTION = 'Aircraft: <a href="https://adsb.lol">adsb.lol</a> contributors (ODbL 1.0)';
const SHAPE_SCALE =["match", ["get", "shape"], "heavy", 1.15, "prop", 0.8, "helicopter", 0.9, "glider", 0.9, "ground", 0.6, "balloon", 0.8, 1];

function rasterSource(entry, apiBase, now = new Date()) {
  const source = {
    type: "raster",
    tiles: resolveTiles(entry, { now, apiBase }),
    tileSize: entry.tileSize || 256,
    minzoom: entry.minzoom ?? 0,
    maxzoom: Math.ceil(entry.maxzoom ?? 19),
    attribution: entry.attribution,
  };
  if (entry.bounds) source.bounds = entry.bounds;
  return source;
}

export function rasterBaseStyle(entry, apiBase) {
  return {
    version: 8,
    glyphs: GLYPHS_URL,
    sources: { "sw-base": rasterSource(entry, apiBase) },
    layers: [
      { id: "sw-base-background", type: "background", paint: { "background-color": "#0b1622" } },
      { id: "sw-base", type: "raster", source: "sw-base" },
    ],
  };
}

export class LiveMapEngine {
  constructor({ maplibregl, container, viewport, baseLayerId, customTemplate, apiBase = "", onSelect, onViewChange, onSourceError, onReady }) {
    if (!maplibregl?.Map) throw new Error("MapLibre GL JS is unavailable.");
    this.maplibregl = maplibregl;
    this.apiBase = apiBase;
    this.onSelect = onSelect || (() => {});
    this.onViewChange = onViewChange || (() => {});
    this.onSourceError = onSourceError || (() => {});
    this.overlays = new Set();
    this.timers = new Map();
    this.data = { aircraft: EMPTY, trails: EMPTY, trackLabels: EMPTY, rings: EMPTY, you: EMPTY };
    this.visibility = { aircraftWebGL: true, aircraftPositions: true, aircraftTrails: true, yourPosition: true, rangeRings: true };
    this.dim = { enabled: true, amount: 0.45 };
    this.destroyed = false;
    this.customTemplate = customTemplate || "";
    this.baseLayerId = baseLayerId;
    this.images = null;

    const base = this.resolveBase(baseLayerId);
    this.map = new maplibregl.Map({
      container,
      style: base.kind === "vector-style" ? base.styleUrl : rasterBaseStyle(base, apiBase),
      center: viewport.center,
      zoom: viewport.zoom,
      bearing: 0,
      pitch: 0,
      attributionControl: false,
      maxPitch: 0,
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
    });
    this.map.touchZoomRotate?.disableRotation?.();
    this.attribution = new maplibregl.AttributionControl({ compact: false });
    this.map.addControl(this.attribution, "bottom-right");
    this.scale = new maplibregl.ScaleControl({ unit: "nautical", maxWidth: 110 });
    this.map.addControl(this.scale, "bottom-left");

    this.map.on("styleimagemissing", (event) => this.addMissingImage(event.id));
    this.map.on("style.load", () => this.installLayers());
    this.map.on("load", () => onReady?.(this));
    this.map.on("moveend", () => this.onViewChange(this.view()));
    this.map.on("click", (event) => this.handleClick(event));
    for (const layer of AIRCRAFT_LAYERS) {
      this.map.on("mouseenter", layer, () => { this.map.getCanvas().style.cursor = "pointer"; });
      this.map.on("mouseleave", layer, () => { this.map.getCanvas().style.cursor = ""; });
    }
    this.map.on("error", (event) => {
      const sourceId = event?.sourceId || event?.source?.id || null;
      this.onSourceError(sourceId, event?.error?.message || "map error");
    });
  }

  resolveBase(id) {
    if (id === "custom_tiles" && this.customTemplate) return customBaseLayer(this.customTemplate);
    return findBaseLayer(id) || BASE_LAYERS[1];
  }

  view() {
    const bounds = this.map.getBounds();
    const center = this.map.getCenter();
    return {
      center: [center.lng, center.lat],
      zoom: this.map.getZoom(),
      bounds: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()],
    };
  }

  // ── base layers ────────────────────────────────────────────────────────────
  setBaseLayer(id, customTemplate = this.customTemplate) {
    if (this.destroyed) return;
    this.customTemplate = customTemplate;
    this.baseLayerId = id;
    const base = this.resolveBase(id);
    const next = base.kind === "vector-style" ? base.styleUrl : rasterBaseStyle(base, this.apiBase);
    this.map.setStyle(next, {
      diff: false,
      transformStyle: (previous, incoming) => {
        const keepSources = Object.fromEntries(
          Object.entries(previous?.sources || {}).filter(([key]) => key.startsWith("sw-") && key !== "sw-base"),
        );
        const keepLayers = (previous?.layers || []).filter((layer) => layer.id.startsWith("sw-") && !layer.id.startsWith("sw-base"));
        return {
          ...incoming,
          glyphs: incoming.glyphs || GLYPHS_URL,
          sources: { ...incoming.sources, ...keepSources },
          layers: [...incoming.layers, ...keepLayers],
        };
      },
    });
  }

  // ── images ─────────────────────────────────────────────────────────────────
  addMissingImage(id) {
    if (!id?.startsWith("sw-ac-")) return;
    if (!this.images) this.images = createAircraftImages();
    for (const { id: imageId, image, options } of this.images) {
      if (!this.map.hasImage(imageId)) this.map.addImage(imageId, image, options);
    }
  }

  // ── our layers ─────────────────────────────────────────────────────────────
  installLayers() {
    if (this.destroyed) return;
    const map = this.map;
    const ensureSource = (id, data, attribution) => {
      if (!map.getSource(id)) map.addSource(id, { type: "geojson", data, ...(attribution ? { attribution } : {}) });
    };
    ensureSource("sw-dim", WORLD);
    ensureSource("sw-rings", this.data.rings);
    ensureSource("sw-trails", this.data.trails);
    ensureSource("sw-track-labels", this.data.trackLabels);
    ensureSource("sw-you", this.data.you);
    ensureSource("sw-aircraft", this.data.aircraft, AIRCRAFT_ATTRIBUTION);
    const add = (layer, before) => { if (!map.getLayer(layer.id)) map.addLayer(layer, before && map.getLayer(before) ? before : undefined); };

    add({ id: "sw-dim", type: "fill", source: "sw-dim", paint: { "fill-color": "#000", "fill-opacity": this.dim.enabled ? this.dim.amount : 0 } });
    add({ id: TOP_LAYER, type: "line", source: "sw-rings", filter: ["==", ["get", "kind"], "ring"], paint: { "line-color": "#0b0b0b", "line-width": 1.2, "line-opacity": 0.85 } });
    add({ id: "sw-rings-label", type: "symbol", source: "sw-rings", filter: ["==", ["get", "kind"], "ring-label"], layout: { "text-field": ["get", "label"], "text-font": LABEL_FONT, "text-size": 11, "text-offset": [0, -0.8] }, paint: { "text-color": "#fff", "text-halo-color": "#000", "text-halo-width": 1.2 } });
    add({ id: "sw-trails", type: "line", source: "sw-trails", layout: { "line-cap": "round" }, paint: { "line-color": ["get", "color"], "line-width": 2, "line-opacity": ["case", ["get", "stale"], 0.4, 0.9] } });
    add({ id: "sw-track-labels", type: "symbol", source: "sw-track-labels", layout: { "text-field": ["get", "label"], "text-font": LABEL_FONT, "text-size": 10, "text-anchor": "left", "text-offset": [0.6, 0], "text-allow-overlap": false }, paint: { "text-color": "#fff", "text-halo-color": "#000", "text-halo-width": 1.2 } });
    add({ id: "sw-you", type: "circle", source: "sw-you", paint: { "circle-radius": 6, "circle-color": "#2f81f7", "circle-stroke-color": "#fff", "circle-stroke-width": 2 } });
    add({ id: "sw-aircraft-dots", type: "circle", source: "sw-aircraft", paint: { "circle-radius": ["case", ["get", "selected"], 6, 4], "circle-color": ["get", "color"], "circle-stroke-color": ["case", ["get", "selected"], "#fff", "#000"], "circle-stroke-width": 1, "circle-opacity": ["case", ["get", "stale"], 0.45, 1] } });
    add({
      id: "sw-aircraft",
      type: "symbol",
      source: "sw-aircraft",
      layout: {
        "symbol-sort-key": ["get", "sortKey"],
        "icon-image": ["get", "icon"],
        "icon-size": ["interpolate", ["linear"], ["zoom"], 3, ["*", 0.5, SHAPE_SCALE], 8, ["*", 0.8, SHAPE_SCALE], 12, ["*", 1, SHAPE_SCALE]],
        "icon-rotate": ["get", "track"],
        "icon-rotation-alignment": "map",
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
        "text-field": ["get", "label"],
        "text-font": LABEL_FONT,
        "text-size": 11,
        "text-anchor": "top",
        "text-offset": [0, 1.2],
        "text-optional": true,
        "text-allow-overlap": false,
      },
      paint: {
        "icon-color": ["get", "color"],
        "icon-halo-color": ["case", ["get", "emergency"], "#ff1f1f", ["get", "selected"], "#ffffff", "#000000"],
        "icon-halo-width": ["case", ["get", "selected"], 2, ["get", "emergency"], 2, 1],
        "icon-opacity": ["case", ["get", "stale"], 0.5, 1],
        "text-color": "#ffffff",
        "text-halo-color": "#000000",
        "text-halo-width": 1.4,
      },
    });
    for (const id of this.overlays) this.installOverlay(id);
    this.applyVisibility();
    this.applyDim();
  }

  setData(key, sourceId, data) {
    this.data[key] = data;
    if (this.destroyed) return;
    const source = this.map.getSource(sourceId);
    if (source?.setData) source.setData(data);
  }

  setAircraft(collection) { this.setData("aircraft", "sw-aircraft", collection); }
  setTrails(collection) { this.setData("trails", "sw-trails", collection); }
  setTrackLabels(collection) { this.setData("trackLabels", "sw-track-labels", collection); }
  setRangeRings(collection) { this.setData("rings", "sw-rings", collection); }
  setYourPosition(lonLat) {
    this.setData("you", "sw-you", lonLat ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: lonLat } }] } : EMPTY);
  }

  setFeatureVisibility(visibility) {
    this.visibility = { ...this.visibility, ...visibility };
    this.applyVisibility();
  }

  applyVisibility() {
    if (this.destroyed || !this.map.getLayer("sw-aircraft")) return;
    const v = this.visibility;
    const show = (id, on) => this.map.getLayer(id) && this.map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    show("sw-aircraft", v.aircraftPositions && v.aircraftWebGL);
    show("sw-aircraft-dots", v.aircraftPositions && !v.aircraftWebGL);
    show("sw-trails", v.aircraftTrails);
    show("sw-track-labels", v.aircraftTrails);
    show("sw-you", v.yourPosition);
    show(TOP_LAYER, v.rangeRings);
    show("sw-rings-label", v.rangeRings);
  }

  setDim(enabled, amount) {
    this.dim = { enabled: Boolean(enabled), amount: Math.min(0.9, Math.max(0, Number(amount) || 0)) };
    this.applyDim();
  }

  applyDim() {
    if (this.destroyed || !this.map.getLayer("sw-dim")) return;
    this.map.setPaintProperty("sw-dim", "fill-opacity", this.dim.enabled ? this.dim.amount : 0);
  }

  setScaleUnit(unit) {
    this.scale?.setUnit?.(unit);
  }

  // ── overlays ───────────────────────────────────────────────────────────────
  setOverlay(id, visible) {
    if (this.destroyed) return;
    if (visible) {
      this.overlays.add(id);
      if (this.map.getLayer(TOP_LAYER)) this.installOverlay(id);
    } else {
      this.overlays.delete(id);
      this.removeOverlay(id);
    }
  }

  overlayLayerIds(id) {
    return [`sw-ov-${id}`, `sw-ov-${id}-fill`, `sw-ov-${id}-line`, `sw-ov-${id}-label`];
  }

  removeOverlay(id) {
    clearInterval(this.timers.get(id));
    this.timers.delete(id);
    for (const layerId of this.overlayLayerIds(id)) if (this.map.getLayer(layerId)) this.map.removeLayer(layerId);
    if (this.map.getSource(`sw-ov-${id}`)) this.map.removeSource(`sw-ov-${id}`);
  }

  installOverlay(id) {
    const entry = findOverlay(id);
    if (!entry || this.map.getSource(`sw-ov-${id}`)) return;
    const sourceId = `sw-ov-${id}`;
    const opacity = entry.opacity ?? 1;
    if (entry.kind === "raster") {
      this.map.addSource(sourceId, rasterSource(entry, this.apiBase));
      this.map.addLayer({ id: sourceId, type: "raster", source: sourceId, paint: { "raster-opacity": opacity } }, TOP_LAYER);
      if (entry.refreshMs) {
        this.timers.set(id, setInterval(() => {
          this.map.getSource(sourceId)?.setTiles?.(resolveTiles(entry, { now: new Date(), apiBase: this.apiBase }));
        }, entry.refreshMs));
      }
    } else if (entry.kind === "geojson") {
      this.map.addSource(sourceId, { type: "geojson", data: entry.url, attribution: entry.attribution });
      const polygons = ["match", ["geometry-type"], ["Polygon", "MultiPolygon"], true, false];
      this.map.addLayer({ id: `${sourceId}-fill`, type: "fill", source: sourceId, filter: polygons, paint: { "fill-color": entry.fill, "fill-opacity": opacity } }, TOP_LAYER);
      this.map.addLayer({ id: `${sourceId}-line`, type: "line", source: sourceId, paint: { "line-color": entry.stroke, "line-width": entry.lineWidth || 1, "line-opacity": opacity } }, TOP_LAYER);
      if (entry.showLabel) {
        this.map.addLayer({
          id: `${sourceId}-label`, type: "symbol", source: sourceId,
          layout: { "text-field": entry.labelExpression || ["coalesce", ["get", entry.labelField || "name"], ""], "text-font": LABEL_FONT, "text-size": 12 },
          paint: { "text-color": "#000", "text-halo-color": "#fff", "text-halo-width": 2 },
        }, TOP_LAYER);
      }
      if (entry.refreshMs) {
        this.timers.set(id, setInterval(() => this.map.getSource(sourceId)?.setData?.(entry.url), entry.refreshMs));
      }
    } else if (entry.kind === "rainviewer") {
      this.installRainViewer(entry, sourceId, opacity);
    }
  }

  async rainViewerTiles(entry) {
    const response = await fetch(entry.indexUrl, { credentials: "omit" });
    if (!response.ok) throw new Error(`RainViewer index HTTP ${response.status}`);
    const maps = await response.json();
    const past = maps?.radar?.past || [];
    if (!past.length) throw new Error("RainViewer index lists no radar frames");
    return [`${maps.host}${past[past.length - 1].path}/512/{z}/{x}/{y}/6/1_1.png`];
  }

  async installRainViewer(entry, sourceId, opacity) {
    try {
      const tiles = await this.rainViewerTiles(entry);
      if (this.destroyed || !this.overlays.has(entry.id) || this.map.getSource(sourceId)) return;
      this.map.addSource(sourceId, { type: "raster", tiles, tileSize: entry.tileSize, maxzoom: entry.maxzoom, attribution: entry.attribution });
      this.map.addLayer({ id: sourceId, type: "raster", source: sourceId, paint: { "raster-opacity": opacity } }, TOP_LAYER);
      this.timers.set(entry.id, setInterval(async () => {
        try {
          this.map.getSource(sourceId)?.setTiles?.(await this.rainViewerTiles(entry));
        } catch (error) {
          this.onSourceError(sourceId, error.message);
        }
      }, entry.refreshMs));
    } catch (error) {
      this.onSourceError(sourceId, error.message);
    }
  }

  // ── interaction ────────────────────────────────────────────────────────────
  handleClick(event) {
    const pad = 8;
    const box = [[event.point.x - pad, event.point.y - pad], [event.point.x + pad, event.point.y + pad]];
    const layers = AIRCRAFT_LAYERS.filter((id) => this.map.getLayer(id));
    const hit = layers.length ? this.map.queryRenderedFeatures(box, { layers }) : [];
    const hex = hit[0]?.properties?.hex || null;
    this.onSelect(hex, { additive: Boolean(event.originalEvent?.ctrlKey || event.originalEvent?.metaKey) });
  }

  flyTo(center, zoom) {
    if (this.destroyed) return;
    this.map.easeTo({ center, zoom: zoom ?? this.map.getZoom(), duration: 600 });
  }

  panTo(center) {
    if (!this.destroyed) this.map.panTo(center, { duration: 400 });
  }

  zoomBy(delta) {
    if (!this.destroyed) this.map.easeTo({ zoom: this.map.getZoom() + delta, duration: 250 });
  }

  resize() {
    if (!this.destroyed) this.map.resize();
  }

  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    for (const timer of this.timers.values()) clearInterval(timer);
    this.timers.clear();
    this.map.remove();
  }
}

export const OVERLAY_IDS = OVERLAYS.map((entry) => entry.id);
