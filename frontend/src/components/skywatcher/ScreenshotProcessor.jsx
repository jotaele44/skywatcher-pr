import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Camera, FileUp, Pause, Play, ShieldCheck, AlertTriangle, Archive } from "lucide-react";
import { federation } from "@/api/federationClient";

const ACCEPT = ".png,.jpg,.jpeg,.heic,.heif,.webp,.tif,.tiff,.bmp,.pdf,.zip";
const DONE = new Set(["READY_FOR_REVIEW", "COMPLETE", "COMPLETE_WITH_BLOCKERS", "CANCELLED"]);
const BUTTON = "rounded-md border border-border bg-secondary/40 px-3 py-2 text-xs font-semibold text-foreground disabled:cursor-not-allowed disabled:opacity-40";
const RUN_KEY = "skywatcher_screenshot_run_id";

function asBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Cannot read " + file.name));
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.readAsDataURL(file);
  });
}

function SourcePreview({ jobId, itemId, token }) {
  const [src, setSrc] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = async () => {
    setBusy(true); setError("");
    try {
      const response = await federation.request(
        "/screenshot-runs/" + encodeURIComponent(jobId) + "/items/" + itemId + "/image",
        { token }
      );
      setSrc("data:" + response.mime_type + ";base64," + response.data_base64);
    } catch (exc) { setError(exc.message); } finally { setBusy(false); }
  };
  return <div className="mt-3 space-y-2">
    {!src && <button type="button" className={BUTTON} disabled={busy || !token} onClick={load}>
      {busy ? "Loading source..." : "View original source image"}
    </button>}
    {src && <img src={src} alt="Original uploaded image used for extraction review" className="max-h-[30rem] max-w-full rounded border border-border object-contain" />}
    {error && <p className="text-xs text-amber-300">{error}</p>}
  </div>;
}

