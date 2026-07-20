import maplibregl from 'maplibre-gl';
import { assertOfflineStyle } from './BlankOfflineStyle';
import { DEFAULT_MAX_BOUNDS, DEFAULT_VIEWPORT } from './consoleDefaults';
import { createOfflineTransformRequest } from './OfflineRequestGuard';
import { getGlobalDiagnostics, RuntimeResourceLedger, updateGlobalDiagnostics } from './RuntimeResourceLedger';

const USER_SOURCE_ID = 'skywatcher-user-location';
const USER_ACCURACY_LAYER_ID = 'skywatcher-user-location-accuracy';
const USER_POINT_LAYER_ID = 'skywatcher-user-location-point';

function viewportFromMap(map) {
  const center = map.getCenter();
  return {
    longitude: center.lng,
    latitude: center.lat,
    zoom: map.getZoom(),
    bearing: map.getBearing(),
    pitch: map.getPitch(),
  };
}

function userLocationGeoJSON({ longitude, latitude, accuracy = 0 }) {
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { accuracy },
        geometry: { type: 'Point', coordinates: [longitude, latitude] },
      },
    ],
  };
}

export class MapRuntimeAdapter {
  constructor({
    mapFactory = (options) => new maplibregl.Map(options),
    attributionFactory = () => new maplibregl.AttributionControl({
      compact: false,
      customAttribution: 'Skywatcher-PR diagnostic console',
    }),
    navigationFactory = () => new maplibregl.NavigationControl({
      showCompass: true,
      showZoom: true,
      visualizePitch: true,
    }),
    resizeObserverFactory = (callback) => new ResizeObserver(callback),
    ledger = new RuntimeResourceLedger(),
  } = {}) {
    this.mapFactory = mapFactory;
    this.attributionFactory = attributionFactory;
    this.navigationFactory = navigationFactory;
    this.resizeObserverFactory = resizeObserverFactory;
    this.ledger = ledger;
    this.map = null;
    this.runtimeStatus = 'idle';
    this.lastError = null;
  }

  create({
    container,
    style,
    viewport = DEFAULT_VIEWPORT,
    maxBounds = DEFAULT_MAX_BOUNDS,
    onViewportChange,
    onReady,
    onError,
  }) {
    if (this.map) return this.map;
    if (!container) throw new Error('map container is required');
    assertOfflineStyle(style);
    this.runtimeStatus = 'initializing';
    updateGlobalDiagnostics({ runtimeStatus: 'initializing', lastError: null });

    try {
      const map = this.mapFactory({
        container,
        style,
        center: [viewport.longitude, viewport.latitude],
        zoom: viewport.zoom,
        bearing: viewport.bearing,
        pitch: viewport.pitch,
        maxBounds,
        renderWorldCopies: false,
        attributionControl: false,
        transformRequest: createOfflineTransformRequest(),
      });
      this.map = map;
      updateGlobalDiagnostics({
        mapsCreated: getGlobalDiagnostics().mapsCreated + 1,
      });

      this.ledger.acquire('map', 'MapLibre map', () => {
        try {
          map.remove();
        } finally {
          updateGlobalDiagnostics({
            mapsRemoved: getGlobalDiagnostics().mapsRemoved + 1,
          });
        }
      });

      const attribution = this.attributionFactory();
      map.addControl(attribution, 'bottom-right');
      this.ledger.acquire('control', 'attribution control', () => {
        try { map.removeControl(attribution); } catch { /* map may already be removing */ }
      });

      const navigation = this.navigationFactory();
      map.addControl(navigation, 'top-right');
      this.ledger.acquire('control', 'navigation control', () => {
        try { map.removeControl(navigation); } catch { /* map may already be removing */ }
      });

      const handleMoveEnd = () => onViewportChange?.(viewportFromMap(map));
      map.on('moveend', handleMoveEnd);
      this.ledger.acquire('listener', 'moveend', () => map.off('moveend', handleMoveEnd));

      const handleLoad = () => {
        this.runtimeStatus = 'ready';
        updateGlobalDiagnostics({ runtimeStatus: 'ready', lastError: null });
        onReady?.(this.diagnostics());
      };
      map.on('load', handleLoad);
      this.ledger.acquire('listener', 'load', () => map.off('load', handleLoad));

      const handleError = (event) => {
        const message = event?.error?.message || event?.message || 'MapLibre runtime error';
        this.lastError = message;
        if (this.runtimeStatus !== 'ready') this.runtimeStatus = 'error';
        updateGlobalDiagnostics({ runtimeStatus: this.runtimeStatus, lastError: message });
        onError?.(new Error(message));
      };
      map.on('error', handleError);
      this.ledger.acquire('listener', 'error', () => map.off('error', handleError));

      const observer = this.resizeObserverFactory(() => map.resize());
      observer.observe(container);
      updateGlobalDiagnostics({
        observersCreated: getGlobalDiagnostics().observersCreated + 1,
      });
      this.ledger.acquire('observer', 'ResizeObserver', () => {
        observer.disconnect();
        updateGlobalDiagnostics({
          observersDisconnected: getGlobalDiagnostics().observersDisconnected + 1,
        });
      });

      return map;
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      this.runtimeStatus = 'error';
      updateGlobalDiagnostics({ runtimeStatus: 'error', lastError: this.lastError });
      this.destroy();
      throw error;
    }
  }

