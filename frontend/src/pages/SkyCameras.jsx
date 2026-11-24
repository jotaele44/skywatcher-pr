import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Camera, ClipboardCheck, RefreshCw, Search, Upload, Video } from "lucide-react";

import PageHeader from "@/components/skywatcher/PageHeader";
import CameraCard, { CATEGORY_LABELS } from "@/components/skywatcher/CameraCard";
import { federation } from "@/api/federationClient";

const CATEGORIES = Object.keys(CATEGORY_LABELS);
const PLAYERS_KEY = "skywatcher.skyCameras.showPlayers";

function readPlayersPreference() {
  try {
    return window.localStorage.getItem(PLAYERS_KEY) !== "off";
  } catch {
    return true;
  }
}

function writePlayersPreference(on) {
  try {
    window.localStorage.setItem(PLAYERS_KEY, on ? "on" : "off");
  } catch {
    // storage unavailable (private window); the toggle still works for this visit
  }
}

function errorText(error) {
  const detail = error?.data?.detail;
  if (typeof detail === "string") return detail;
  return String(error?.message ?? error);
}

function CoverageStrip({ coverage }) {
  if (!coverage) return null;
  const gaps = coverage.categories_without_cameras || [];
  return (
    <section
      aria-label="Coverage"
      className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-border bg-card/60 px-3 py-2 text-xs text-muted-foreground"
    >
      <span>
        <strong className="text-foreground">{coverage.camera_count}</strong> cameras
      </span>
      <span>
        <strong className="text-foreground">{coverage.online_count}</strong> online at last check
      </span>
      <span>
        <strong className="text-foreground">{`${coverage.municipios_covered}/${coverage.municipio_total}`}</strong> municipalities
      </span>
      {gaps.length ? (
        <span>{`No ${gaps.map((name) => CATEGORY_LABELS[name]?.toLowerCase() || name).join(", ")} cameras yet — help fill the gaps.`}</span>
      ) : null}
    </section>
  );
}

const EMPTY_FORM = {
  title: "",
  url: "",
  categories: [],
  municipality: "",
  lat: "",
  lon: "",
  description: "",
  contributor: "",
  contact: "",
  license: "display-only",
  attest_rights: false,
  attest_consent: false,
};

