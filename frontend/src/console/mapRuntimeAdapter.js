import { getBasemap } from "./basemapRegistry.js";
import { installRegisteredLayers, setRegisteredLayerVisibility } from "./layerRegistry.js";
import { selectionToGeoJSON } from "./selectionState.js";
import { normalizeViewport, viewportFromMap } from "./viewportState.js";
import { isCapabilityEnabled } from "./capabilityGate.js";

function setSelectionData(map, selection) {
  const source = map.getSource("console-selection-source");
  if (source?.setData) source.setData(selectionToGeoJSON(selection));
}

export function createMapRuntime({
  maplibregl,
  container,
  capabilityIndex = {},
  basemapId,
  viewport,
  selection,
  layerVisibility = {},
  geolocationAvailable = typeof navigator !== "undefined" && Boolean(navigator.geolocation),
  onViewportChange = () => {},
  onSelectionChange = () => {},
  onLoad = () => {},
}) {
  if (!maplibregl?.Map) throw new Error("MapLibre GL JS runtime is unavailable.");
  if (!container) throw new Error("Map container is required.");

  const basemap = getBasemap(basemapId);
  const initialViewport = normalizeViewport(viewport);
  const map = new maplibregl.Map({
    container,
    style: basemap.style,
    center: initialViewport.center,
    zoom: initialViewport.zoom,
    bearing: initialViewport.bearing,
    pitch: initialViewport.pitch,
    attributionControl: false,
    cooperativeGestures: true,
    maxPitch: 85,
  });

  const controls = [];
  const handlers = [];
  let destroyed = false;

  const addControl = (control, position) => {
    map.addControl(control, position);
    controls.push(control);
  };

  if (maplibregl.AttributionControl) {
    addControl(new maplibregl.AttributionControl({ compact: false, customAttribution: basemap.attribution }), "bottom-right");
  }
  if (maplibregl.NavigationControl && isCapabilityEnabled(capabilityIndex, "map_navigation")) {
    addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
  }
  if (maplibregl.GeolocateControl && geolocationAvailable && isCapabilityEnabled(capabilityIndex, "geolocation")) {
    addControl(new maplibregl.GeolocateControl({
      positionOptions: { enableHighAccuracy: true },
      trackUserLocation: false,
      showUserHeading: true,
    }), "top-right");
  }

  const bind = (eventName, handler) => {
    map.on(eventName, handler);
    handlers.push([eventName, handler]);
  };

  const install = () => {
    installRegisteredLayers(map, capabilityIndex, layerVisibility);
    setSelectionData(map, selection);
    onLoad({ map, basemap, capabilityIndex });
  };

  bind("load", install);
  bind("moveend", () => onViewportChange(viewportFromMap(map)));
  bind("click", (event) => {
    const coordinate = [event.lngLat.lng, event.lngLat.lat];
    onSelectionChange({ type: "coordinate", coordinate });
  });

  return {
    map,
    basemap,
    resize: () => { if (!destroyed) map.resize(); },
    updateSelection: (nextSelection) => { if (!destroyed) setSelectionData(map, nextSelection); },
    setLayerVisibility: (layerId, visible) => {
      if (!destroyed) setRegisteredLayerVisibility(map, layerId, visible);
    },
    resetViewport: (nextViewport) => {
      if (!destroyed) map.jumpTo(normalizeViewport(nextViewport));
    },
    destroy: () => {
      if (destroyed) return;
      destroyed = true;
      for (const [eventName, handler] of handlers) map.off(eventName, handler);
      for (const control of controls) {
        try { map.removeControl(control); } catch { /* control may already be detached */ }
      }
      map.remove();
    },
  };
}
