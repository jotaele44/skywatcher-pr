import { useMemo, useRef, useState } from "react";
import { FileUp, Plane, RotateCcw } from "lucide-react";
import { FLIGHT_INGEST_STATUS, parseFlightFiles } from "@/lib/skywatcher";

const MAX_FILES = 12;
const ACCEPT = ".csv,.kml,.html,.htm,text/csv,text/html,application/vnd.google-earth.kml+xml";

const STATUS_LABEL = {
  [FLIGHT_INGEST_STATUS.READY]: "Ready",
  [FLIGHT_INGEST_STATUS.CORPUS_READY]: "Corpus ready",
  [FLIGHT_INGEST_STATUS.EMPTY_TRACK]: "Empty track",
  [FLIGHT_INGEST_STATUS.SCHEMA_UNRESOLVED]: "Schema unresolved",
  [FLIGHT_INGEST_STATUS.COORDINATE_BINDING_UNRESOLVED]: "Coordinates unresolved",
  [FLIGHT_INGEST_STATUS.MALFORMED_CSV]: "Malformed CSV",
  [FLIGHT_INGEST_STATUS.MALFORMED_XML]: "Malformed KML",
  [FLIGHT_INGEST_STATUS.UNSUPPORTED_GEOMETRY]: "Unsupported",
};

function resultTone(status) {
  if (status === FLIGHT_INGEST_STATUS.READY || status === FLIGHT_INGEST_STATUS.CORPUS_READY) return "text-emerald-300 border-emerald-400/30 bg-emerald-400/10";
  if (status === FLIGHT_INGEST_STATUS.EMPTY_TRACK) return "text-amber-300 border-amber-400/30 bg-amber-400/10";
  return "text-red-300 border-red-400/30 bg-red-400/10";
}

export function flightResultsToRoutes(results) {
  return results
    .filter((result) => result.status === FLIGHT_INGEST_STATUS.READY)
    .flatMap((result) => {
      const routes = [];
      for (let index = 1; index < result.points.length; index += 1) {
        const start = result.points[index - 1];
        const end = result.points[index];
        routes.push({
          id: `${result.source}:${index - 1}`,
          source: result.source,
          manifestation: result.manifestation,
          start_lat: start.lat,
          start_lon: start.lon,
          end_lat: end.lat,
          end_lon: end.lon,
        });
      }
      return routes;
    });
}

