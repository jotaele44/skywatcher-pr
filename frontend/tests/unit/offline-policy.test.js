import { describe, expect, it } from 'vitest';
import { assertOfflineStyle, BLANK_OFFLINE_STYLE, collectExternalStyleReferences } from '@/components/console/BlankOfflineStyle';
import { BASEMAP_REGISTRY, getBasemap, validateBasemapRegistry } from '@/components/console/BasemapRegistry';
import { LAYER_REGISTRY, validateLayerRegistry } from '@/components/console/LayerRegistry';
import { createOfflineTransformRequest, enforceOfflineMapPolicy, isExternalUrl } from '@/components/console/OfflineRequestGuard';
import { DEFAULT_VIEWPORT, isConsoleEnabled } from '@/components/console/consoleDefaults';

const locationRef = { origin: 'http://127.0.0.1:4173' };

describe('offline console policy', () => {
  it('ships a provider-free version 8 blank style', () => {
    expect(assertOfflineStyle(BLANK_OFFLINE_STYLE)).toBe(BLANK_OFFLINE_STYLE);
    expect(collectExternalStyleReferences(BLANK_OFFLINE_STYLE)).toEqual([]);
    expect(BLANK_OFFLINE_STYLE.sources).toEqual({});
    expect(enforceOfflineMapPolicy(BLANK_OFFLINE_STYLE)).toEqual({ externalRequestsAllowed: false, styleValidated: true });
  });

  it('rejects remote URLs and credentials anywhere in a style', () => {
    const unsafe = {
      version: 8,
      sprite: 'https://tiles.example/sprite',
      metadata: { api_key: 'secret' },
      sources: {},
      layers: [],
    };
    expect(collectExternalStyleReferences(unsafe)).toHaveLength(2);
    expect(() => assertOfflineStyle(unsafe)).toThrow(/prohibited external references/);
  });

  it('blocks external transform requests while allowing local, data, and blob URLs', () => {
    const transform = createOfflineTransformRequest(locationRef);
    expect(transform('/local/style.json')).toEqual({ url: '/local/style.json' });
    expect(transform('data:application/json,{}')).toEqual({ url: 'data:application/json,{}' });
    expect(transform('blob:http://127.0.0.1:4173/worker')).toEqual({ url: 'blob:http://127.0.0.1:4173/worker' });
    expect(() => transform('https://tiles.example/1/2/3')).toThrow(/external map request blocked/);
    expect(isExternalUrl('https://tiles.example/a', locationRef)).toBe(true);
    expect(isExternalUrl('/assets/a.js', locationRef)).toBe(false);
  });

  it('validates basemap and layer registries fail closed', () => {
    expect(validateBasemapRegistry()).toBe(true);
    expect(getBasemap('missing').id).toBe(BASEMAP_REGISTRY[0].id);
    expect(() => validateBasemapRegistry([{ id: 'x', configured: true, attribution: '', style: BLANK_OFFLINE_STYLE }])).toThrow(/attribution/);
    expect(validateLayerRegistry(LAYER_REGISTRY)).toBe(true);
    expect(() => validateLayerRegistry([{ id: 'x', enabledByDefault: true, requiredCapabilities: [], dataEndpoint: null }])).toThrow(/data endpoint/);
  });

  it('keeps the feature flag reversible and viewport bounded', () => {
    expect(isConsoleEnabled({})).toBe(true);
    expect(isConsoleEnabled({ VITE_SKYWATCHER_CONSOLE_ENABLED: 'false' })).toBe(false);
    expect(DEFAULT_VIEWPORT.longitude).toBeCloseTo(-66.45);
  });
});
