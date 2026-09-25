import React from "react";
import { Archive, CalendarRange, Clock3, FileUp, Radar, ShieldCheck } from "lucide-react";
import MetricCard from "@/components/skywatcher/MetricCard";
import PageHeader from "@/components/skywatcher/PageHeader";
import Panel from "@/components/skywatcher/Panel";
import StatusChip from "@/components/skywatcher/StatusChip";
import { federation } from "@/api/federationClient";
import { FLIGHT_INGEST_STATUS, parseFlightFiles } from "@/lib/skywatcher";

const ACCEPT = ".html,.htm,.csv,.kml,text/html,text/csv,application/vnd.google-earth.kml+xml";
const TABS = [
  ["archive", "Archive", Archive],
  ["coverage", "Coverage", CalendarRange],
  ["timeline", "Timeline", Clock3],
  ["acquisition", "Acquisition", Radar],
  ["integrity", "Integrity", ShieldCheck],
];

function bytesToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function fmtDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toISOString().slice(0, 10);
}

function summarize(records) {
  const starts = records.map((r) => r.startTimeUtc).filter(Boolean).sort();
  const ends = records.map((r) => r.endTimeUtc).filter(Boolean).sort();
  const aircraft = new Set(records.map((r) => r.callsignRaw).filter(Boolean));
  const withKml = records.filter((r) => r.sourceManifestations.some((s) => s.kmlPresent)).length;
  return {
    first: starts[0] || null,
    last: ends.at(-1) || starts.at(-1) || null,
    aircraft: aircraft.size,
    points: records.reduce((sum, r) => sum + (r.pointCount || 0), 0),
    withKml,
    withoutKml: records.length - withKml,
  };
}

function groupedCoverage(records) {
  const grouped = new Map();
  records.forEach((row) => {
    const key = row.callsignRaw || "UNRESOLVED";
    const item = grouped.get(key) || { callsign: key, count: 0, first: null, last: null, kml: 0 };
    item.count += 1;
    if (row.startTimeUtc && (!item.first || row.startTimeUtc < item.first)) item.first = row.startTimeUtc;
    if (row.endTimeUtc && (!item.last || row.endTimeUtc > item.last)) item.last = row.endTimeUtc;
    if (row.sourceManifestations.some((s) => s.kmlPresent)) item.kml += 1;
    grouped.set(key, item);
  });
  return [...grouped.values()].sort((a, b) => b.count - a.count || a.callsign.localeCompare(b.callsign));
}