  setViewport(viewport, options = {}) {
    if (!this.map) return false;
    this.map.easeTo({
      center: [viewport.longitude, viewport.latitude],
      zoom: viewport.zoom,
      bearing: viewport.bearing,
      pitch: viewport.pitch,
      duration: options.duration ?? 0,
    });
    return true;
  }

  setStyle(style) {
    if (!this.map) return false;
    assertOfflineStyle(style);
    this.map.setStyle(style);
    return true;
  }

  showUserLocation({ longitude, latitude, accuracy = 0 }) {
    if (!this.map) return false;
    const data = userLocationGeoJSON({ longitude, latitude, accuracy });
    const existing = /** @type {import('maplibre-gl').GeoJSONSource | undefined} */ (this.map.getSource(USER_SOURCE_ID));
    if (existing?.setData) {
      existing.setData(data);
    } else {
      this.map.addSource(USER_SOURCE_ID, { type: 'geojson', data });
      this.ledger.acquire('source', USER_SOURCE_ID, () => {
        if (this.map?.getSource(USER_SOURCE_ID)) this.map.removeSource(USER_SOURCE_ID);
      });
      this.map.addLayer({
        id: USER_ACCURACY_LAYER_ID,
        type: 'circle',
        source: USER_SOURCE_ID,
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 8, 12, 30],
          'circle-color': 'rgba(56,189,248,0.12)',
          'circle-stroke-color': 'rgba(56,189,248,0.45)',
          'circle-stroke-width': 1,
        },
      });
      this.ledger.acquire('layer', USER_ACCURACY_LAYER_ID, () => {
        if (this.map?.getLayer(USER_ACCURACY_LAYER_ID)) this.map.removeLayer(USER_ACCURACY_LAYER_ID);
      });
      this.map.addLayer({
        id: USER_POINT_LAYER_ID,
        type: 'circle',
        source: USER_SOURCE_ID,
        paint: {
          'circle-radius': 5,
          'circle-color': '#38bdf8',
          'circle-stroke-color': '#e0f2fe',
          'circle-stroke-width': 2,
        },
      });
      this.ledger.acquire('layer', USER_POINT_LAYER_ID, () => {
        if (this.map?.getLayer(USER_POINT_LAYER_ID)) this.map.removeLayer(USER_POINT_LAYER_ID);
      });
    }
    this.map.easeTo({ center: [longitude, latitude], zoom: Math.max(this.map.getZoom(), 10), duration: 500 });
    return true;
  }

  diagnostics() {
    return {
      runtimeStatus: this.runtimeStatus,
      lastError: this.lastError,
      resources: this.ledger.snapshot(),
    };
  }

  destroy() {
    if (!this.map && this.ledger.snapshot().active === 0) return this.ledger.snapshot();
    this.ledger.releaseAll();
    this.map = null;
    this.runtimeStatus = 'destroyed';
    updateGlobalDiagnostics({ runtimeStatus: 'destroyed' });
    return this.ledger.assertBalanced();
  }
}
