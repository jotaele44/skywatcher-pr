import { useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import { bandHex } from '@/lib/format'

// MapLibre GL wrapper (replaces the scaffold's Leaflet MapView).
//
// The map data is built CLIENT-SIDE from the JSON read endpoints (/sites,
// /anomalies, /events/{id}/track) — it does NOT depend on /geo/*.geojson files
// existing on disk. Anomalies are positioned by joining anomaly.siteId → site.
//
// Keyless OSM raster basemap so it renders with no Mapbox/MapTiler token.
const OSM_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://a.tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors',
    },
  },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#0b1220' } },
    { id: 'osm', type: 'raster', source: 'osm', paint: { 'raster-opacity': 0.85, 'raster-saturation': -0.3 } },
  ],
}

const PR_CENTER = [-66.4, 18.22]

const empty = { type: 'FeatureCollection', features: [] }

function sitesFC(sites = []) {
  return {
    type: 'FeatureCollection',
    features: sites
      .filter((s) => s.lat != null && s.lng != null)
      .map((s) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [s.lng, s.lat] },
        properties: { id: s.id, name: s.name, kind: s.kind, sensitive: s.sensitive ? 1 : 0 },
      })),
  }
}

function anomaliesFC(anomalies = [], sites = []) {
  const byId = new Map(sites.map((s) => [s.id, s]))
  return {
    type: 'FeatureCollection',
    features: anomalies
      .map((a) => {
        const site = byId.get(a.siteId)
        if (!site || site.lat == null) return null
        return {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [site.lng, site.lat] },
          properties: { id: a.id, title: a.title, band: a.band, score: a.score, color: bandHex(a.band) },
        }
      })
      .filter(Boolean),
  }
}

function trackFC(track = []) {
  const coords = track.filter((p) => p.lat != null && p.lng != null).map((p) => [p.lng, p.lat])
  if (coords.length < 2) return empty
  return {
    type: 'FeatureCollection',
    features: [{ type: 'Feature', geometry: { type: 'LineString', coordinates: coords }, properties: {} }],
  }
}

export default function MapView({ sites = [], anomalies = [], track = [], onSelectSite, onSelectAnomaly }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const readyRef = useRef(false)
  // keep latest handlers without re-running the init effect
  const handlers = useRef({ onSelectSite, onSelectAnomaly })
  handlers.current = { onSelectSite, onSelectAnomaly }

  // init once
  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: OSM_STYLE,
      center: PR_CENTER,
      zoom: 8.3,
      attributionControl: true,
    })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

    map.on('load', () => {
      map.addSource('sites', { type: 'geojson', data: empty })
      map.addSource('anomalies', { type: 'geojson', data: empty })
      map.addSource('track', { type: 'geojson', data: empty })

      map.addLayer({
        id: 'track-line', type: 'line', source: 'track',
        paint: { 'line-color': '#38bdf8', 'line-width': 3, 'line-opacity': 0.9 },
      })
      map.addLayer({
        id: 'sites-dot', type: 'circle', source: 'sites',
        paint: {
          'circle-radius': 6,
          'circle-color': ['case', ['==', ['get', 'sensitive'], 1], '#f97316', '#22d3ee'],
          'circle-stroke-color': '#0b1220', 'circle-stroke-width': 1.5,
        },
      })
      map.addLayer({
        id: 'anomalies-dot', type: 'circle', source: 'anomalies',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['coalesce', ['get', 'score'], 0.5], 0, 8, 1, 18],
          'circle-color': ['get', 'color'], 'circle-opacity': 0.35,
          'circle-stroke-color': ['get', 'color'], 'circle-stroke-width': 2,
        },
      })

      readyRef.current = true
      // paint whatever props arrived before load
      map.getSource('sites').setData(sitesFC(sitesRef.current))
      map.getSource('anomalies').setData(anomaliesFC(anomaliesRef.current, sitesRef.current))
      map.getSource('track').setData(trackFC(trackRef.current))

      const pointer = (id) => {
        map.on('mouseenter', id, () => (map.getCanvas().style.cursor = 'pointer'))
        map.on('mouseleave', id, () => (map.getCanvas().style.cursor = ''))
      }
      pointer('sites-dot'); pointer('anomalies-dot')
      map.on('click', 'sites-dot', (e) => handlers.current.onSelectSite?.(e.features[0].properties))
      map.on('click', 'anomalies-dot', (e) => handlers.current.onSelectAnomaly?.(e.features[0].properties))
    })

    return () => { readyRef.current = false; map.remove() }
  }, [])

  // refs mirror latest props so the load handler can read them
  const sitesRef = useRef(sites); sitesRef.current = sites
  const anomaliesRef = useRef(anomalies); anomaliesRef.current = anomalies
  const trackRef = useRef(track); trackRef.current = track

  // push prop updates into the map sources
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return
    mapRef.current.getSource('sites')?.setData(sitesFC(sites))
    mapRef.current.getSource('anomalies')?.setData(anomaliesFC(anomalies, sites))
  }, [sites, anomalies])

  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return
    const fc = trackFC(track)
    mapRef.current.getSource('track')?.setData(fc)
    if (fc.features.length) {
      const b = new maplibregl.LngLatBounds()
      fc.features[0].geometry.coordinates.forEach((c) => b.extend(c))
      mapRef.current.fitBounds(b, { padding: 80, maxZoom: 11, duration: 700 })
    }
  }, [track])

  // h-full (not absolute inset-0): maplibre-gl.css sets `.maplibregl-map{position:relative}`
  // which loads after Tailwind and would override `absolute`, collapsing the height to 0.
  return <div ref={containerRef} className="h-full w-full" />
}
