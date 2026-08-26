import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Radar, MapPin } from "lucide-react";
import { appParams } from "@/lib/app-params";

// Real MapLibre GL map of Puerto Rico airspace context, replacing the earlier
// hand-rolled SVG/projectToShell shell. Point props (observations/airports/
// assets) and the routes line prop are rendered as native GL layers; the
// infrastructure-zone and flight-corridor polygons and the observation
// heatmap are fetched directly from the backend's /api/geo/* endpoints,
// since those need real buffered geometry the flat prop shape doesn't carry.
const PR_CENTER = [-66.35, 18.2];

const MARKER_STYLES = {
  observation: "hsl(190 100% 55%)",
  airport: "hsl(38 100% 56%)",
  asset: "hsl(262 52% 66%)",
};

const OSM_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "hsl(220 34% 4%)" } },
    { id: "osm", type: "raster", source: "osm", paint: { "raster-opacity": 0.55, "raster-saturation": -0.4 } },
  ],
};

const EMPTY = { type: "FeatureCollection", features: [] };

function toPointCollection(rows, latKey = "latitude", lonKey = "longitude") {
  return {
    type: "FeatureCollection",
    features: rows
      .filter((r) => r[latKey] != null && r[lonKey] != null)
      .map((r) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [Number(r[lonKey]), Number(r[latKey])] },
        properties: r,
      })),
  };
}

function toLineCollection(rows) {
  return {
    type: "FeatureCollection",
    features: rows
      .filter((r) => r.start_lat != null && r.start_lon != null && r.end_lat != null && r.end_lon != null)
      .map((r) => ({
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: [
            [Number(r.start_lon), Number(r.start_lat)],
            [Number(r.end_lon), Number(r.end_lat)],
          ],
        },
        properties: r,
      })),
  };
}

async function fetchGeojson(path) {
  try {
    const res = await fetch(`${appParams.apiBaseUrl}${path}`);
    if (!res.ok) return EMPTY;
    return await res.json();
  } catch {
    return EMPTY;
  }
}