export default function ScreenshotProcessor() {
  const [token, setToken] = useState("");
  const [files, setFiles] = useState([]);
  const [reprocess, setReprocess] = useState(false);
  const [perceptualDiscovery, setPerceptualDiscovery] = useState(false);
  const [renderedTrack, setRenderedTrack] = useState(false);
  const [existingGeoref, setExistingGeoref] = useState(true);
  const [pdfScale, setPdfScale] = useState(1.0);
  const [activeTab, setActiveTab] = useState("upload");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState(() => sessionStorage.getItem(RUN_KEY) || "");
  const [job, setJob] = useState(null);
  const [results, setResults] = useState(null);
  const [history, setHistory] = useState([]);
  const [notes, setNotes] = useState({});
  const totalSize = useMemo(() => files.reduce((n, f) => n + f.size, 0), [files]);
  const canRun = !!token && !busy && files.length > 0 && files.length <= 32 && totalSize <= 40 * 1048576;
  const call = (path, options = {}) => federation.request("/screenshot-runs" + path, { ...options, token });

  useEffect(() => {
    if (!token || !jobId) return undefined;
    let live = true;
    const tick = async () => {
      try {
        const current = await federation.request("/screenshot-runs/" + encodeURIComponent(jobId), { token });
        if (!live) return;
        setJob(current);
        if (DONE.has(current.status)) {
          const data = await federation.request("/screenshot-runs/" + encodeURIComponent(jobId) + "/results", { token });
          if (live) setResults(data);
        }
      } catch (exc) {
        if (live) setError(exc.message);
      }
    };
    tick();
    const interval = window.setInterval(tick, 1600);
    return () => { live = false; window.clearInterval(interval); };
  }, [token, jobId]);

  const execute = async () => {
    if (!canRun) return;
    setBusy(true); setError(""); setResults(null);
    try {
      const upload = await Promise.all(files.map(async (f) => ({ name: f.name, data_base64: await asBase64(f) })));
      const created = await call("", {
        method: "POST",
        body: { files: upload, settings: {
          ocr_mode: "local",
          vision_mode: "off",
          duplicate_mode: perceptualDiscovery ? "exact+perceptual_discovery" : "exact",
          rendered_track_mode: renderedTrack ? "local" : "off",
          georeference_mode: existingGeoref ? "existing_only" : "off",
          reprocess_existing: reprocess,
          pdf_scale: pdfScale,
        } },
      });
      setJobId(created.job_id); sessionStorage.setItem(RUN_KEY, created.job_id);
      setJob(created); setActiveTab("execution");
    } catch (exc) { setError(exc.message); } finally { setBusy(false); }
  };
  const control = async (action) => {
    try { setJob(await call("/" + encodeURIComponent(jobId) + "/control", { method: "POST", body: { action } })); }
    catch (exc) { setError(exc.message); }
  };
  const loadResults = async () => {
    try { setResults(await call("/" + encodeURIComponent(jobId) + "/results")); }
    catch (exc) { setError(exc.message); }
  };
  const refreshHistory = async () => {
    try { setHistory((await call("")).jobs || []); }
    catch (exc) { setError(exc.message); }
  };
  const exportMflProjection = () => {
    if (!results?.items?.length) return;
    const payload = {
      schema_version: "skywatcher.screenshot.mfl_staging_export.v1",
      source_job_id: jobId,
      canonical_append_authorized: false,
      items: results.items.map((item) => ({
        item_id: item.item_id, filename_raw: item.filename_raw,
        screenshot_sha256: item.sha256,
        processing_status: item.status,
        master_log_projection: item.master_log_projection,
      })),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "skywatcher-screenshot-mfl-staging-" + jobId + ".json";
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 2000);
  };
  const chooseRun = (id) => {
    setJobId(id); sessionStorage.setItem(RUN_KEY, id); setResults(null); setActiveTab("execution");
  };
  const review = async (item) => {
    try {
      setResults(await call("/" + encodeURIComponent(jobId) + "/review", {
        method: "POST", body: { item_id: item, note: notes[item] || "" },
      }));
    } catch (exc) { setError(exc.message); }
  };

  return (
    <section className="space-y-4 rounded-xl border border-primary/30 bg-card p-4" aria-label="Screenshot Processor">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-bold"><Camera className="h-5 w-5" /> Screenshot Processor</h2>
          <p className="text-xs text-muted-foreground">Local RLSM extraction and review-only flight reconciliation. No canonical record changes.</p>
        </div>
        <Link to="/flight-archive" className={BUTTON}><Archive className="mr-1 inline h-4 w-4" /> Flight Archive</Link>
      </header>
      <label className="block max-w-xl text-xs font-semibold">Screenshot-intake access token
        <input type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)}
          placeholder="Required — not stored by this form" className="mt-2 block w-full rounded border border-border bg-background px-3 py-2 text-sm" />
      </label>
      <p className="text-xs text-muted-foreground">Configure SKYWATCHER_SCREENSHOT_TOKEN on the local backend. This form keeps the token in memory.</p>
      <div role="tablist" aria-label="Screenshot processing sections" className="flex flex-wrap gap-2">
        {[["upload", "Upload & settings"], ["execution", "Execution & results"], ["history", "Processing history"]].map(([id, label]) =>
          <button key={id} type="button" role="tab" aria-selected={activeTab === id} className={BUTTON + (activeTab === id ? " border-primary text-primary" : "")}
            onClick={() => { setActiveTab(id); if (id === "history" && token) refreshHistory(); }}>{label}</button>)}
      </div>

      {activeTab === "upload" && <div role="tabpanel" className="space-y-4">
        <label className="block rounded-lg border border-dashed border-primary/40 bg-muted/20 p-5 text-sm">
          <FileUp className="mb-2 h-6 w-6" /> Select individual screenshots or mixed PDF / ZIP batches
          <input type="file" accept={ACCEPT} multiple onChange={(e) => { setFiles(Array.from(e.target.files || [])); setError(""); }}
            className="mt-3 block w-full text-xs file:mr-3 file:rounded file:border file:border-border file:bg-background file:px-3 file:py-2" />
        </label>
        <div className="grid gap-2 text-xs sm:grid-cols-3">
          <div className="rounded border border-border p-3">Sources <strong className="block mt-1 text-lg">{files.length}</strong></div>
          <div className="rounded border border-border p-3">Size <strong className="block mt-1 text-lg">{(totalSize / 1048576).toFixed(1)} MiB</strong></div>
          <div className="rounded border border-border p-3">Limits <strong className="block mt-1 text-lg">32 / 40 MiB</strong></div>
        </div>
        <div className="rounded border border-border p-3 text-xs">
          <h3 className="font-semibold">Preprocessing profile — initial secured implementation</h3>
          <p className="mt-2">Local OCR: enabled · Exact SHA-256 reuse: enabled · Raw manifestation provenance: preserved</p>
          <label className="mt-3 flex items-center gap-2"><input type="checkbox" checked={reprocess} onChange={(e) => setReprocess(e.target.checked)} /> Reprocess existing screenshot OCR (append-only new attempt)</label>
          <label className="mt-2 flex items-center gap-2"><input type="checkbox" checked={perceptualDiscovery} onChange={(e) => setPerceptualDiscovery(e.target.checked)} /> Discover perceptually similar screenshots (discovery only; never dedup identity)</label>
          <label className="mt-2 flex items-center gap-2"><input type="checkbox" checked={renderedTrack} onChange={(e) => setRenderedTrack(e.target.checked)} /> Analyze rendered track pixels (not raw telemetry)</label>
          <label className="mt-2 flex items-center gap-2"><input type="checkbox" checked={existingGeoref} onChange={(e) => setExistingGeoref(e.target.checked)} /> Reuse existing supported RLSM georeference receipts when present</label>
          <label className="mt-2 block">PDF render resolution
            <select className="ml-2 rounded border border-border bg-background px-2 py-1" value={pdfScale} onChange={(e) => setPdfScale(Number(e.target.value))}>
              <option value={1}>Standard 1.0×</option><option value={1.5}>Enhanced 1.5×</option>
            </select>
          </label>
          <p className="mt-2 text-muted-foreground">External vision remains withheld pending independent validation. Perceptual similarity is discovery-only; rendered trails are never native trajectories. PDF rendering requires optional PyMuPDF.</p>
        </div>
        <button type="button" disabled={!canRun} onClick={execute}
          className="rounded border border-primary bg-primary/10 px-5 py-2 text-sm font-bold text-primary disabled:opacity-40">
          {busy ? "Staging…" : "Execute Processing"}
        </button>
      </div>}

      {activeTab === "execution" && <div role="tabpanel" className="space-y-3">
        {!job ? <p className="text-sm text-muted-foreground">Upload or select a batch. Reenter your token to restore progress after refreshing the page.</p> : <>
          <p className="break-all font-mono text-xs">{job.job_id} · {job.status}</p>
          <progress className="h-3 w-full" value={job.complete || 0} max={job.total || 1} aria-label="Processing progress" />
          <p className="text-sm">{job.complete}/{job.total} manifestations processed ({Math.round((job.progress || 0) * 100)}%)</p>
          {job.current_stage && <p className="font-mono text-xs text-primary">Current stage: {job.current_stage}</p>}
          <div className="flex flex-wrap gap-2">{Object.entries(job.counts || {}).map(([k, n]) =>
            <span key={k} className="rounded border border-border px-2 py-1 font-mono text-xs">{k}: {n}</span>)}</div>
          <div className="flex flex-wrap gap-2">
            {["QUEUED", "RUNNING"].includes(job.status) && <button className={BUTTON} onClick={() => control("pause")}><Pause className="mr-1 inline h-3 w-3" /> Pause</button>}
            {job.status === "PAUSED" && <button className={BUTTON} onClick={() => control("resume")}><Play className="mr-1 inline h-3 w-3" /> Resume</button>}
            {["QUEUED", "RUNNING", "PAUSED"].includes(job.status) && <button className={BUTTON} onClick={() => control("cancel")}>Cancel remaining</button>}
            <button className={BUTTON} onClick={loadResults}>Refresh detailed results</button>
            {!!results?.items?.length && <button type="button" className={BUTTON} onClick={exportMflProjection}>Export staged MFL field coverage</button>}
          </div>
          {(results?.items || []).map((item) => <details key={item.item_id} className="rounded border border-border p-3 text-xs">
            <summary className="cursor-pointer font-semibold">{item.filename_raw} · {item.status}{item.was_reused ? " · existing OCR reused" : ""}</summary>
            {item.error && <p className="mt-2 text-amber-300">{item.error}</p>}
            {item.sha256 && <SourcePreview jobId={jobId} itemId={item.item_id} token={token} />}
            <div className="mt-2 space-y-1">{Object.entries(item.fields || {}).map(([k, v]) =>
              <p key={k}><strong>{k}:</strong> {String(v.value)} <span className="text-muted-foreground">({v.certification})</span></p>)}</div>
            <p className="mt-2">Flight-record discovery candidates: {item.candidates?.length || 0}. Candidate matches are not identity.</p>
            {!!item.perceptual_duplicates?.length && <div className="mt-2 rounded border border-border/70 p-2">
              <p className="font-semibold">Perceptual similarity candidates: {item.perceptual_duplicates.length}</p>
              <p className="text-muted-foreground">Discovery only — same-looking pixels do not establish screenshot, flight, or event identity.</p>
              {item.perceptual_duplicates.slice(0, 10).map((candidate) =>
                <p key={candidate.screenshot_id} className="font-mono">RLSM #{candidate.screenshot_id} · Hamming {candidate.hamming_distance} · {candidate.certification}</p>)}
              {item.perceptual_duplicates.length > 10 && <p className="text-muted-foreground">+ {item.perceptual_duplicates.length - 10} more preserved candidates</p>}
            </div>}
            {item.rendered_track?.status && item.rendered_track.status !== "NOT_REQUESTED" && <div className="mt-2 rounded border border-border/70 p-2">
              <p className="font-semibold">Rendered-track observation: {item.rendered_track.status}</p>
              {item.rendered_track.path_shape && <p className="font-mono">shape={item.rendered_track.path_shape} · confidence={item.rendered_track.confidence}</p>}
              <p className="text-muted-foreground">Evidence type: RENDERED_TRAIL · raw_trajectory=false.</p>
            </div>}
            {!!item.georeference_evidence?.length && <div className="mt-2 rounded border border-border/70 p-2">
              <p className="font-semibold">Persisted georeference receipts: {item.georeference_evidence.length}</p>
              {item.georeference_evidence.map((receipt) =>
                <p key={receipt.georef_version} className="font-mono">{receipt.georef_version} · {receipt.status} · {receipt.method} · {receipt.certification}</p>)}
            </div>}
            {item.master_log_projection && <div className="mt-2 rounded border border-border/70 p-2">
              <p className="font-semibold">Master Flight Log v1 compatibility: {item.master_log_projection.proposed_count} proposed / {item.master_log_projection.withheld_count} withheld</p>
              <p className="text-muted-foreground">NONCANONICAL — extraction does not authorize a new flight record.</p>
              {Object.entries(item.master_log_projection.proposed_fields || {}).map(([key, field]) =>
                <p key={key} className="font-mono">{key}: {String(field.value_raw)} (provisional)</p>)}
              <details className="mt-2"><summary>View withheld fields and evidence requirements</summary>
                {Object.entries(item.master_log_projection.withheld_fields || {}).map(([key, reason]) =>
                  <p key={key} className="mt-1"><strong>{key}</strong>: {reason}</p>)}
              </details>
            </div>}
            {(item.contradictions || []).map((c, idx) => <p key={idx} className="mt-1 text-amber-300">{c.class}: {c.note}</p>)}
            {item.status === "NEEDS_REVIEW" && <div className="mt-3 space-y-2">
              <label className="block">Manual review notes (not flight certification)
                <textarea value={notes[item.item_id] || ""} onChange={(e) => setNotes((old) => ({ ...old, [item.item_id]: e.target.value }))}
                  className="mt-1 block min-h-16 w-full rounded border border-border bg-background p-2" />
              </label>
              <button className={BUTTON} disabled={(notes[item.item_id] || "").trim().length < 3} onClick={() => review(item.item_id)}>
                <ShieldCheck className="mr-1 inline h-3 w-3" /> Record review
              </button>
            </div>}
            {item.review_note && <p className="mt-2">Review note: {item.review_note}</p>}
          </details>)}
          {job.status === "COMPLETE_WITH_BLOCKERS" && <p className="flex items-center gap-2 text-xs text-amber-300">
            <AlertTriangle className="h-4 w-4" /> The batch has unresolved inputs and is not certified.
          </p>}
        </>}
      </div>}

      {activeTab === "history" && <div role="tabpanel" className="space-y-2">
        <button className={BUTTON} disabled={!token} onClick={refreshHistory}>Refresh history</button>
        {history.map((h) => <button key={h.job_id} type="button" className="flex w-full flex-wrap justify-between gap-2 rounded border border-border p-2 text-left text-xs" onClick={() => chooseRun(h.job_id)}>
          <span className="break-all font-mono">{h.job_id}</span><span>{h.complete}/{h.total}</span><span>{h.status}</span>
        </button>)}
        {!history.length && <p className="text-xs text-muted-foreground">No history loaded.</p>}
      </div>}
      {error && <p role="alert" className="rounded border border-red-400/40 bg-red-500/10 p-3 text-xs text-red-300">{error}</p>}
    </section>
  );
}
