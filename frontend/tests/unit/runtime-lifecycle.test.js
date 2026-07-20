import { describe, expect, it, vi } from 'vitest';
import { BLANK_OFFLINE_STYLE } from '@/components/console/BlankOfflineStyle';
import { MapRuntimeAdapter } from '@/components/console/MapRuntimeAdapter';
import { RuntimeResourceLedger, getGlobalDiagnostics, updateGlobalDiagnostics } from '@/components/console/RuntimeResourceLedger';
import { probeWebGL } from '@/components/console/WebGLCapabilityProbe';

class FakeMap {
  constructor(options) {
    this.options = options;
    this.handlers = new Map();
    this.controls = [];
    this.sources = new Map();
    this.layers = new Map();
    this.center = { lng: -66.45, lat: 18.22 };
    this.zoom = 7;
    this.bearing = 0;
    this.pitch = 0;
    this.removeCount = 0;
    this.resizeCount = 0;
  }

  on(name, handler) { this.handlers.set(name, handler); }
  off(name, handler) { if (this.handlers.get(name) === handler) this.handlers.delete(name); }
  emit(name, payload) { this.handlers.get(name)?.(payload); }
  addControl(control) { this.controls.push(control); }
  removeControl(control) { this.controls = this.controls.filter((item) => item !== control); }
  getCenter() { return this.center; }
  getZoom() { return this.zoom; }
  getBearing() { return this.bearing; }
  getPitch() { return this.pitch; }
  resize() { this.resizeCount += 1; }
  remove() { this.removeCount += 1; }
  easeTo(options) {
    if (options.center) this.center = { lng: options.center[0], lat: options.center[1] };
    if (options.zoom !== undefined) this.zoom = options.zoom;
    if (options.bearing !== undefined) this.bearing = options.bearing;
    if (options.pitch !== undefined) this.pitch = options.pitch;
  }
  setStyle(style) { this.style = style; }
  addSource(id, source) { this.sources.set(id, { ...source, setData: (data) => { this.sources.get(id).data = data; } }); }
  getSource(id) { return this.sources.get(id); }
  removeSource(id) { this.sources.delete(id); }
  addLayer(layer) { this.layers.set(layer.id, layer); }
  getLayer(id) { return this.layers.get(id); }
  removeLayer(id) { this.layers.delete(id); }
}

class FakeObserver {
  constructor(callback) { this.callback = callback; this.disconnectCount = 0; }
  observe() { this.observed = true; }
  disconnect() { this.disconnectCount += 1; }
}

function createHarness() {
  let map;
  let observer;
  const adapter = new MapRuntimeAdapter({
    mapFactory: (options) => { map = new FakeMap(options); return map; },
    attributionFactory: () => ({ id: 'attribution' }),
    navigationFactory: () => ({ id: 'navigation' }),
    resizeObserverFactory: (callback) => { observer = new FakeObserver(callback); return observer; },
  });
  return { adapter, get map() { return map; }, get observer() { return observer; } };
}

describe('MapRuntimeAdapter lifecycle', () => {
  it('creates, reports viewport changes, displays location, and tears down every resource', () => {
    updateGlobalDiagnostics({ mapsCreated: 0, mapsRemoved: 0, observersCreated: 0, observersDisconnected: 0 });
    const harness = createHarness();
    const ready = vi.fn();
    const viewport = vi.fn();
    harness.adapter.create({
      container: document.createElement('div'),
      style: BLANK_OFFLINE_STYLE,
      onReady: ready,
      onViewportChange: viewport,
    });
    expect(harness.map.options.attributionControl).toBe(false);
    expect(harness.map.options.renderWorldCopies).toBe(false);
    harness.map.emit('load');
    harness.map.emit('moveend');
    expect(ready).toHaveBeenCalledOnce();
    expect(viewport).toHaveBeenCalledWith(expect.objectContaining({ longitude: -66.45, zoom: 7 }));

    expect(harness.adapter.showUserLocation({ longitude: -66, latitude: 18, accuracy: 15 })).toBe(true);
    expect(harness.map.getSource('skywatcher-user-location')).toBeTruthy();
    expect(harness.adapter.showUserLocation({ longitude: -66.1, latitude: 18.1, accuracy: 10 })).toBe(true);
    expect(harness.adapter.setViewport({ longitude: -67, latitude: 18.5, zoom: 9, bearing: 2, pitch: 3 })).toBe(true);
    expect(harness.adapter.setStyle(BLANK_OFFLINE_STYLE)).toBe(true);

    harness.observer.callback();
    expect(harness.map.resizeCount).toBe(1);
    const result = harness.adapter.destroy();
    expect(result.balanced).toBe(true);
    expect(harness.map.removeCount).toBe(1);
    expect(harness.observer.disconnectCount).toBe(1);
    expect(harness.adapter.destroy().balanced).toBe(true);
    expect(getGlobalDiagnostics()).toMatchObject({ mapsCreated: 1, mapsRemoved: 1, observersCreated: 1, observersDisconnected: 1 });
  });

  it('survives 25 mount/unmount cycles without resource growth', () => {
    for (let index = 0; index < 25; index += 1) {
      const harness = createHarness();
      harness.adapter.create({ container: document.createElement('div'), style: BLANK_OFFLINE_STYLE });
      harness.map.emit('load');
      expect(harness.adapter.destroy().active).toBe(0);
    }
  });

  it('records runtime errors and cleans a partially created map', () => {
    const onError = vi.fn();
    const harness = createHarness();
    harness.adapter.create({ container: document.createElement('div'), style: BLANK_OFFLINE_STYLE, onError });
    harness.map.emit('error', { error: new Error('boom') });
    expect(onError).toHaveBeenCalled();
    expect(harness.adapter.diagnostics().lastError).toBe('boom');
    harness.adapter.destroy();
  });

  it('rejects missing containers and uncreated operations', () => {
    const adapter = new MapRuntimeAdapter();
    expect(() => adapter.create({ style: BLANK_OFFLINE_STYLE })).toThrow(/container/);
    expect(adapter.setViewport({})).toBe(false);
    expect(adapter.setStyle(BLANK_OFFLINE_STYLE)).toBe(false);
    expect(adapter.showUserLocation({ longitude: 0, latitude: 0 })).toBe(false);
  });
});

describe('resource ledger and WebGL probe', () => {
  it('runs cleanup once and reports balance', () => {
    const ledger = new RuntimeResourceLedger();
    const cleanup = vi.fn();
    const token = ledger.acquire('listener', 'test', cleanup);
    expect(ledger.snapshot().active).toBe(1);
    expect(ledger.release(token)).toBe(true);
    expect(ledger.release(token)).toBe(false);
    expect(cleanup).toHaveBeenCalledOnce();
    expect(ledger.assertBalanced().balanced).toBe(true);
  });

  it('detects supported and unsupported contexts', () => {
    const supported = probeWebGL({ createElement: () => ({ getContext: (name) => (name === 'webgl2' ? {} : null) }) });
    expect(supported).toMatchObject({ supported: true, context: 'webgl2' });
    const unsupported = probeWebGL({ createElement: () => ({ getContext: () => null }) });
    expect(unsupported).toMatchObject({ supported: false, reason: 'webgl_unavailable' });
    expect(probeWebGL(null).reason).toBe('document_unavailable');
  });
});
