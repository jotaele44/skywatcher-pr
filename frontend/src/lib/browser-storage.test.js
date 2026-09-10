import { afterEach, expect, it, vi } from 'vitest';
import { browserStorage } from './browser-storage';
afterEach(() => vi.restoreAllMocks());
it('keeps the session usable when browser storage access is forbidden', () => {
  vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => { throw new Error('SecurityError'); });
  expect(browserStorage.getItem('missing')).toBeNull();
  browserStorage.setItem('restricted-token', 'secret');
  expect(browserStorage.getItem('restricted-token')).toBe('secret');
  browserStorage.removeItem('restricted-token');
  expect(browserStorage.getItem('restricted-token')).toBeNull();
});
it('does not revive a token when persistent removal fails', () => {
  vi.spyOn(window, 'localStorage', 'get').mockReturnValue({ getItem: () => 'old-secret', removeItem: () => { throw new Error('denied'); } });
  browserStorage.removeItem('stale-token');
  expect(browserStorage.getItem('stale-token')).toBeNull();
});
