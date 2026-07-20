import { isCapabilityEnabled } from "./capabilityGate.js";

const emptyCollection = () => ({ type: "FeatureCollection", features: [] });

export const LAYER_REGISTRY = Object.freeze([
  {
    id: "diagnostic-pr-extent",
    label: "PR diagnostic extent",
    capabilityId: null,
    sourceId: "diagnostic-pr-extent-source",
    source: {
      type: "geojson",
      data: {
        type: "FeatureCollection",
        features: [{
          type: "Feature",
          properties: { diagnostic_only: true, authoritative_boundary: false },
          geometry: {
            type: "Polygon",
            coordinates: [[[-67.5, 17.75], [-65.15, 17.75], [-65.15, 18.65], [-67.5, 18.65], [-67.5, 17.75]]],
          },
        }],
      },
    },
    layers: [{
      id: "diagnostic-pr-extent-line",
      type: "line",
      paint: { "line-color": "#22d3ee", "line-opacity": 0.55, "line-width": 1.5, "line-dasharray": [3, 2] },
    }],
    defaultVisible: true,
  },
  {
    id: "selection",
    label: "Current selection",
    capabilityId: null,
    sourceId: "console-selection-source",
    source: { type: "geojson", data: emptyCollection() },
    layers: [{
      id: "console-selection-halo",
      type: "circle",
      paint: {
        "circle-radius": 9,
        "circle-color": "#fbbf24",
        "circle-opacity": 0.22,
        "circle-stroke-color": "#fbbf24",
        "circle-stroke-width": 2,
      },
    }],
    defaultVisible: true,
  },
  {
    id: "aircraft-states",
    label: "Aircraft states",
    capabilityId: "aircraft_viewport_list",
    sourceId: "console-aircraft-source",
    source: { type: "geojson", data: emptyCollection() },
    layers: [{
      id: "console-aircraft-points",
      type: "circle",
      paint: { "circle-radius": 4, "circle-color": "#38bdf8", "circle-opacity": 0.9 },
    }],
    defaultVisible: false,
  },
  {
    id: "routes",
    label: "Track and route evidence",
    capabilityId: "playback_timeline",
    sourceId: "console-routes-source",
    source: { type: "geojson", data: emptyCollection() },
    layers: [{
      id: "console-route-lines",
      type: "line",
      paint: { "line-color": "#a78bfa", "line-width": 2, "line-opacity": 0.8 },
    }],
    defaultVisible: false,
  },
  {
    id: "airports",
    label: "Puerto Rico airports",
    capabilityId: "airport_detail",
    sourceId: "console-airports-source",
    source: { type: "geojson", data: emptyCollection() },
    layers: [{
      id: "console-airport-points",
      type: "circle",
      paint: { "circle-radius": 5, "circle-color": "#34d399", "circle-stroke-color": "#052e2b", "circle-stroke-width": 1 },
    }],
    defaultVisible: false,
  },
]);

export function availableLayers(capabilityIndex = {}) {
  return LAYER_REGISTRY.filter((entry) => isCapabilityEnabled(capabilityIndex, entry.capabilityId));
}

export function installRegisteredLayers(map, capabilityIndex = {}, visibility = {}) {
  const installed = [];
  for (const entry of availableLayers(capabilityIndex)) {
    if (!map.getSource(entry.sourceId)) map.addSource(entry.sourceId, structuredClone(entry.source));
    const visible = visibility[entry.id] ?? entry.defaultVisible;
    for (const layer of entry.layers) {
      if (!map.getLayer(layer.id)) {
        map.addLayer({ ...structuredClone(layer), source: entry.sourceId, layout: { ...(layer.layout || {}), visibility: visible ? "visible" : "none" } });
      }
    }
    installed.push(entry.id);
  }
  return installed;
}

export function setRegisteredLayerVisibility(map, layerId, visible) {
  const entry = LAYER_REGISTRY.find((candidate) => candidate.id === layerId);
  if (!entry) throw new Error(`Unknown console layer: ${layerId}`);
  for (const layer of entry.layers) {
    if (map.getLayer(layer.id)) map.setLayoutProperty(layer.id, "visibility", visible ? "visible" : "none");
  }
}
