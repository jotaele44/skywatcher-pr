// Client for the backend live-feed endpoints (/api/console/live/*) that back
// the /live airspace map. Upstream outages come back in-band as
// { status: "upstream_unavailable", reason } so callers can render them.
import { federation } from '@/api/federationClient';
import { appParams } from '@/lib/app-params';

const bboxParam = (bbox) => bbox.map((value) => Number(value).toFixed(4)).join(',');

export const liveClient = {
  apiBase() {
    return (appParams.apiBaseUrl || '/api').replace(/\/+$/, '');
  },

  status(options = {}) {
    return federation.request('/console/live/status', options);
  },

  aircraft(bbox, { military = false, hexes = [], signal } = {}) {
    const params = new URLSearchParams({ bbox: bboxParam(bbox) });
    if (military) params.set('military', 'true');
    if (hexes.length) params.set('hex', hexes.slice(0, 20).join(','));
    return federation.request(`/console/live/aircraft?${params}`, { signal });
  },

  trace(hex, { date, signal } = {}) {
    const params = date ? `?${new URLSearchParams({ date })}` : '';
    return federation.request(`/console/live/trace/${encodeURIComponent(hex)}${params}`, { signal });
  },

  replay(tsIso, bbox, { windowS = 300, signal } = {}) {
    const params = new URLSearchParams({ ts: tsIso, bbox: bboxParam(bbox), window_s: String(windowS) });
    return federation.request(`/console/live/replay?${params}`, { signal });
  },

  routes(planes, { signal } = {}) {
    return federation.request('/console/live/routes', { method: 'POST', body: { planes }, signal });
  },
};