export default function FlightArchive() {
  const [tab, setTab] = React.useState("archive");
  const [results, setResults] = React.useState([]);
  const [sourceFiles, setSourceFiles] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [persisting, setPersisting] = React.useState(false);
  const [persistReceipts, setPersistReceipts] = React.useState([]);
  const [storedSnapshots, setStoredSnapshots] = React.useState([]);
  const [error, setError] = React.useState("");

  const refreshSnapshots = React.useCallback(async () => {
    try {
      setStoredSnapshots(await federation.flightCorpusArchive.listSnapshots());
    } catch {
      setStoredSnapshots([]);
    }
  }, []);

  React.useEffect(() => {
    refreshSnapshots();
  }, [refreshSnapshots]);

  const corpusResults = results.filter((r) => r.status === FLIGHT_INGEST_STATUS.CORPUS_READY);
  const records = corpusResults.flatMap((r) => r.records || []);
  const summary = summarize(records);
  const queue = records
    .filter((r) => !r.sourceManifestations.some((s) => s.kmlPresent))
    .sort((a, b) => String(b.startTimeUtc || "").localeCompare(String(a.startTimeUtc || "")));
  const unresolved = results.filter(
    (r) =>
      r.status !== FLIGHT_INGEST_STATUS.CORPUS_READY &&
      r.status !== FLIGHT_INGEST_STATUS.READY &&
      r.status !== FLIGHT_INGEST_STATUS.EMPTY_TRACK,
  );

  const ingest = async (filesLike) => {
    const files = [...(filesLike || [])];
    if (!files.length) return;
    setBusy(true);
    setError("");
    try {
      setResults(await parseFlightFiles(files));
      setSourceFiles(files);
      setPersistReceipts([]);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const persistCorpus = async () => {
    const candidates = results
      .map((result, index) => ({ result, file: sourceFiles[index] }))
      .filter(({ result, file }) =>
        file && result.status === FLIGHT_INGEST_STATUS.CORPUS_READY
      );
    if (!candidates.length) return;

    setPersisting(true);
    setError("");
    try {
      const receipts = [];
      for (const { result, file } of candidates) {
        const sourceBytes = bytesToBase64(await file.arrayBuffer());
        const receipt = await federation.flightCorpusArchive.persistSnapshot({
          source_bytes_base64: sourceBytes,
          source_kind: "master_flight_log_html",
          source_filename: file.name,
          format_name: result.snapshot?.format || "master-flight-log-backup",
          format_version: result.snapshot?.version ?? 1,
          exported_at: result.snapshot?.exportedAt || null,
          records: result.records || [],
        });
        receipts.push({ file: file.name, ...receipt });
      }
      setPersistReceipts(receipts);
      await refreshSnapshots();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setPersisting(false);
    }
  };

  const loadStoredSnapshot = async (snapshotId) => {
    setBusy(true);
    setError("");
    try {
      const stored = await federation.flightCorpusArchive.getSnapshot(snapshotId);
      setResults([{
        status: FLIGHT_INGEST_STATUS.CORPUS_READY,
        source: stored.snapshot?.source_filename || ("snapshot-" + snapshotId),
        snapshot: {
          format: stored.snapshot?.format_name || "master-flight-log-backup",
          version: stored.snapshot?.format_version || null,
          exportedAt: stored.snapshot?.exported_at || null,
          recordCount: stored.snapshot?.record_count || 0,
        },
        records: stored.records || [],
        diagnostics: { persistedSnapshotId: snapshotId },
      }]);
      setSourceFiles([]);
      setPersistReceipts([]);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Flight Archive"
        subtitle="Canonical corpus, coverage, acquisition, and integrity review. Corpus metadata remains distinct from analytical flight geometry."
        icon={Archive}
        actions={null}
      />

      <Panel title="Load corpus snapshot" icon={FileUp} action={null}>
        <div className="space-y-3">
          <input
            type="file"
            accept={ACCEPT}
            multiple
            disabled={busy}
            aria-label="Load Master Flight Log, CSV, or KML files"
            onChange={(event) => ingest(event.target.files)}
            className="block w-full text-xs text-muted-foreground file:mr-3 file:rounded-md file:border file:border-border file:bg-muted file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-foreground"
          />
          <p className="text-xs text-muted-foreground">
            Master Flight Log HTML is corpus metadata. CSV/KML remain geometry-bearing manifestations and are not synthesized into corpus identity here.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy || persisting || corpusResults.length === 0}
              onClick={persistCorpus}
              className="rounded-md border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              {persisting ? "Persisting…" : "Persist corpus snapshot"}
            </button>
            <span className="text-xs text-muted-foreground">
              Explicit commit only; preview/import alone does not write canonical storage.
            </span>
          </div>
          {busy && <p className="text-xs text-muted-foreground">Parsing local sources…</p>}
          {persistReceipts.map((receipt) => (
            <p key={receipt.file + receipt.snapshot_id} className="text-xs text-emerald-300">
              Persisted {receipt.file}: snapshot #{receipt.snapshot_id} · {receipt.record_count} records · SHA-256 {receipt.source_sha256}
              {receipt.duplicate_snapshot ? " · exact duplicate reused" : ""}
            </p>
          ))}
          {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
        </div>
      </Panel>

      <Panel title="Persisted snapshots" icon={Archive} action={<StatusChip tone="ready" label={String(storedSnapshots.length) + " stored"} icon={null} />}>
        {storedSnapshots.length === 0 ? (
          <p className="text-sm text-muted-foreground">No persisted corpus snapshots in the configured Skywatcher database.</p>
        ) : (
          <div className="max-h-48 space-y-1 overflow-auto">
            {storedSnapshots.map((snapshot) => (
              <button
                key={snapshot.snapshot_id}
                type="button"
                onClick={() => loadStoredSnapshot(snapshot.snapshot_id)}
                className="grid w-full grid-cols-[5rem_1fr_7rem_10rem] gap-2 rounded-md border border-border bg-muted/20 px-3 py-2 text-left text-xs hover:bg-muted/40"
              >
                <span className="font-mono text-foreground">#{snapshot.snapshot_id}</span>
                <span className="truncate text-foreground">{snapshot.source_filename || snapshot.source_ref || snapshot.source_kind}</span>
                <span className="text-right font-mono text-muted-foreground">{snapshot.record_count} rows</span>
                <span className="truncate font-mono text-muted-foreground">{snapshot.source_sha256?.slice(0, 16)}…</span>
              </button>
            ))}
          </div>
        )}
      </Panel>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard label="Corpus records" value={records.length} sub={String(corpusResults.length) + " imported snapshot(s)"} icon={Archive} accent="primary" />
        <MetricCard label="Aircraft identities" value={summary.aircraft} sub="Distinct source callsigns; not canonical aircraft identity" icon={Radar} accent="info" />
        <MetricCard label="Track points" value={summary.points} sub="Source-reported accepted point count" icon={Clock3} accent="muted" />
        <MetricCard label="With KML" value={summary.withKml} sub={String(summary.withoutKml) + " without KML manifestation"} icon={ShieldCheck} accent={summary.withoutKml ? "warn" : "ready"} />
        <MetricCard label="Coverage span" value={summary.first ? fmtDate(summary.first) + " → " + fmtDate(summary.last) : "—"} sub="Observed corpus range only" icon={CalendarRange} accent="primary" />
      </div>

      <div className="flex flex-wrap gap-2 border-b border-border pb-2" role="tablist" aria-label="Flight archive sections">
        {TABS.map(([id, label, Icon]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={"inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-semibold " + (
              tab === id
                ? "border-primary/40 bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:text-foreground"
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>

      {tab === "archive" && <Panel title="Canonical corpus records" icon={Archive} action={null}><CorpusTable records={records} /></Panel>}
      {tab === "coverage" && <Panel title="Coverage denominator" icon={CalendarRange} action={null}>
        <p className="mb-3 text-sm text-muted-foreground">This describes what the archive can answer. Absence from the corpus is not evidence that an aircraft did not fly.</p>
        <CoverageTable records={records} />
      </Panel>}
      {tab === "timeline" && <Panel title="Observed timeline" icon={Clock3} action={null}><Timeline records={records} /></Panel>}
      {tab === "acquisition" && <Panel title="Acquisition queue" icon={Radar} action={<StatusChip tone={queue.length ? "warn" : "ready"} label={String(queue.length) + " missing KML"} icon={null} />}><CorpusTable records={queue} empty="No corpus records currently lack a KML manifestation." /></Panel>}
      {tab === "integrity" && <Panel title="Integrity state" icon={ShieldCheck} action={null}>
        <div className="grid gap-3 md:grid-cols-3">
          <Integrity label="Corpus-ready snapshots" value={corpusResults.length} tone="ready" />
          <Integrity label="Unresolved inputs" value={unresolved.length} tone={unresolved.length ? "warn" : "ready"} />
          <Integrity label="Metadata-only route synthesis" value="0" tone="ready" />
        </div>
        <p className="mt-3 text-xs text-muted-foreground">Route geometry is intentionally not generated from Master Flight Log endpoint metadata. Renderable tracks still require geometry-bearing evidence.</p>
      </Panel>}
    </div>
  );
}

function CorpusTable({ records, empty = "Load a Master Flight Log HTML backup to populate the corpus." }) {
  if (!records.length) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <div className="max-h-[62vh] overflow-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead><tr className="sticky top-0 border-b border-border bg-secondary text-left text-[10px] uppercase tracking-wide text-muted-foreground">
          <th className="px-3 py-2">Flight ID</th><th className="px-3 py-2">Callsign</th><th className="px-3 py-2">Start</th><th className="px-3 py-2">End</th><th className="px-3 py-2 text-right">Points</th><th className="px-3 py-2">KML</th><th className="px-3 py-2">Route</th>
        </tr></thead>
        <tbody>{records.slice(0, 1000).map((row) => {
          const hasKml = row.sourceManifestations.some((s) => s.kmlPresent);
          return <tr key={row.corpusUid} className="border-b border-border/50">
            <td className="px-3 py-2 font-mono text-xs text-foreground">{row.sourceFlightIdRaw || "—"}</td>
            <td className="px-3 py-2 font-mono text-xs text-foreground">{row.callsignRaw || "—"}</td>
            <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{row.startTimeUtc || "—"}</td>
            <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{row.endTimeUtc || "—"}</td>
            <td className="px-3 py-2 text-right font-mono text-xs">{row.pointCount ?? "—"}</td>
            <td className="px-3 py-2"><StatusChip tone={hasKml ? "ready" : "warn"} label={hasKml ? "present" : "missing"} icon={null} /></td>
            <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{row.kmlEnrichment?.routeRaw || "—"}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>
  );
}

function CoverageTable({ records }) {
  const rows = groupedCoverage(records);
  if (!rows.length) return <p className="text-sm text-muted-foreground">No corpus coverage loaded.</p>;
  return <div className="overflow-auto rounded-lg border border-border"><table className="w-full text-sm">
    <thead><tr className="border-b border-border bg-secondary/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
      <th className="px-3 py-2">Source callsign</th><th className="px-3 py-2 text-right">Flights</th><th className="px-3 py-2">First</th><th className="px-3 py-2">Last</th><th className="px-3 py-2 text-right">KML</th>
    </tr></thead>
    <tbody>{rows.map((row) => <tr key={row.callsign} className="border-b border-border/50">
      <td className="px-3 py-2 font-mono text-xs">{row.callsign}</td><td className="px-3 py-2 text-right font-mono text-xs">{row.count}</td><td className="px-3 py-2 font-mono text-xs text-muted-foreground">{fmtDate(row.first)}</td><td className="px-3 py-2 font-mono text-xs text-muted-foreground">{fmtDate(row.last)}</td><td className="px-3 py-2 text-right font-mono text-xs">{row.kml}/{row.count}</td>
    </tr>)}</tbody>
  </table></div>;
}

function Timeline({ records }) {
  const rows = [...records].filter((r) => r.startTimeUtc).sort((a, b) => a.startTimeUtc.localeCompare(b.startTimeUtc));
  if (!rows.length) return <p className="text-sm text-muted-foreground">No timestamped corpus records loaded.</p>;
  return <div className="max-h-[62vh] space-y-1 overflow-auto">{rows.slice(0, 1000).map((row) =>
    <div key={row.corpusUid} className="grid grid-cols-[10rem_8rem_1fr] gap-3 rounded-md border border-border bg-muted/20 px-3 py-2 text-xs">
      <span className="font-mono text-muted-foreground">{row.startTimeUtc}</span><span className="font-mono font-semibold text-foreground">{row.callsignRaw || "UNRESOLVED"}</span><span className="font-mono text-muted-foreground">{row.sourceFlightIdRaw || row.corpusUid}</span>
    </div>
  )}</div>;
}

function Integrity({ label, value, tone }) {
  return <div className="rounded-lg border border-border bg-muted/20 p-3">
    <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
    <div className="mt-2 flex items-center justify-between gap-2"><span className="font-mono text-xl font-semibold text-foreground">{value}</span><StatusChip tone={tone} label={tone === "ready" ? "PASS" : "REVIEW"} icon={null} /></div>
  </div>;
}
