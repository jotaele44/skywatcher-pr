import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Archive,
  Camera,
  CheckCircle2,
  FileArchive,
  FileImage,
  History,
  Pause,
  Play,
  RefreshCw,
  ShieldCheck,
  Square,
  Upload,
} from "lucide-react";
import { federation } from "@/api/federationClient";
import { useSkywatcher } from "@/lib/SkywatcherData";
import { useDrawers } from "@/components/skywatcher/drawers/DrawerHub";
import PageHeader from "@/components/skywatcher/PageHeader";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import Panel from "@/components/skywatcher/Panel";
import StatusChip from "@/components/skywatcher/StatusChip";
import SyntheticDataBadge from "@/components/skywatcher/SyntheticDataBadge";
import EmptyState from "@/components/skywatcher/EmptyState";
import LoadingState from "@/components/skywatcher/LoadingState";
import { Toolbar, SearchInput, FilterSelect } from "@/components/skywatcher/Toolbar";
import { INGEST_STATUS } from "@/lib/skywatcher";

const ACCEPT = [
  ".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".pdf", ".zip",
].join(",");

const TABS = [
  ["processor", "Screenshot Processor", Upload],
  ["history", "Processing History", History],
  ["review", "Review Queue", ShieldCheck],
];

const INGEST_OPTS = [
  { value: "all", label: "All ingest states" },
  { value: "queued", label: "Queued" },
  { value: "processed", label: "Processed" },
  { value: "needs_manual_review", label: "Needs Manual Review" },
  { value: "duplicate", label: "Duplicate" },
  { value: "corrupt", label: "Corrupt" },
  { value: "rejected", label: "Rejected" },
];

const DEFAULT_SETTINGS = {
  source_family: "auto",
  ocr: true,
  vision_assist: "low_confidence_only",
  track_vectorization: true,
  georeference: true,
  match_existing_flights: true,
  candidate_time_window_minutes: 90,
  temporal_hint_mode: "preserve_only",
};

