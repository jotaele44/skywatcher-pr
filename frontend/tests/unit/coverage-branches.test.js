import { describe, expect, it, vi } from 'vitest';
import { assertOfflineStyle, BLANK_OFFLINE_STYLE, collectExternalStyleReferences } from '@/components/console/BlankOfflineStyle';
import { getBasemap, validateBasemapRegistry } from '@/components/console/BasemapRegistry';
import { validateLayerRegistry } from '@/components/console/LayerRegistry';
import { isExternalUrl } from '@/components/console/OfflineRequestGuard';
import { capabilityById, resolveCapability } from '@/components/console/capabilityPolicy';
import { ConsoleApiClient, loadConsoleBootstrap } from '@/components/console/ConsoleApiClient';
import { consoleStateReducer, INITIAL_CONSOLE_STATE } from '@/components/console/consoleState';
import { MapRuntimeAdapter } from '@/components/console/MapRuntimeAdapter';
import { RuntimeResourceLedger, updateGlobalDiagnostics } from '@/components/console/RuntimeResourceLedger';
import { probeWebGL } from '@/components/console/WebGLCapabilityProbe';

class BranchMap {
  constructor({ throwRemoveControl = false } = {}) {
    this.handlers = new Map();
    this.controls = [];
    this.sources = new Map();
    this.layers = new Map();
    this.throwRemoveControl = throwRemoveControl;
    this.center = { lng: -66, lat: 18 };
  }
  on(name, fn) { this.handlers.set(name, fn); }
  off(name) { this.handlers.delete(name); }
  emit(name, value) { this.handlers.get(name)?.(value); }
  addControl(control) { this.controls.push(control); }
  removeControl() { if (this.throwRemoveControl) throw new Error('already removed'); }
  getCenter() { return this.center; }
  getZoom() { return 7; }
  getBearing() { return 0; }
  getPitch() { return 0; }
  resize() {}
  remove() {}
  easeTo() {}
  setStyle() {}
  addSource(id, source) { this.sources.set(id, { ...source, setData: vi.fn() }); }
  getSource(id) { return this.sources.get(id); }
  removeSource(id) { this.sources.delete(id); }
  addLayer(layer) { this.layers.set(layer.id, layer); }
  getLayer(id) { return this.layers.get(id); }
  removeLayer(id) { this.layers.delete(id); }
}

const observerFactory = () => ({ observe() {}, disconnect() {} });
const adapterFor = (map) => new MapRuntimeAdapter({
  mapFactory: () => map,
  attributionFactory: () => ({}),
  navigationFactory: () => ({}),
  resizeObserverFactory: observerFactory,
});

