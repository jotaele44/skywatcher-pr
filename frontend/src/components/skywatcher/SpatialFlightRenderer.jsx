import React, { useMemo, useState } from "react";
import { FileWarning, Layers3, Upload } from "lucide-react";
import Panel from "@/components/skywatcher/Panel";
import StatusChip from "@/components/skywatcher/StatusChip";
import {
  FLIGHT_INGEST_STATUS,
  parseFlightFiles,
} from "@/lib/skywatcher";

const MAX_FILES = 12;

const STATUS_TONE = {
  [FLIGHT_INGEST_STATUS.READY]: "ready",
  [FLIGHT_INGEST_STATUS.EMPTY_TRACK]: "muted",
  [FLIGHT_INGEST_STATUS.SCHEMA_UNRESOLVED]: "warn",
  [FLIGHT_INGEST_STATUS.COORDINATE_BINDING_UNRESOLVED]: "warn",
  [FLIGHT_INGEST_STATUS.MALFORMED_CSV]: "blocked",
  [FLIGHT_INGEST_STATUS.MALFORMED_XML]: "blocked",
  [FLIGHT_INGEST_STATUS.UNSUPPORTED_GEOMETRY]: "blocked",
};

function extentFor(results) {
  const points = results.flatMap((result) => result.points || []);
  if (!points.length) return null;
  const lats = points.map((point) => point.lat).filter(Number.isFinite);
  const lons = points.map((point) => point.lon).filter(Number.isFinite);
  if (!lats.length || !lons.length) return null;

  let minLat = Math.min(...lats);
  let maxLat = Math.max(...lats);
  let minLon = Math.min(...lons);
  let maxLon = Math.max(...lons);

  const latPad = Math.max((maxLat - minLat) * 0.08, 0.01);
  const lonPad = Math.max((maxLon - minLon) * 0.08, 0.01);
  minLat -= latPad;
  maxLat += latPad;
  minLon -= lonPad;
  maxLon += lonPad;

  return { minLat, maxLat, minLon, maxLon };
}

function project(point, extent, width = 1000, height = 360, pad = 24) {
  const x = pad + ((point.lon - extent.minLon) / (extent.maxLon - extent.minLon)) * (width - pad * 2);
  const y = pad + ((extent.maxLat - point.lat) / (extent.maxLat - extent.minLat)) * (height - pad * 2);
  return [x, y];
}