function bytesToBase64(arrayBuffer) {
  const bytes = new Uint8Array(arrayBuffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

async function serializeUploads(files) {
  const uploads = [];
  for (const file of files) {
    uploads.push({
      name: file.name,
      content_base64: bytesToBase64(await file.arrayBuffer()),
    });
  }
  return uploads;
}

function formatBytes(value) {
  const n = Number(value || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function toneForJob(status) {
  if (status === "COMPLETED") return "ready";
  if (status === "FAILED" || status === "CANCELED") return "blocked";
  if (status === "PAUSED") return "warn";
  if (status === "RUNNING" || status === "QUEUED") return "info";
  return "muted";
}

export default function FR24Intake() {
  const d = useSkywatcher();
  const [tab, setTab] = useState("processor");
  const [files, setFiles] = useState([]);
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);
  const [job, setJob] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [decisions, setDecisions] = useState({});
  const [rationales, setRationales] = useState({});
  const pollRef = useRef(null);

  const loadHistory = async () => {
    try {
      const result = await federation.screenshotProcessing.listJobs({ limit: 50 });
      setJobs(result.jobs || []);
    } catch {
      // History is supplemental; processor errors are shown from direct actions.
    }
  };

  useEffect(() => {
    loadHistory();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  useEffect(() => {
    if (!job?.job_id || !["QUEUED", "RUNNING", "PAUSED"].includes(job.status)) {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
      return;
    }
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const current = await federation.screenshotProcessing.getJob(job.job_id);
        setJob(current);
        if (!["QUEUED", "RUNNING", "PAUSED"].includes(current.status)) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          loadHistory();
        }
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : String(exc));
      }
    }, 1200);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [job?.job_id, job?.status]);

  const execute = async () => {
    if (!files.length) return;
    setBusy(true);
    setError("");
    setDecisions({});
    setRationales({});
    try {
      const uploads = await serializeUploads(files);
      const staged = await federation.screenshotProcessing.createJob({ uploads, settings });
      setJob(staged);
      const running = await federation.screenshotProcessing.execute(staged.job_id);
      setJob(running);
      setTab("processor");
      loadHistory();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const control = async (action) => {
    if (!job?.job_id) return;
    setError("");
    try {
      const updated = await federation.screenshotProcessing[action](job.job_id);
      setJob(updated);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };

  const loadJob = async (jobId) => {
    setBusy(true);
    setError("");
    try {
      setJob(await federation.screenshotProcessing.getJob(jobId));
      setTab("processor");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const commitSelected = async () => {
    if (!job?.job_id) return;
    const payload = Object.entries(decisions)
      .filter(([, corpusRecordId]) => corpusRecordId)
      .map(([fileId, corpusRecordId]) => ({
        file_id: Number(fileId),
        corpus_record_id: Number(corpusRecordId),
        rationale: String(rationales[fileId] || "").trim(),
      }));
    if (!payload.length) {
      setError("Select at least one candidate record before committing.");
      return;
    }
    if (payload.some((item) => !item.rationale)) {
      setError("A review rationale is required for every committed candidate link.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await federation.screenshotProcessing.commit(job.job_id, payload);
      setJob(await federation.screenshotProcessing.getJob(job.job_id));
      loadHistory();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  if (d.loading) return <LoadingState />;

  return (
    <div className="space-y-5">
      <PageHeader
        title="FR24 Intake"
        subtitle="Upload screenshots, run bounded extraction, and reconcile staged evidence against the Master Flight Log."
        icon={Camera}
      />
      <DiagnosticNoticeBanner />

      <div className="flex flex-wrap gap-2 border-b border-border pb-2" role="tablist" aria-label="FR24 intake sections">
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

      {error && (
        <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {tab === "processor" && (
        <ProcessorTab
          files={files}
          setFiles={setFiles}
          settings={settings}
          setSettings={setSettings}
          job={job}
          busy={busy}
          onExecute={execute}
          onPause={() => control("pause")}
          onResume={() => control("resume")}
          onCancel={() => control("cancel")}
          decisions={decisions}
          setDecisions={setDecisions}
          rationales={rationales}
          setRationales={setRationales}
          onCommit={commitSelected}
        />
      )}

      {tab === "history" && (
        <HistoryTab jobs={jobs} onRefresh={loadHistory} onLoad={loadJob} />
      )}

      {tab === "review" && (
        <ReviewTab data={d} />
      )}
    </div>
  );
}

function ProcessorTab({
  files,
  setFiles,
  settings,
  setSettings,
  job,
  busy,
  onExecute,
  onPause,
  onResume,
  onCancel,
  decisions,
  setDecisions,
  rationales,
  setRationales,
  onCommit,
}) {
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  return (
    <div className="space-y-5">
      <Panel title="1. Upload evidence" icon={Upload} action={null}>
        <div className="space-y-3">
          <label className="flex min-h-32 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-border bg-muted/20 px-4 py-6 text-center hover:bg-muted/35">
            <FileImage className="mb-2 h-6 w-6 text-primary" />
            <span className="text-sm font-semibold text-foreground">Choose screenshots, PDFs, or ZIP archives</span>
            <span className="mt-1 text-xs text-muted-foreground">Multiple files are supported. Source bytes and expanded visual manifestations remain distinct.</span>
            <input
              className="sr-only"
              type="file"
              accept={ACCEPT}
              multiple
              disabled={busy || ["QUEUED", "RUNNING"].includes(job?.status)}
              onChange={(event) => setFiles([...(event.target.files || [])])}
            />
          </label>
          {files.length > 0 && (
            <div className="rounded-lg border border-border bg-background/30">
              <div className="flex items-center justify-between border-b border-border px-3 py-2 text-xs">
                <span className="font-semibold text-foreground">{files.length} selected source(s)</span>
                <span className="font-mono text-muted-foreground">{formatBytes(totalBytes)}</span>
              </div>
              <div className="max-h-40 overflow-auto">
                {files.map((file, index) => (
                  <div key={file.name + file.size + index} className="flex items-center justify-between border-b border-border/50 px-3 py-2 text-xs last:border-0">
                    <span className="truncate pr-3 text-foreground">{file.name}</span>
                    <span className="shrink-0 font-mono text-muted-foreground">{formatBytes(file.size)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </Panel>

      <Panel title="2. Pre-processing settings" icon={ShieldCheck} action={null}>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <SettingSelect
            label="Source family"
            value={settings.source_family}
            onChange={(value) => setSettings((prev) => ({ ...prev, source_family: value }))}
            options={[
              ["auto", "Automatic"],
              ["fr24", "FlightRadar24"],
              ["generic_aviation", "Generic aviation screenshot"],
            ]}
          />
          <SettingSelect
            label="Vision assistance"
            value={settings.vision_assist}
            onChange={(value) => setSettings((prev) => ({ ...prev, vision_assist: value }))}
            options={[
              ["disabled", "Disabled"],
              ["low_confidence_only", "Low-confidence only"],
              ["comprehensive", "Comprehensive"],
            ]}
          />
          <SettingSelect
            label="Filename timestamp interpretation"
            value={settings.temporal_hint_mode}
            onChange={(value) => setSettings((prev) => ({ ...prev, temporal_hint_mode: value }))}
            options={[
              ["preserve_only", "Preserve only — no temporal filtering"],
              ["america_puerto_rico", "Puerto Rico local time (AST)"],
              ["utc", "UTC"],
            ]}
          />
          <SettingNumber
            label="Candidate time window"
            value={settings.candidate_time_window_minutes}
            suffix="minutes"
            min={1}
            max={1440}
            onChange={(value) => setSettings((prev) => ({ ...prev, candidate_time_window_minutes: value }))}
          />
          <SettingToggle
            label="Local OCR"
            checked={settings.ocr}
            onChange={(checked) => setSettings((prev) => ({ ...prev, ocr: checked }))}
          />
          <SettingToggle
            label="Rendered-track vectorization"
            checked={settings.track_vectorization}
            onChange={(checked) => setSettings((prev) => ({ ...prev, track_vectorization: checked }))}
          />
          <SettingToggle
            label="Use existing georeference evidence"
            checked={settings.georeference}
            onChange={(checked) => setSettings((prev) => ({ ...prev, georeference: checked }))}
          />
          <SettingToggle
            label="Reconcile against Master Flight Log"
            checked={settings.match_existing_flights}
            onChange={(checked) => setSettings((prev) => ({ ...prev, match_existing_flights: checked }))}
          />
        </div>
        <p className="mt-4 text-xs text-muted-foreground">
          Screenshot-derived fields remain provisional. Rendered trails are not raw trajectories, and candidate matches never promote flight identity automatically.
        </p>
      </Panel>

      <Panel
        title="3. Execution"
        icon={Play}
        action={
          <button
            type="button"
            disabled={busy || files.length === 0 || ["QUEUED", "RUNNING"].includes(job?.status)}
            onClick={onExecute}
            className="rounded-md border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Preparing…" : "Execute Processing"}
          </button>
        }
      >
        {!job ? (
          <p className="text-sm text-muted-foreground">Upload one or more sources, configure processing, then execute.</p>
        ) : (
          <JobProgress job={job} onPause={onPause} onResume={onResume} onCancel={onCancel} />
        )}
      </Panel>

      {job?.files?.length > 0 && (
        <Panel title="4. Results and Master Flight Log reconciliation" icon={Archive} action={null}>
          <ResultsTable
            job={job}
            decisions={decisions}
            setDecisions={setDecisions}
            rationales={rationales}
            setRationales={setRationales}
          />
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={busy || job.status !== "COMPLETED"}
              onClick={onCommit}
              className="rounded-md border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              Commit reviewed candidate links
            </button>
            <span className="text-xs text-muted-foreground">
              Commit records a screenshot manifestation as candidate evidence. It does not change canonical flight identity.
            </span>
          </div>
        </Panel>
      )}
    </div>
  );
}

function JobProgress({ job, onPause, onResume, onCancel }) {
  const pct = Math.round(Number(job.progress || 0) * 100);
  const running = ["QUEUED", "RUNNING"].includes(job.status);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <StatusChip tone={toneForJob(job.status)} label={job.status} icon={null} />
            <span className="font-mono text-xs text-muted-foreground">{job.job_id}</span>
          </div>
          <p className="mt-2 text-sm text-foreground">Current stage: <span className="font-semibold">{job.stage}</span></p>
        </div>
        <div className="flex gap-2">
          {running && (
            <button type="button" onClick={onPause} className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs">
              <Pause className="h-3.5 w-3.5" /> Pause
            </button>
          )}
          {job.status === "PAUSED" && (
            <button type="button" onClick={onResume} className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs">
              <Play className="h-3.5 w-3.5" /> Resume
            </button>
          )}
          {["QUEUED", "RUNNING", "PAUSED"].includes(job.status) && (
            <button type="button" onClick={onCancel} className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs">
              <Square className="h-3.5 w-3.5" /> Cancel
            </button>
          )}
        </div>
      </div>

      <div>
        <div className="mb-1 flex items-center justify-between text-xs">
          <span className="text-muted-foreground">Overall progress</span>
          <span className="font-mono font-semibold text-foreground">{pct}%</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-secondary">
          <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        <MiniMetric label="Sources" value={job.source_count} />
        <MiniMetric label="Manifestations" value={job.manifestation_count} />
        <MiniMetric label="Processable" value={job.processable_count} />
        <MiniMetric label="Failed" value={job.failed_count} />
        <MiniMetric label="Needs review" value={job.review_count} />
      </div>

      {job.error && <p className="text-xs text-red-300">{job.error}</p>}

      {job.events?.length > 0 && (
        <div className="max-h-44 overflow-auto rounded-lg border border-border bg-background/30">
          {job.events.slice(-12).reverse().map((event) => (
            <div key={event.event_id} className="grid grid-cols-[6.5rem_6rem_1fr] gap-2 border-b border-border/50 px-3 py-2 text-xs last:border-0">
              <span className="font-mono text-muted-foreground">{event.stage}</span>
              <span className="font-semibold text-foreground">{event.status}</span>
              <span className="text-muted-foreground">{event.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ResultsTable({ job, decisions, setDecisions, rationales, setRationales }) {
  const rows = job.files || [];
  return (
    <div className="max-h-[64vh] overflow-auto rounded-lg border border-border">
      <table className="w-full min-w-[1120px] text-sm">
        <thead>
          <tr className="sticky top-0 border-b border-border bg-secondary text-left text-[10px] uppercase tracking-wide text-muted-foreground">
            <th className="px-3 py-2">Source</th>
            <th className="px-3 py-2">State</th>
            <th className="px-3 py-2">Aircraft fields</th>
            <th className="px-3 py-2">Rendered track</th>
            <th className="px-3 py-2">Reconciliation</th>
            <th className="px-3 py-2">Reviewed candidate</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const candidates = row.candidate_matches || [];
            const fields = row.extracted_fields || {};
            const selected = decisions[row.file_id] || "";
            return (
              <tr key={row.file_id} className="align-top border-b border-border/50">
                <td className="px-3 py-2">
                  <div className="max-w-60 truncate text-xs font-semibold text-foreground">{row.source_locator}</div>
                  <div className="mt-1 font-mono text-[10px] text-muted-foreground">{row.payload_sha256?.slice(0, 16) || "—"}{row.payload_sha256 ? "…" : ""}</div>
                  {row.exact_duplicate && <div className="mt-1 text-[10px] font-semibold text-amber-300">exact payload already known</div>}
                </td>
                <td className="px-3 py-2">
                  <StatusChip
                    tone={row.status === "FAILED" ? "blocked" : row.extraction_status === "UNRESOLVED" ? "warn" : "ready"}
                    label={row.status}
                    icon={null}
                  />
                  <div className="mt-1 text-[10px] text-muted-foreground">OCR {row.ocr_status || "—"}</div>
                </td>
                <td className="px-3 py-2">
                  {Object.keys(fields).length ? (
                    <div className="space-y-1 text-xs">
                      {Object.entries(fields).slice(0, 8).map(([key, value]) => (
                        <div key={key}><span className="text-muted-foreground">{key}:</span> <span className="font-mono text-foreground">{String(value)}</span></div>
                      ))}
                    </div>
                  ) : <span className="text-xs text-muted-foreground">No structured fields</span>}
                </td>
                <td className="px-3 py-2 text-xs">
                  {row.track_features?.path_shape ? (
                    <div>
                      <div className="font-semibold text-foreground">{row.track_features.path_shape}</div>
                      <div className="text-muted-foreground">Rendered trail · not raw trajectory</div>
                    </div>
                  ) : <span className="text-muted-foreground">Unresolved</span>}
                </td>
                <td className="px-3 py-2">
                  <StatusChip
                    tone={candidates.length ? "warn" : "muted"}
                    label={row.reconciliation_status || "UNRESOLVED"}
                    icon={null}
                  />
                  <div className="mt-1 text-[10px] text-muted-foreground">{candidates.length} candidate(s)</div>
                  {row.contradictions?.map((item, index) => (
                    <div key={index} className="mt-1 text-[10px] text-amber-300">{item.detail}</div>
                  ))}
                </td>
                <td className="px-3 py-2">
                  {candidates.length ? (
                    <div className="space-y-2">
                      <select
                        value={selected}
                        onChange={(event) => setDecisions((prev) => ({ ...prev, [row.file_id]: event.target.value }))}
                        className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground"
                      >
                        <option value="">Do not link</option>
                        {candidates.map((candidate) => (
                          <option key={candidate.corpus_record_id} value={candidate.corpus_record_id}>
                            #{candidate.corpus_record_id} · {candidate.callsign_raw || "—"} · {candidate.start_time_utc || "time unresolved"}
                          </option>
                        ))}
                      </select>
                      <input
                        value={rationales[row.file_id] || ""}
                        disabled={!selected}
                        onChange={(event) => setRationales((prev) => ({ ...prev, [row.file_id]: event.target.value }))}
                        placeholder="Review rationale required"
                        className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground disabled:opacity-40"
                      />
                      {row.committed_corpus_record_id && (
                        <div className="flex items-center gap-1 text-[10px] font-semibold text-emerald-300">
                          <CheckCircle2 className="h-3 w-3" /> Candidate link committed to record #{row.committed_corpus_record_id}
                        </div>
                      )}
                    </div>
                  ) : <span className="text-xs text-muted-foreground">No candidate set</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function HistoryTab({ jobs, onRefresh, onLoad }) {
  return (
    <Panel
      title="Persistent processing jobs"
      icon={History}
      action={
        <button type="button" onClick={onRefresh} className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs">
          <RefreshCw className="h-3.5 w-3.5" /> Refresh
        </button>
      }
    >
      {!jobs.length ? (
        <EmptyState icon={FileArchive} title="No screenshot processing jobs" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-secondary/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                <th className="px-3 py-2">Job</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Stage</th>
                <th className="px-3 py-2 text-right">Progress</th>
                <th className="px-3 py-2 text-right">Sources</th>
                <th className="px-3 py-2 text-right">Review</th>
                <th className="px-3 py-2">Created</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((item) => (
                <tr
                  key={item.job_id}
                  onClick={() => onLoad(item.job_id)}
                  className="cursor-pointer border-b border-border/50 hover:bg-secondary/30"
                >
                  <td className="px-3 py-2 font-mono text-xs text-foreground">{item.job_id.slice(0, 12)}…</td>
                  <td className="px-3 py-2"><StatusChip tone={toneForJob(item.status)} label={item.status} icon={null} /></td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">{item.stage}</td>
                  <td className="px-3 py-2 text-right font-mono text-xs">{Math.round(Number(item.progress || 0) * 100)}%</td>
                  <td className="px-3 py-2 text-right font-mono text-xs">{item.source_count}</td>
                  <td className="px-3 py-2 text-right font-mono text-xs">{item.review_count}</td>
                  <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{item.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function ReviewTab({ data }) {
  const { open } = useDrawers();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const filtered = useMemo(() => {
    let rows = [...data.captures];
    if (q) {
      const s = q.toLowerCase();
      rows = rows.filter((capture) => [capture.file_name, capture.capture_id, capture.sha256_hash]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(s)));
    }
    if (status !== "all") rows = rows.filter((capture) => capture.ingest_status === status);
    return rows.sort((a, b) => new Date(b.captured_at) - new Date(a.captured_at));
  }, [data.captures, q, status]);

  return (
    <Panel title="Existing repository capture queue" icon={ShieldCheck} action={null} bodyClassName="space-y-4">
      <p className="text-xs text-muted-foreground">
        This preserves the existing capture-review surface. Screenshot Processor jobs use their own durable staging ledger and do not silently promote these rows.
      </p>
      <Toolbar>
        <SearchInput value={q} onChange={setQ} placeholder="Search file name, capture id, hash…" />
        <FilterSelect value={status} onChange={setStatus} options={INGEST_OPTS} label="Ingest status" />
      </Toolbar>
      {filtered.length === 0 ? (
        <EmptyState icon={Camera} title="No captures in queue" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border scrollbar-thin">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-secondary/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                <th className="px-3 py-2 font-semibold">File</th>
                <th className="px-3 py-2 font-semibold">Type</th>
                <th className="px-3 py-2 font-semibold">Ingest Status</th>
                <th className="px-3 py-2 font-semibold">OCR</th>
                <th className="px-3 py-2 font-semibold">Route</th>
                <th className="px-3 py-2 font-semibold">Obs</th>
                <th className="px-3 py-2 font-semibold">Review</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((capture) => {
                const ingest = INGEST_STATUS[capture.ingest_status] || INGEST_STATUS.queued;
                return (
                  <tr
                    key={capture.id}
                    onClick={() => open.capture(capture.capture_id)}
                    className="cursor-pointer border-b border-border/50 transition hover:bg-secondary/40"
                  >
                    <td className="px-3 py-2.5">
                      <div className="font-mono text-xs font-semibold text-foreground">{capture.file_name}</div>
                      <div className="mt-0.5"><SyntheticDataBadge synthetic={capture.synthetic_flag} /></div>
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground">{capture.capture_type}</td>
                    <td className="px-3 py-2.5"><StatusChip tone={ingest.tone} label={ingest.label} /></td>
                    <td className="px-3 py-2.5"><QualityCell score={capture.ocr_quality_score} /></td>
                    <td className="px-3 py-2.5"><QualityCell score={capture.route_quality_score} /></td>
                    <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{capture.linked_observation_count ?? 0}</td>
                    <td className="px-3 py-2.5">
                      {capture.manual_review_required
                        ? <span className="flex items-center gap-1 text-[10px] font-semibold text-[hsl(38_100%_62%)]"><AlertTriangle className="h-3 w-3" /> Required</span>
                        : <span className="text-[10px] text-muted-foreground">—</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function SettingSelect({ label, value, onChange, options }) {
  return (
    <label className="space-y-1.5">
      <span className="text-xs font-semibold text-foreground">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs text-foreground"
      >
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>{optionLabel}</option>
        ))}
      </select>
    </label>
  );
}

function SettingToggle({ label, checked, onChange }) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/20 px-3 py-2.5">
      <span className="text-xs font-semibold text-foreground">{label}</span>
      <input
        type="checkbox"
        checked={Boolean(checked)}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 accent-primary"
      />
    </label>
  );
}

function SettingNumber({ label, value, onChange, suffix, min, max }) {
  return (
    <label className="space-y-1.5">
      <span className="text-xs font-semibold text-foreground">{label}</span>
      <div className="flex items-center gap-2">
        <input
          type="number"
          min={min}
          max={max}
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs text-foreground"
        />
        <span className="text-xs text-muted-foreground">{suffix}</span>
      </div>
    </label>
  );
}

function MiniMetric({ label, value }) {
  return (
    <div className="rounded-lg border border-border bg-muted/20 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 font-mono text-sm font-semibold text-foreground">{value ?? 0}</div>
    </div>
  );
}

function QualityCell({ score }) {
  const pct = score == null ? 0 : Math.round(score * 100);
  const color = pct >= 75 ? "hsl(142 70% 55%)" : pct >= 50 ? "hsl(38 100% 56%)" : "hsl(4 90% 62%)";
  return (
    <div className="flex items-center gap-1.5">
      <span className="font-mono text-xs font-semibold" style={{ color }}>{pct}%</span>
      <div className="h-1.5 w-8 overflow-hidden rounded-full bg-secondary">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}
