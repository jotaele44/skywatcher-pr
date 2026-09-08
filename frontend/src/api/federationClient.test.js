import { afterEach, expect, it, vi } from 'vitest';
import { federation, setWriteToken } from './federationClient';
import { appParams } from '@/lib/app-params';

vi.mock('@/lib/app-params', () => ({ appParams: { apiBaseUrl: '/api', token: null, writeToken: null } }));

afterEach(() => {
  federation.auth.setToken(null);
  setWriteToken(null);
  vi.unstubAllGlobals();
});

it('does not revive startup URL tokens after clearing or replacing credentials', async () => {
  const fetch = vi.fn().mockImplementation(async () => new Response('{}', {
    headers: { 'Content-Type': 'application/json' },
  }));
  vi.stubGlobal('fetch', fetch);
  appParams.token = 'stale-access-token';
  appParams.writeToken = 'stale-write-token';
  federation.auth.setToken(null);
  setWriteToken('replacement-write-token');
  await federation.request('/entities/ManualReviewItems');
  expect(fetch.mock.calls[0][1].headers.get('Authorization')).toBe('Bearer replacement-write-token');
  setWriteToken(null);
  await federation.request('/entities/ManualReviewItems');
  expect(fetch.mock.calls[1][1].headers.has('Authorization')).toBe(false);
});

it('retains the backend rejection reason', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
    JSON.stringify({ detail: 'Write access denied' }), { status: 403 },
  )));
  await expect(federation.request('/entities/ManualReviewItems')).rejects.toMatchObject({
    message: 'Write access denied', status: 403,
  });
});
