import { useCallback, useEffect, useState } from "react";
import { appParams } from "@/lib/app-params";

// Finishes the track-playback feature left half-built by the original GIS
// rollout: the backend has always shipped GET /api/geo/tracks/{icao24}.geojson
// (a full ADS-B LineString for one aircraft), but no UI ever called it.
// Scrubbing truncates the rendered line to points up to the selected time and
// drops a marker at the current head, driven entirely off this component's
// own fetches so it works on any page that mounts PuertoRicoMapShell.
export default function TrackTimeScrubber({ map, mapReady }) {
  const [available, setAvailable] = useState([]);
  const [icao24, setIcao24] = useState("");
  const [track, setTrack] = useState(null);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetch(`${appParams.apiBaseUrl}/geo/tracks`)
      .then((res) => (res.ok ? res.json() : []))
      .then((rows) => {
        if (!cancelled) setAvailable(rows);
      })
      .catch(() => {
        if (!cancelled) setAvailable([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!icao24) {
      setTrack(null);
      return;
    }
    let cancelled = false;
    fetch(`${appParams.apiBaseUrl}/geo/tracks/${encodeURIComponent(icao24)}.geojson`)
      .then((res) => (res.ok ? res.json() : null))
      .then((geojson) => {
        if (cancelled) return;
        const feature = geojson?.features?.[0] ?? null;
        setTrack(feature);
        setIndex(feature ? feature.geometry.coordinates.length - 1 : 0);
      })
      .catch(() => {
        if (!cancelled) setTrack(null);
      });
    return () => {
      cancelled = true;
    };
  }, [icao24]);

  const coords = track?.geometry?.coordinates ?? [];

  const ensureLayers = useCallback(() => {
    if (!map || map.getSource("track-scrubber-line")) return;
    map.addSource("track-scrubber-line", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({
      id: "track-scrubber-line-layer", type: "line", source: "track-scrubber-line",
      layout: { "line-join": "round", "line-cap": "round" },
      paint: { "line-color": "hsl(142 70% 50%)", "line-width": 2.5 },
    });
    map.addSource("track-scrubber-head", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({
      id: "track-scrubber-head-layer", type: "circle", source: "track-scrubber-head",
      paint: { "circle-radius": 6, "circle-color": "hsl(142 70% 50%)", "circle-stroke-color": "#0b1220", "circle-stroke-width": 1.5 },
    });
  }, [map]);

  useEffect(() => {
    if (!map || !mapReady) return;
    if (map.isStyleLoaded()) ensureLayers();
    else map.once("styledata", ensureLayers);
  }, [map, mapReady, ensureLayers]);

  useEffect(() => {
    if (!map || !mapReady || !map.getSource("track-scrubber-line")) return;
    const sliced = coords.slice(0, index + 1);
    map.getSource("track-scrubber-line")?.setData({
      type: "FeatureCollection",
      features: sliced.length >= 2 ? [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: sliced } }] : [],
    });
    const head = sliced[sliced.length - 1];
    map.getSource("track-scrubber-head")?.setData({
      type: "FeatureCollection",
      features: head ? [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: head } }] : [],
    });
  }, [map, mapReady, coords, index]);

  useEffect(() => {
    return () => {
      if (!map) return;
      map.getSource("track-scrubber-line")?.setData({ type: "FeatureCollection", features: [] });
      map.getSource("track-scrubber-head")?.setData({ type: "FeatureCollection", features: [] });
    };
  }, [map]);

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-2.5 text-[11px]">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Track playback:</span>
      <select
        value={icao24}
        onChange={(e) => setIcao24(e.target.value)}
        className="rounded-md border border-border bg-secondary/40 px-1.5 py-0.5 text-[10px] text-foreground"
      >
        <option value="">
          {available.length === 0 ? "No tracks available" : "Select an aircraft"}
        </option>
        {available.map((a) => (
          <option key={a.icao24} value={a.icao24}>
            {a.callsign || a.icao24} ({a.point_count} pts)
          </option>
        ))}
      </select>
      {coords.length >= 2 && (
        <input
          type="range"
          min={0}
          max={coords.length - 1}
          value={index}
          onChange={(e) => setIndex(Number(e.target.value))}
          className="h-1 max-w-[200px] flex-1 accent-[hsl(142_70%_50%)]"
        />
      )}
      {coords.length >= 2 && (
        <span className="font-mono text-[10px] text-muted-foreground">
          {index + 1} / {coords.length}
        </span>
      )}
    </div>
  );
}