function pathFor(points, extent) {
  if (!extent || !points?.length) return "";
  return points
    .filter((point) => Number.isFinite(point.lat) && Number.isFinite(point.lon))
    .map((point, index) => {
      const [x, y] = project(point, extent);
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

export default function SpatialFlightRenderer() {
  const [results, setResults] = useState([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const ready = useMemo(
    () => results.filter((result) => result.status === FLIGHT_INGEST_STATUS.READY),
    [results],
  );
  const extent = useMemo(() => extentFor(ready), [ready]);
  const totalPoints = useMemo(
    () => ready.reduce((sum, result) => sum + (result.points?.length || 0), 0),
    [ready],
  );

  async function onFiles(event) {
    const files = [...(event.target.files || [])];
    if (!files.length) return;

    if (files.length > MAX_FILES) {
      setMessage(`Select no more than ${MAX_FILES} files per batch.`);
      event.target.value = "";
      return;
    }

    setLoading(true);
    setMessage("");
    try {
      const parsed = await parseFlightFiles(files);
      setResults(parsed);
    } catch (error) {
      setMessage(`Unexpected batch failure: ${String(error)}`);
    } finally {
      setLoading(false);
      event.target.value = "";
    }
  }

  return (
    <Panel title="Spatial Flight Renderer" icon={Layers3}>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-secondary/20 p-3">
          <div>
            <p className="text-xs font-semibold text-foreground">Puerto Rico flight layers</p>
            <p className="text-[10px] text-muted-foreground">
              Canonical CSV/KML ingestion · up to {MAX_FILES} local files · files remain browser-local
            </p>
          </div>
          <label className="inline-flex cursor-pointer items-center gap-2 rounded border border-border bg-background px-3 py-2 text-xs font-semibold hover:bg-secondary/50">
            <Upload className="h-4 w-4" />
            {loading ? "Parsing…" : "Load KML / CSV flight files"}
            <input
              aria-label="Load KML or CSV flight files"
              type="file"
              accept=".csv,.kml,text/csv,application/vnd.google-earth.kml+xml"
              multiple
              disabled={loading}
              onChange={onFiles}
              className="sr-only"
            />
          </label>
        </div>

        {message && (
          <div className="flex items-start gap-2 rounded border border-destructive/40 bg-destructive/10 p-3 text-xs">
            <FileWarning className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{message}</span>
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded border border-border p-3">
            <p className="text-[10px] uppercase text-muted-foreground">Files</p>
            <p className="font-mono text-lg font-bold">{results.length}</p>
          </div>
          <div className="rounded border border-border p-3">
            <p className="text-[10px] uppercase text-muted-foreground">Ready</p>
            <p className="font-mono text-lg font-bold">{ready.length}</p>
          </div>
          <div className="rounded border border-border p-3">
            <p className="text-[10px] uppercase text-muted-foreground">Accepted points</p>
            <p className="font-mono text-lg font-bold">{totalPoints.toLocaleString()}</p>
          </div>
        </div>

        <div className="overflow-hidden rounded-lg border border-border bg-[hsl(220_30%_5%)]">
          {extent ? (
            <svg
              role="img"
              aria-label="Local flight track preview"
              viewBox="0 0 1000 360"
              className="h-[260px] w-full"
              preserveAspectRatio="none"
            >
              <rect x="0" y="0" width="1000" height="360" fill="currentColor" opacity="0.02" />
              {ready.map((result, index) => (
                <path
                  key={result.source || index}
                  d={pathFor(result.points, extent)}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={ready.length > 6 ? 1.2 : 1.8}
                  opacity={0.82}
                  vectorEffect="non-scaling-stroke"
                />
              ))}
            </svg>
          ) : (
            <div className="flex h-[260px] items-center justify-center px-6 text-center text-xs text-muted-foreground">
              Load CSV or KML files to preview their coordinate tracks. Empty or unresolved files remain listed below without blocking valid siblings.
            </div>
          )}
        </div>

        {results.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-secondary/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2">File</th>
                  <th className="px-3 py-2">State</th>
                  <th className="px-3 py-2">Manifestation</th>
                  <th className="px-3 py-2">Points</th>
                  <th className="px-3 py-2">Header</th>
                  <th className="px-3 py-2">Delimiter</th>
                </tr>
              </thead>
              <tbody>
                {results.map((result, index) => (
                  <tr key={`${result.source}-${index}`} className="border-t border-border/50">
                    <td className="px-3 py-2 font-mono">{result.source}</td>
                    <td className="px-3 py-2">
                      <StatusChip
                        tone={STATUS_TONE[result.status] || "muted"}
                        label={result.status}
                      />
                    </td>
                    <td className="px-3 py-2 font-mono text-[10px]">
                      {result.manifestation || "—"}
                    </td>
                    <td className="px-3 py-2 font-mono">{result.points?.length || 0}</td>
                    <td className="px-3 py-2 font-mono">
                      {Number.isInteger(result.diagnostics?.headerIndex)
                        ? result.diagnostics.headerIndex + 1
                        : "—"}
                    </td>
                    <td className="px-3 py-2 font-mono">
                      {result.diagnostics?.delimiter === "\t"
                        ? "TAB"
                        : result.diagnostics?.delimiter || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="text-[10px] text-muted-foreground">
          Local rendering is a visualization aid only. Loading or pairing files does not establish aircraft identity, mission, coordination, targeting, or canonical route equivalence.
        </p>
      </div>
    </Panel>
  );
}
