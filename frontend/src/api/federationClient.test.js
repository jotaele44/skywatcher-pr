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

it('does not infer anonymous access from a settings transport failure', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Offline')));
  await expect(federation.system.publicSettings()).rejects.toThrow('Offline');
});

it.each([null, {}, { public_settings: {} }, { public_settings: { requires_auth: 'false' } }])(
  'rejects malformed authentication policy %j', async payload => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
      headers: { 'Content-Type': 'application/json' },
    })));
    await expect(federation.system.publicSettings()).rejects.toThrow('invalid authentication policy');
  },
);

it.each([true, false])('retains explicit authentication requirement %s', async required => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ public_settings: { requires_auth: required } }), {
    headers: { 'Content-Type': 'application/json' },
  })));
  expect((await federation.system.publicSettings()).public_settings.requires_auth).toBe(required);
});