export default function PuertoRicoMapShell({
  observations = [],
  airports = [],
  assets = [],
  routes = [],
  height = 300,
  title = "Puerto Rico Airspace Context",
  diagnostic = true,
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const readyRef = useRef(false);
  const propsRef = useRef({ observations, airports, assets, routes });
  propsRef.current = { observations, airports, assets, routes };
  const [hover, setHover] = useState(null);
  const [showZones, setShowZones] = useState(true);
  const [showCorridors, setShowCorridors] = useState(true);
  const [showHeatmap, setShowHeatmap] = useState(false);

  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: OSM_STYLE,
      center: PR_CENTER,
      zoom: 8.2,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    map.on("style.load", async () => {
      const { observations: obs, airports: apt, assets: ast, routes: rte } = propsRef.current;

      map.addSource("routes", { type: "geojson", data: toLineCollection(rte) });
      map.addLayer({
        id: "routes-line", type: "line", source: "routes",
        paint: { "line-color": "hsl(190 100% 60%)", "line-width": 1.6, "line-dasharray": [3, 2], "line-opacity": 0.7 },
      });

      const [zones, corridors, heatmap] = await Promise.all([
        fetchGeojson("/geo/infrastructure.geojson"),
        fetchGeojson("/geo/corridors.geojson"),
        fetchGeojson("/geo/observations/heatmap.geojson"),
      ]);

      map.addSource("zones", { type: "geojson", data: zones });
      map.addLayer({
        id: "zones-fill", type: "fill", source: "zones",
        paint: { "fill-color": "hsl(0 84% 60%)", "fill-opacity": 0.08 },
        layout: { visibility: showZones ? "visible" : "none" },
      });
      map.addLayer({
        id: "zones-line", type: "line", source: "zones",
        paint: { "line-color": "hsl(0 84% 60% / 0.6)", "line-width": 1 },
        layout: { visibility: showZones ? "visible" : "none" },
      });

      map.addSource("corridors", { type: "geojson", data: corridors });
      map.addLayer({
        id: "corridors-fill", type: "fill", source: "corridors",
        paint: { "fill-color": "hsl(38 100% 56%)", "fill-opacity": 0.1 },
        layout: { visibility: showCorridors ? "visible" : "none" },
      });
      map.addLayer({
        id: "corridors-line", type: "line", source: "corridors",
        paint: { "line-color": "hsl(38 100% 56% / 0.6)", "line-width": 1, "line-dasharray": [2, 2] },
        layout: { visibility: showCorridors ? "visible" : "none" },
      });

      map.addSource("obs-heatmap", { type: "geojson", data: heatmap });
      map.addLayer({
        id: "obs-heatmap-layer", type: "heatmap", source: "obs-heatmap",
        paint: {
          "heatmap-weight": ["get", "intensity"],
          "heatmap-intensity": 1.1,
          "heatmap-radius": 22,
          "heatmap-opacity": 0.75,
        },
        layout: { visibility: showHeatmap ? "visible" : "none" },
      });

      map.addSource("assets", { type: "geojson", data: toPointCollection(ast) });
      map.addLayer({
        id: "assets-dot", type: "circle", source: "assets",
        paint: { "circle-radius": 4.5, "circle-color": MARKER_STYLES.asset, "circle-opacity": 0.85, "circle-stroke-color": "#0b1220", "circle-stroke-width": 1 },
      });

      map.addSource("airports", { type: "geojson", data: toPointCollection(apt) });
      map.addLayer({
        id: "airports-dot", type: "circle", source: "airports",
        paint: { "circle-radius": 5, "circle-color": MARKER_STYLES.airport, "circle-opacity": 0.9, "circle-stroke-color": "#0b1220", "circle-stroke-width": 1 },
      });

      map.addSource("observations", { type: "geojson", data: toPointCollection(obs) });
      map.addLayer({
        id: "observations-dot", type: "circle", source: "observations",
        paint: { "circle-radius": 3.5, "circle-color": MARKER_STYLES.observation, "circle-opacity": 0.9, "circle-stroke-color": "#0b1220", "circle-stroke-width": 0.5 },
      });

      readyRef.current = true;

      for (const layer of ["observations-dot", "airports-dot", "assets-dot", "zones-fill", "corridors-fill"]) {
        map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
        map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
        map.on("click", layer, (e) => {
          const f = e.features[0];
          setHover({ point: e.point, props: f.properties });
        });
      }
    });

    return () => { readyRef.current = false; map.remove(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!readyRef.current) return;
    mapRef.current.getSource("observations")?.setData(toPointCollection(observations));
  }, [observations]);
  useEffect(() => {
    if (!readyRef.current) return;
    mapRef.current.getSource("airports")?.setData(toPointCollection(airports));
  }, [airports]);
  useEffect(() => {
    if (!readyRef.current) return;
    mapRef.current.getSource("assets")?.setData(toPointCollection(assets));
  }, [assets]);
  useEffect(() => {
    if (!readyRef.current) return;
    mapRef.current.getSource("routes")?.setData(toLineCollection(routes));
  }, [routes]);

  useEffect(() => {
    if (!readyRef.current) return;
    mapRef.current.setLayoutProperty("zones-fill", "visibility", showZones ? "visible" : "none");
    mapRef.current.setLayoutProperty("zones-line", "visibility", showZones ? "visible" : "none");
  }, [showZones]);
  useEffect(() => {
    if (!readyRef.current) return;
    mapRef.current.setLayoutProperty("corridors-fill", "visibility", showCorridors ? "visible" : "none");
    mapRef.current.setLayoutProperty("corridors-line", "visibility", showCorridors ? "visible" : "none");
  }, [showCorridors]);
  useEffect(() => {
    if (!readyRef.current) return;
    mapRef.current.setLayoutProperty("obs-heatmap-layer", "visibility", showHeatmap ? "visible" : "none");
  }, [showHeatmap]);

  return (
    <div className="relative overflow-hidden rounded-xl border border-border bg-[hsl(220_34%_4%)]">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Radar className="h-4 w-4 text-primary" />
          <span className="text-xs font-bold uppercase tracking-wider text-foreground/90">{title}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <ToggleChip label="Zones" active={showZones} onClick={() => setShowZones((v) => !v)} />
          <ToggleChip label="Corridors" active={showCorridors} onClick={() => setShowCorridors((v) => !v)} />
          <ToggleChip label="Heatmap" active={showHeatmap} onClick={() => setShowHeatmap((v) => !v)} />
          {diagnostic && (
            <span className="ml-1 rounded-full border border-[hsl(262_52%_60%/0.35)] bg-[hsl(262_52%_60%/0.14)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[hsl(262_60%_76%)]">
              Diagnostic / Sample
            </span>
          )}
        </div>
      </div>

      <div className="relative">
        <div ref={containerRef} style={{ height }} className="w-full" />

        {hover && (
          <div
            className="pointer-events-none absolute z-10 max-w-[220px] rounded-md border border-border bg-popover px-2.5 py-1.5 text-[10px] shadow-lg"
            style={{ left: hover.point.x, top: hover.point.y, transform: "translate(-50%, -120%)" }}
          >
            <p className="font-semibold text-foreground">
              {hover.props.callsign || hover.props.airport_name || hover.props.asset_name || hover.props.name || "Record"}
            </p>
            {hover.props.latitude != null && (
              <p className="font-mono text-muted-foreground">
                {Number(hover.props.latitude).toFixed(3)}, {Number(hover.props.longitude).toFixed(3)}
              </p>
            )}
            {hover.props.type && <p className="text-muted-foreground">{hover.props.type}</p>}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-4 py-2 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full" style={{ background: MARKER_STYLES.observation }} /> Observation</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full" style={{ background: MARKER_STYLES.airport }} /> Airport</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full" style={{ background: MARKER_STYLES.asset }} /> Infrastructure</span>
        <span className="flex items-center gap-1.5"><span className="inline-block h-0 w-3 border-t-2 border-dashed" style={{ borderColor: "hsl(190 100% 60%)" }} /> Route segment</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm border" style={{ borderColor: "hsl(0 84% 60% / 0.6)", background: "hsl(0 84% 60% / 0.15)" }} /> Restricted zone</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm border" style={{ borderColor: "hsl(38 100% 56% / 0.6)", background: "hsl(38 100% 56% / 0.15)" }} /> Flight corridor</span>
        <span className="ml-auto flex items-center gap-1 font-mono"><MapPin className="h-3 w-3" /> MapLibre / OSM</span>
      </div>
    </div>
  );
}

function ToggleChip({ label, active, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide transition-colors ${
        active
          ? "border-primary/50 bg-primary/15 text-primary"
          : "border-border text-muted-foreground hover:text-foreground"
      }`}
    >
      {label}
    </button>
  );
}