describe('defensive branch coverage', () => {
  it('covers all registry validation outcomes', () => {
    expect(validateBasemapRegistry([{ id: 'local', configured: false, offline: false, attribution: 'a', style: null }])).toBe(true);
    expect(getBasemap('local', [{ id: 'local', configured: false, offline: false, attribution: 'a', style: null }]).id).toBe('local');
    expect(() => validateBasemapRegistry([{ configured: false, attribution: 'a' }])).toThrow(/missing/);
    expect(() => validateBasemapRegistry([{ id: 'x', configured: false, attribution: 'a' }, { id: 'x', configured: false, attribution: 'a' }])).toThrow(/duplicate/);
    expect(() => validateBasemapRegistry([{ id: 'x', configured: true, attribution: 'a' }])).toThrow(/include a style/);
    expect(() => validateBasemapRegistry([{ id: 'x', configured: true, offline: true, attribution: 'a', style: { version: 8, sources: { x: { tiles: ['https://x'] } }, layers: [] } }])).toThrow(/prohibited/);

    expect(validateLayerRegistry([{ id: 'x', enabledByDefault: true, requiredCapabilities: [], dataEndpoint: '/x' }])).toBe(true);
    expect(() => validateLayerRegistry([{ requiredCapabilities: [] }])).toThrow(/missing/);
    expect(() => validateLayerRegistry([{ id: 'x', requiredCapabilities: [] }, { id: 'x', requiredCapabilities: [] }])).toThrow(/duplicate/);
    expect(() => validateLayerRegistry([{ id: 'x', requiredCapabilities: null }])).toThrow(/requiredCapabilities/);
  });

  it('covers style traversal and URL parsing fallbacks', () => {
    expect(() => assertOfflineStyle(null)).toThrow(/version 8/);
    expect(collectExternalStyleReferences({ version: 8, sources: [{ value: null }, 'plain'], layers: [] })).toEqual([]);
    expect(isExternalUrl('', { origin: 'http://local' })).toBe(false);
    expect(isExternalUrl('http://[invalid', { origin: 'http://local' })).toBe(true);
    expect(isExternalUrl('http://other', null)).toBe(false);
  });

  it('covers capability and state fallbacks', () => {
    expect(capabilityById(null, 'x')).toBeNull();
    expect(resolveCapability({ capabilities: [{ id: 'x', status: 'available_synthetic_only', reason: '' }], capabilityId: 'x' })).toEqual({ enabled: true, reason: 'available_synthetic_only', status: 'available_synthetic_only' });
    expect(resolveCapability({ capabilities: [{ id: 'x', status: 'degraded', reason: 'partial' }], capabilityId: 'x' }).enabled).toBe(false);

    let state = consoleStateReducer(INITIAL_CONSOLE_STATE, { type: 'selection/set' });
    expect(state.selectedEntity).toBeNull();
    state = consoleStateReducer(state, { type: 'runtime/status', status: 'error' });
    expect(state.webglSupported).toBeNull();
    state = consoleStateReducer(state, { type: 'bootstrap/ready' });
    expect(state.capabilities).toEqual([]);
    expect(state.repositories).toEqual([]);
    state = consoleStateReducer(state, { type: 'bootstrap/error' });
    expect(state.runtimeError).toBe('Console API unavailable.');
    state = consoleStateReducer(state, { type: 'geolocation/status', status: 'idle' });
    expect(state.geolocation).toBeNull();
  });

  it('covers API defaults and empty query strings', async () => {
    const request = vi.fn(async (path) => ({ path }));
    const client = new ConsoleApiClient(request);
    await client.capabilities();
    await client.repositories();
    await client.aircraftStates({ a: undefined, b: null, c: '' });
    expect(request).toHaveBeenLastCalledWith('/console/aircraft/states', { signal: undefined });
    await expect(loadConsoleBootstrap()).rejects.toThrow();
  });

  it('covers adapter idempotency, optional callbacks, error shapes, and cleanup catches', () => {
    const map = new BranchMap({ throwRemoveControl: true });
    const adapter = adapterFor(map);
    const container = document.createElement('div');
    expect(adapter.create({ container, style: BLANK_OFFLINE_STYLE })).toBe(map);
    expect(adapter.create({ container, style: BLANK_OFFLINE_STYLE })).toBe(map);
    map.emit('moveend');
    map.emit('error', { message: 'message-only' });
    expect(adapter.diagnostics().runtimeStatus).toBe('error');
    map.emit('load');
    map.emit('error', {});
    expect(adapter.diagnostics().runtimeStatus).toBe('ready');
    adapter.showUserLocation({ longitude: -66, latitude: 18 });
    expect(map.getSource('skywatcher-user-location')).toBeTruthy();
    expect(() => adapter.setStyle({ version: 8, sprite: 'https://remote', sources: {}, layers: [] })).toThrow(/prohibited/);
    expect(adapter.destroy().balanced).toBe(true);
    expect(map.sources.size).toBe(0);
    expect(map.layers.size).toBe(0);
  });

  it('cleans a partially initialized adapter and handles map-factory failure', () => {
    const map = new BranchMap();
    const adapter = new MapRuntimeAdapter({
      mapFactory: () => map,
      attributionFactory: () => ({}),
      navigationFactory: () => ({}),
      resizeObserverFactory: () => { throw new Error('observer failed'); },
    });
    expect(() => adapter.create({ container: document.createElement('div'), style: BLANK_OFFLINE_STYLE })).toThrow('observer failed');
    expect(adapter.diagnostics().resources.balanced).toBe(true);

    const failed = new MapRuntimeAdapter({ mapFactory: () => { throw new Error('factory failed'); } });
    expect(() => failed.create({ container: document.createElement('div'), style: BLANK_OFFLINE_STYLE })).toThrow('factory failed');
    expect(failed.destroy().balanced).toBe(true);
  });

  it('covers ledger no-cleanup and leak detection branches', () => {
    const ledger = new RuntimeResourceLedger();
    const cleanup = vi.fn();
    const token = ledger.acquire('x', 'x', cleanup);
    expect(ledger.release(token, { runCleanup: false })).toBe(true);
    expect(cleanup).not.toHaveBeenCalled();
    ledger.acquire('y');
    expect(() => ledger.assertBalanced()).toThrow(/resource leak/);
    ledger.releaseAll();
    expect(ledger.assertBalanced().balanced).toBe(true);
    expect(updateGlobalDiagnostics({ runtimeStatus: 'test' }).runtimeStatus).toBe('test');
  });

  it('constructs the default non-map runtime helpers', () => {
    const adapter = new MapRuntimeAdapter();
    expect(adapter.attributionFactory()).toBeTruthy();
    expect(adapter.navigationFactory()).toBeTruthy();
    const observer = adapter.resizeObserverFactory(() => {});
    expect(observer).toBeTruthy();
    observer.disconnect();
  });

  it('continues probing when a context constructor throws', () => {
    const getContext = vi.fn((name) => {
      if (name === 'webgl2') throw new Error('no webgl2');
      return name === 'webgl' ? {} : null;
    });
    expect(probeWebGL({ createElement: () => ({ getContext }) })).toMatchObject({ supported: true, context: 'webgl' });
  });
});
