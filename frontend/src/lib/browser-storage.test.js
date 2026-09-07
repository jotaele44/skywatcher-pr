import { describe, expect, it } from 'vitest';
import { createResilientStorage } from './browser-storage.js';

describe('storage availability', () => {
  it.each([() => undefined, () => ({}), () => { throw new Error('denied'); }])(
    'retains session settings when browser storage is unavailable', (getStorage) => {
      const store = createResilientStorage(getStorage);
      expect(store.getItem('setting')).toBeNull();
      store.setItem('setting', 42);
      expect(store.getItem('setting')).toBe('42');
      store.removeItem('setting');
      expect(store.getItem('setting')).toBeNull();
    },
  );
  it('does not resurrect a cleared token when removal is denied', () => {
    const store = createResilientStorage(() => ({
      getItem: () => 'stale-token', removeItem: () => { throw new Error('denied'); },
    }));
    expect(store.getItem('token')).toBe('stale-token');
    store.removeItem('token');
    expect(store.getItem('token')).toBeNull();
  });
  it('persists through the native storage interface when available', () => {
    const values = new Map();
    const native = { getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) };
    const store = createResilientStorage(() => native);
    store.setItem('setting', 'value');
    expect(values.get('setting')).toBe('value');
    expect(createResilientStorage(() => native).getItem('setting')).toBe('value');
    store.removeItem('setting');
    expect(values.has('setting')).toBe(false);
  });
});
