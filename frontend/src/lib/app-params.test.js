import { describe, expect, it } from 'vitest';

import { createMemoryStorage, resolveStorage } from './app-params';

describe('app parameter storage capability', () => {
  it('preserves string values with the Web Storage interface', () => {
    const storage = createMemoryStorage();
    storage.setItem('count', 3);
    expect(storage.getItem('count')).toBe('3');
    storage.removeItem('count');
    expect(storage.getItem('count')).toBeNull();
  });

  it('falls back when storage is absent or access throws', () => {
    expect(resolveStorage({}).getItem('missing')).toBeNull();
    const restricted = {};
    Object.defineProperty(restricted, 'localStorage', {
      get: () => { throw new DOMException('blocked', 'SecurityError'); },
    });
    expect(resolveStorage(restricted).getItem('missing')).toBeNull();
  });
});
