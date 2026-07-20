import { BASEMAP_REGISTRY } from './BasemapRegistry';
import { DEFAULT_VIEWPORT } from './consoleDefaults';
import { LAYER_REGISTRY } from './LayerRegistry';

export const INITIAL_CONSOLE_STATE = Object.freeze({
  viewport: DEFAULT_VIEWPORT,
  selectedEntity: null,
  selectedEntityType: null,
  activeBasemapId: BASEMAP_REGISTRY[0].id,
  visibleLayerIds: Object.freeze(LAYER_REGISTRY.filter((item) => item.enabledByDefault).map((item) => item.id)),
  runtimeStatus: 'idle',
  runtimeError: null,
  webglSupported: null,
  capabilities: Object.freeze([]),
  capabilityPolicy: Object.freeze({}),
  repositories: Object.freeze([]),
  bootstrapStatus: 'idle',
  geolocationStatus: 'idle',
  geolocation: null,
});

export function consoleStateReducer(state, action) {
  switch (action.type) {
    case 'viewport/set':
      return { ...state, viewport: { ...state.viewport, ...action.viewport } };
    case 'selection/set':
      return { ...state, selectedEntity: action.entity || null, selectedEntityType: action.entityType || null };
    case 'selection/clear':
      return { ...state, selectedEntity: null, selectedEntityType: null };
    case 'basemap/set':
      return { ...state, activeBasemapId: action.basemapId };
    case 'layer/toggle': {
      const current = new Set(state.visibleLayerIds);
      if (current.has(action.layerId)) current.delete(action.layerId);
      else current.add(action.layerId);
      return { ...state, visibleLayerIds: [...current].sort() };
    }
    case 'runtime/status':
      return {
        ...state,
        runtimeStatus: action.status,
        runtimeError: action.error || null,
        webglSupported: action.webglSupported ?? state.webglSupported,
      };
    case 'bootstrap/loading':
      return { ...state, bootstrapStatus: 'loading' };
    case 'bootstrap/ready':
      return {
        ...state,
        bootstrapStatus: 'ready',
        capabilities: action.capabilities?.capabilities || [],
        capabilityPolicy: action.capabilities?.policy || {},
        repositories: action.repositories?.repositories || [],
      };
    case 'bootstrap/error':
      return { ...state, bootstrapStatus: 'degraded', runtimeError: action.error || 'Console API unavailable.' };
    case 'geolocation/status':
      return { ...state, geolocationStatus: action.status, geolocation: action.location ?? state.geolocation };
    default:
      return state;
  }
}