export function ContributeForm({ municipios, onSubmitted = undefined }) {
  const [mode, setMode] = useState("camera_link");
  const [videoSource, setVideoSource] = useState("link");
  const [form, setForm] = useState(EMPTY_FORM);
  const [file, setFile] = useState(null);
  const [state, setState] = useState({ busy: false, error: "", receipt: null });

  const kind = mode === "camera_link" ? "camera_link" : videoSource === "file" ? "video_upload" : "video_link";
  const set = (field) => (event) => {
    const value = event.target.type === "checkbox" ? event.target.checked : event.target.value;
    setForm((prev) => ({ ...prev, [field]: value }));
  };
  const toggleCategory = (category) =>
    setForm((prev) => ({
      ...prev,
      categories: prev.categories.includes(category)
        ? prev.categories.filter((item) => item !== category)
        : [...prev.categories, category],
    }));

  const problem = useMemo(() => {
    if (!form.title.trim()) return "Give it a title.";
    if (kind === "video_upload" ? !file : !form.url.trim()) {
      return kind === "video_upload" ? "Choose a video file." : "Paste the link.";
    }
    if (kind !== "video_upload" && !/^https:\/\//i.test(form.url.trim())) return "The link must start with https://";
    if (!form.categories.length) return "Choose at least one category.";
    if (!form.attest_rights || !form.attest_consent) return "Confirm both statements below.";
    return "";
  }, [form, file, kind]);

  const submit = async (event) => {
    event.preventDefault();
    if (problem) {
      setState({ busy: false, error: problem, receipt: null });
      return;
    }
    const body = new FormData();
    body.set("kind", kind);
    form.categories.forEach((item) => body.append("categories", item));
    body.set("attest_rights", form.attest_rights ? "true" : "false");
    body.set("attest_consent", form.attest_consent ? "true" : "false");
    const textFields = ["title", "url", "municipality", "lat", "lon", "description", "contributor", "contact", "license"];
    textFields.forEach((key) => {
      const value = String(form[key] ?? "").trim();
      if (key === "url" && kind === "video_upload") return;
      if (value) body.set(key, value);
    });
    if (kind === "video_upload" && file) body.set("file", file);
    setState({ busy: true, error: "", receipt: null });
    try {
      const receipt = await federation.skyCameras.submit(body);
      setState({ busy: false, error: "", receipt });
      setForm(EMPTY_FORM);
      setFile(null);
      onSubmitted?.(receipt);
    } catch (error) {
      setState({ busy: false, error: errorText(error), receipt: null });
    }
  };

  const tabClass = (active) =>
    `rounded-md px-3 py-1.5 text-xs font-medium ${active ? "bg-primary/15 text-primary ring-1 ring-primary/30" : "text-muted-foreground hover:bg-secondary"}`;
  const input = "w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-sm text-foreground";

  return (
    <form onSubmit={submit} aria-label="Contribute" className="space-y-3 rounded-xl border border-border bg-card/70 p-4" noValidate>
      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="What are you sharing?">
        <button type="button" role="radio" aria-checked={mode === "camera_link"} className={tabClass(mode === "camera_link")} onClick={() => setMode("camera_link")}>
          Suggest a public camera
        </button>
        <button type="button" role="radio" aria-checked={mode === "video"} className={tabClass(mode === "video")} onClick={() => setMode("video")}>
          Share your video
        </button>
      </div>
      <p className="text-xs text-muted-foreground">
        Every submission is reviewed before it appears. We never publish your contact details.
        {mode === "camera_link"
          ? " Suggest only cameras their owner already shows to the public."
          : ` Videos are limited to MP4, MOV or WebM, up to 100 MB. A link to your own YouTube or Vimeo video can be embedded.`}
      </p>

      {mode === "video" ? (
        <div className="flex gap-4 text-sm" role="radiogroup" aria-label="Video source">
          <label className="inline-flex items-center gap-1.5">
            <input type="radio" name="video-source" checked={videoSource === "link"} onChange={() => setVideoSource("link")} />
            Link (YouTube, Vimeo…)
          </label>
          <label className="inline-flex items-center gap-1.5">
            <input type="radio" name="video-source" checked={videoSource === "file"} onChange={() => setVideoSource("file")} />
            Upload a file
          </label>
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-xs text-muted-foreground sm:col-span-2">
          Title
          <input className={input} value={form.title} onChange={set("title")} maxLength={160} required />
        </label>
        {kind === "video_upload" ? (
          <label className="space-y-1 text-xs text-muted-foreground sm:col-span-2">
            Video file
            <input
              className={input}
              type="file"
              accept="video/mp4,video/quicktime,video/webm"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
            />
          </label>
        ) : (
          <label className="space-y-1 text-xs text-muted-foreground sm:col-span-2">
            {mode === "camera_link" ? "Camera page link (https://…)" : "Video link (https://…)"}
            <input className={input} type="url" inputMode="url" value={form.url} onChange={set("url")} maxLength={2048} />
          </label>
        )}
      </div>

      <fieldset className="space-y-1">
        <legend className="text-xs text-muted-foreground">What does it show?</legend>
        <div className="flex flex-wrap gap-2">
          {CATEGORIES.map((category) => (
            <label key={category} className="inline-flex items-center gap-1.5 text-sm">
              <input type="checkbox" checked={form.categories.includes(category)} onChange={() => toggleCategory(category)} />
              {CATEGORY_LABELS[category]}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-3">
        <label className="space-y-1 text-xs text-muted-foreground">
          Municipality (optional)
          <select className={input} value={form.municipality} onChange={set("municipality")}>
            <option value="">—</option>
            {municipios.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-xs text-muted-foreground">
          Latitude (optional)
          <input className={input} inputMode="decimal" value={form.lat} onChange={set("lat")} placeholder="18.46" />
        </label>
        <label className="space-y-1 text-xs text-muted-foreground">
          Longitude (optional)
          <input className={input} inputMode="decimal" value={form.lon} onChange={set("lon")} placeholder="-66.10" />
        </label>
      </div>

      <label className="block space-y-1 text-xs text-muted-foreground">
        Description (optional)
        <textarea className={input} rows={2} value={form.description} onChange={set("description")} maxLength={1000} />
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-xs text-muted-foreground">
          Credit me as (optional, public)
          <input className={input} value={form.contributor} onChange={set("contributor")} maxLength={80} />
        </label>
        <label className="space-y-1 text-xs text-muted-foreground">
          Contact for the reviewer (optional, private)
          <input className={input} value={form.contact} onChange={set("contact")} maxLength={160} />
        </label>
      </div>

      {mode === "video" ? (
        <fieldset className="space-y-1">
          <legend className="text-xs text-muted-foreground">License</legend>
          <label className="mr-4 inline-flex items-center gap-1.5 text-sm">
            <input type="radio" name="license" checked={form.license === "display-only"} onChange={() => setForm((prev) => ({ ...prev, license: "display-only" }))} />
            Show it here only (all rights reserved)
          </label>
          <label className="inline-flex items-center gap-1.5 text-sm">
            <input type="radio" name="license" checked={form.license === "cc-by-4.0"} onChange={() => setForm((prev) => ({ ...prev, license: "cc-by-4.0" }))} />
            CC BY 4.0
          </label>
        </fieldset>
      ) : null}

      <div className="space-y-1.5 text-sm">
        <label className="flex items-start gap-2">
          <input type="checkbox" className="mt-1" checked={form.attest_rights} onChange={set("attest_rights")} />
          <span>
            {mode === "camera_link"
              ? "This camera is already shown to the public by its owner."
              : "I recorded this video or have the right to share it."}
          </span>
        </label>
        <label className="flex items-start gap-2">
          <input type="checkbox" className="mt-1" checked={form.attest_consent} onChange={set("attest_consent")} />
          <span>It shows a public place and no identifiable people without their consent, and no private interiors.</span>
        </label>
      </div>

      {state.error ? (
        <p role="alert" className="flex items-center gap-1.5 text-xs text-rose-300">
          <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
          {state.error}
        </p>
      ) : null}
      {state.receipt ? (
        <p role="status" className="text-xs text-emerald-300">{state.receipt.message}</p>
      ) : null}
      <button
        type="submit"
        disabled={state.busy}
        className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-60"
      >
        <Upload className="h-4 w-4" aria-hidden="true" />
        {state.busy ? "Sending…" : "Send for review"}
      </button>
    </form>
  );
}

function ReviewQueue({ onChanged }) {
  const [status, setStatus] = useState("pending");
  const [state, setState] = useState({ loading: true, error: "", rows: [] });
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ ...prev, loading: true, error: "" }));
    federation.skyCameras
      .submissions(status)
      .then((payload) => !cancelled && setState({ loading: false, error: "", rows: payload.submissions || [] }))
      .catch((error) => {
        if (cancelled) return;
        const denied = error?.status === 401 || error?.status === 403;
        setState({
          loading: false,
          rows: [],
          error: denied ? "Reviewing needs write access (a local network, or the PRII write token)." : errorText(error),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [status, reload]);

  const decide = async (id, decision) => {
    try {
      await federation.skyCameras.decide(id, decision);
      setReload((value) => value + 1);
      onChanged?.();
    } catch (error) {
      setState((prev) => ({ ...prev, error: errorText(error) }));
    }
  };

  return (
    <section aria-label="Review queue" className="space-y-3 rounded-xl border border-border bg-card/70 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-foreground">Review queue</h2>
        <select aria-label="Submission status" className="rounded-md border border-border bg-background px-2 py-1 text-xs" value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="removed">Removed</option>
        </select>
      </div>
      {state.error ? <p role="alert" className="text-xs text-amber-200">{state.error}</p> : null}
      {state.loading ? <p className="text-xs text-muted-foreground">Loading…</p> : null}
      {!state.loading && !state.error && !state.rows.length ? (
        <p className="text-xs text-muted-foreground">{`No ${status} submissions.`}</p>
      ) : null}
      <ul className="space-y-2">
        {state.rows.map((row) => (
          <li key={row.id} className="space-y-1.5 rounded-lg border border-border bg-secondary/20 p-3 text-xs">
            <p className="text-sm font-semibold text-foreground">{row.title}</p>
            <p className="text-muted-foreground">
              {[row.kind.replace("_", " "), row.municipality, row.categories.join(", "), row.license, row.contributor && `credit: ${row.contributor}`, row.contact && `contact: ${row.contact}`]
                .filter(Boolean)
                .join(" · ")}
            </p>
            {row.url ? (
              <a href={row.url} target="_blank" rel="noopener noreferrer" className="break-all text-primary hover:underline">{row.url}</a>
            ) : null}
            {row.media_url ? (
              <video src={row.media_url} controls preload="metadata" className="max-h-48 rounded bg-black" aria-label={`Preview: ${row.title}`} />
            ) : null}
            {row.description ? <p className="text-muted-foreground">{row.description}</p> : null}
            <div className="flex gap-2">
              {row.status === "pending" ? (
                <>
                  <button type="button" onClick={() => decide(row.id, "approved")} className="rounded-md bg-emerald-600/80 px-2.5 py-1 font-semibold text-white">Approve</button>
                  <button type="button" onClick={() => decide(row.id, "rejected")} className="rounded-md bg-secondary px-2.5 py-1 font-semibold text-foreground">Reject</button>
                </>
              ) : null}
              {row.status === "approved" ? (
                <button type="button" onClick={() => decide(row.id, "removed")} className="rounded-md bg-rose-600/80 px-2.5 py-1 font-semibold text-white">Take down</button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function SkyCameras() {
  const [category, setCategory] = useState("");
  const [municipality, setMunicipality] = useState("");
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [showPlayers, setShowPlayers] = useState(readPlayersPreference);
  const [panel, setPanel] = useState(null); // "contribute" | "review" | null
  const [list, setList] = useState({ loading: true, error: "", payload: null });
  const [coverage, setCoverage] = useState(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(id);
  }, [query]);

  useEffect(() => {
    let cancelled = false;
    setList((prev) => ({ ...prev, loading: true, error: "" }));
    federation.skyCameras
      .list({ category, municipality, q: debounced })
      .then((payload) => !cancelled && setList({ loading: false, error: "", payload }))
      .catch((error) => !cancelled && setList({ loading: false, error: errorText(error), payload: null }));
    return () => {
      cancelled = true;
    };
  }, [category, municipality, debounced, reload]);

  useEffect(() => {
    let cancelled = false;
    federation.skyCameras
      .coverage()
      .then((payload) => !cancelled && setCoverage(payload))
      .catch(() => !cancelled && setCoverage(null));
    return () => {
      cancelled = true;
    };
  }, [reload]);

  const togglePlayers = useCallback(() => {
    setShowPlayers((prev) => {
      writePlayersPreference(!prev);
      return !prev;
    });
  }, []);

  const [municipios, setMunicipios] = useState([]);
  useEffect(() => {
    if (list.payload?.municipios?.length) setMunicipios(list.payload.municipios);
  }, [list.payload]);
  const cameras = list.payload?.cameras || [];
  const chip = (active) =>
    `rounded-full border px-3 py-1 text-xs font-medium transition ${active ? "border-primary/40 bg-primary/15 text-primary" : "border-border text-muted-foreground hover:bg-secondary"}`;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Sky Cameras"
        subtitle="Public live cameras of Puerto Rico's sky, beaches, mountains, rivers and lakes — plus video shared by the community"
        icon={Video}
        actions={
          <div className="flex flex-wrap gap-2">
            <button type="button" aria-pressed={showPlayers} onClick={togglePlayers} className={chip(showPlayers)}>
              {showPlayers ? "Players on" : "Links only"}
            </button>
            <button type="button" aria-expanded={panel === "contribute"} onClick={() => setPanel(panel === "contribute" ? null : "contribute")} className={chip(panel === "contribute")}>
              <Camera className="mr-1 inline h-3.5 w-3.5" aria-hidden="true" />
              Contribute
            </button>
            <button type="button" aria-expanded={panel === "review"} onClick={() => setPanel(panel === "review" ? null : "review")} className={chip(panel === "review")}>
              <ClipboardCheck className="mr-1 inline h-3.5 w-3.5" aria-hidden="true" />
              Review queue
            </button>
          </div>
        }
      />

      <CoverageStrip coverage={coverage} />

      {panel === "contribute" ? <ContributeForm municipios={municipios} /> : null}
      {panel === "review" ? <ReviewQueue onChanged={() => setReload((value) => value + 1)} /> : null}

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Category">
          <button type="button" aria-pressed={!category} className={chip(!category)} onClick={() => setCategory("")}>All</button>
          {CATEGORIES.map((name) => (
            <button key={name} type="button" aria-pressed={category === name} className={chip(category === name)} onClick={() => setCategory(category === name ? "" : name)}>
              {CATEGORY_LABELS[name]}
            </button>
          ))}
        </div>
        <select
          aria-label="Municipality"
          className="rounded-md border border-border bg-background px-2 py-1.5 text-xs"
          value={municipality}
          onChange={(event) => setMunicipality(event.target.value)}
        >
          <option value="">All municipalities</option>
          {municipios.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
        <label className="relative">
          <span className="sr-only">Search cameras</span>
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search cameras"
            className="rounded-md border border-border bg-background py-1.5 pl-7 pr-2 text-xs"
          />
        </label>
        <button type="button" onClick={() => setReload((value) => value + 1)} aria-label="Refresh" className="rounded-md p-1.5 text-muted-foreground hover:bg-secondary">
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>

      {list.error ? (
        <p role="alert" className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{`Cameras unavailable: ${list.error}`}</p>
      ) : null}
      {!list.loading && !list.error && !cameras.length ? (
        <p className="text-sm text-muted-foreground">No cameras match yet. Know one? Use Contribute.</p>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {cameras.map((camera) => (
          <CameraCard key={camera.id} camera={camera} showPlayers={showPlayers} />
        ))}
      </div>
      <p className="text-[11px] text-muted-foreground">
        Streams belong to their owners and open on their sites. Players appear only where the owner publishes an
        embeddable stream. Status comes from the last automated check and may lag.
      </p>
    </div>
  );
}