export default function SpatialFlightRenderer({
  onResults,
  onRoutes,
  maxFiles = MAX_FILES,
  title = "Spatial Flight Renderer",
}) {
  const inputRef = useRef(null);
  const [results, setResults] = useState([]);
  const [busy, setBusy] = useState(false);
  const [batchError, setBatchError] = useState("");

  const summary = useMemo(() => {
    const ready = results.filter((result) => result.status === FLIGHT_INGEST_STATUS.READY);
    return {
      files: results.length,
      ready: ready.length,
      empty: results.filter((result) => result.status === FLIGHT_INGEST_STATUS.EMPTY_TRACK).length,
      corpus: results.reduce((sum, result) => sum + (result.records?.length || 0), 0),
      unresolved: results.filter(
        (result) =>
          result.status !== FLIGHT_INGEST_STATUS.READY &&
          result.status !== FLIGHT_INGEST_STATUS.CORPUS_READY &&
          result.status !== FLIGHT_INGEST_STATUS.EMPTY_TRACK,
      ).length,
      points: ready.reduce((sum, result) => sum + result.points.length, 0),
    };
  }, [results]);

  const reset = () => {
    setResults([]);
    setBatchError("");
    if (inputRef.current) inputRef.current.value = "";
    onResults?.([]);
    onRoutes?.([]);
  };

  const ingest = async (fileList) => {
    const files = [...(fileList || [])];
    if (files.length === 0) return;
    if (files.length > maxFiles) {
      setBatchError(`Select at most ${maxFiles} files per batch. No files were ingested.`);
      return;
    }

    setBusy(true);
    setBatchError("");
    try {
      const parsed = await parseFlightFiles(files);
      setResults(parsed);
      onResults?.(parsed);
      onRoutes?.(flightResultsToRoutes(parsed));
    } catch (error) {
      // parseFlightFiles is deliberately per-file isolated. Reaching this branch
      // means the batch infrastructure itself failed, not an individual source.
      setBatchError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card" aria-label={title}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <Plane className="h-4 w-4 text-primary" />
            <h2 className="text-xs font-bold uppercase tracking-wider text-foreground">{title}</h2>
          </div>
          <p className="mt-1 text-[11px] text-muted-foreground">Puerto Rico flight layers · canonical CSV/KML ingestion</p>
        </div>
        <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-primary">
          KML / CSV ready
        </span>
      </div>

      <div className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            multiple
            disabled={busy}
            aria-label="Load KML or CSV flight files"
            onChange={(event) => ingest(event.target.files)}
            className="block min-w-0 flex-1 text-xs text-muted-foreground file:mr-3 file:rounded-md file:border file:border-border file:bg-muted file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-foreground"
          />
          <button
            type="button"
            onClick={reset}
            disabled={busy || results.length === 0}
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-40"
          >
            <RotateCcw className="h-3.5 w-3.5" /> Reset
          </button>
        </div>

        <p className="text-[10px] text-muted-foreground">
          Up to {maxFiles} local files · CSV header discovery scans up to 500 rows · FR24 Position, split coordinates,
          segment tables, KML Point/LineString/MultiGeometry, gx:Track, and Master Flight Log HTML backups supported.
        </p>

        {batchError && (
          <div role="alert" className="rounded-md border border-red-400/30 bg-red-400/10 px-3 py-2 text-xs text-red-300">
            {batchError}
          </div>
        )}

        {busy && (
          <div role="status" className="flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            <FileUp className="h-3.5 w-3.5" /> Parsing local flight files…
          </div>
        )}

        {results.length > 0 && (
          <>
            <div className="grid grid-cols-2 gap-2 text-[10px] sm:grid-cols-6" role="status">
              <Summary label="Files" value={summary.files} />
              <Summary label="Ready" value={summary.ready} />
              <Summary label="Empty" value={summary.empty} />
              <Summary label="Corpus" value={summary.corpus} />
              <Summary label="Unresolved" value={summary.unresolved} />
              <Summary label="Points" value={summary.points} />
            </div>

            <div className="max-h-72 space-y-2 overflow-auto pr-1">
              {results.map((result, index) => (
                <article key={`${result.source}:${index}`} className="rounded-md border border-border bg-muted/20 p-2.5">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-xs font-semibold text-foreground">{result.source}</p>
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        {result.manifestation || result.snapshot?.format || "UNCLASSIFIED"} · {result.points?.length || 0} accepted points{result.records ? ` · ${result.records.length} corpus records` : ""}
                      </p>
                    </div>
                    <span className={`rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${resultTone(result.status)}`}>
                      {STATUS_LABEL[result.status] || result.status}
                    </span>
                  </div>
                  <Diagnostics diagnostics={result.diagnostics} />
                </article>
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function Summary({ label, value }) {
  return (
    <div className="rounded-md border border-border bg-muted/20 px-2 py-1.5">
      <p className="uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="font-mono text-sm font-semibold text-foreground">{value}</p>
    </div>
  );
}

function Diagnostics({ diagnostics = {} }) {
  const rows = [
    ["Header", diagnostics.headerIndex != null ? `row ${diagnostics.headerIndex + 1}` : null],
    ["Delimiter", diagnostics.delimiter === "\t" ? "TAB" : diagnostics.delimiter],
    ["Malformed rows", diagnostics.malformedRows],
    ["Accepted", diagnostics.acceptedPoints],
    ["Scanned", diagnostics.scannedRows],
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");

  if (rows.length === 0) return null;
  return (
    <dl className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[9px] text-muted-foreground">
      {rows.map(([label, value]) => (
        <div key={label} className="flex gap-1">
          <dt>{label}:</dt>
          <dd className="font-mono text-foreground/80">{String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}
