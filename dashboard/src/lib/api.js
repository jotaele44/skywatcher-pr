// REST client for the skywatcher-pr FastAPI backend.
// Backend: from_spiderweb/server/backend/main.py  (uvicorn ... --port 8000)
//
// IMPORTANT — the backend returns camelCase keys for event/anomaly fields
// (siteId, aircraftType, altitudeFt, groundSpeedMph, flightStatus, originCode,
//  destinationCode, imagePath, refId; anomalies: siteId, factors[], contracts[],
//  events[], band, score, confidence). Components must read those exact keys.
//
// Every call DEGRADES GRACEFULLY: on network/HTTP error it resolves to a
// sentinel (the provided fallback) instead of throwing — this powers the
// "endpoint unavailable" UI for the optional pipeline/RAG routes and for any
// /geo/* layer that 404s.

import snapshot from './snapshot.json' // {} in normal builds; populated for VITE_OFFLINE exports
export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

// Offline export build: resolve from an embedded data snapshot instead of fetching.
// (A file:// page cannot fetch at all, so standalone exports bake the data in.)
const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

async function getJSON(path, fallback = null) {
  if (OFFLINE) {
    const key = path.split('?')[0] // server-side filters degrade to the unfiltered snapshot
    return key in snapshot ? snapshot[key] : fallback
  }
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      signal: AbortSignal.timeout(8000),
    })
    if (!res.ok) return fallback
    return await res.json()
  } catch {
    return fallback
  }
}

// ── Health ────────────────────────────────────────────────────────────────
export const getHealth = () =>
  getJSON('/health', { status: 'down', db_exists: false, integrity_ok: false })

// ── Entities (read) ─────────────────────────────────────────────────────────
export const getSites = () => getJSON('/sites', [])
export const getEvents = () => getJSON('/events', [])
export const getEventTrack = (id) => getJSON(`/events/${encodeURIComponent(id)}/track`, [])
export const getAnomalies = () => getJSON('/anomalies', [])
export const getSources = () => getJSON('/sources', [])
export const getAlerts = () => getJSON('/alerts', [])
export const getInvestigations = () => getJSON('/investigations', [])
export const getAgencies = () => getJSON('/agencies', [])
export const getVendors = () => getJSON('/vendors', [])
export const getContracts = () => getJSON('/contracts', [])

// ── GeoJSON layers (progressive enhancement; null when unavailable) ─────────
// allowlist: flights, sites, anomalies, corridors, heatmap, municipios,
//            tracts, places, barrios
export const getGeoLayer = (layer) => getJSON(`/geo/${layer}.geojson`, null)

// ── Optional: pipeline control (scripts may be absent → {available:false}) ──
export async function runPipeline(body = {}) {
  try {
    const res = await fetch(`${API_BASE}/pipeline/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) return { available: false }
    return await res.json()
  } catch {
    return { available: false }
  }
}

// ── Optional: streaming RAG query (SSE). Returns an abort fn. ────────────────
export function streamRagQuery(payload, { onToken, onDone, onError }) {
  const controller = new AbortController()
  fetch(`${API_BASE}/rag/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      for (;;) {
        const { done, value } = await reader.read()
        if (done) { onDone?.(); break }
        const chunk = decoder.decode(value, { stream: true })
        for (const line of chunk.split('\n').filter(Boolean)) {
          const text = line.startsWith('data:') ? line.slice(5).trim() : line
          if (text === '[DONE]') { onDone?.(); return }
          onToken?.(text)
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') onError?.(err.message || 'RAG endpoint unavailable')
    })
  return () => controller.abort()
}
