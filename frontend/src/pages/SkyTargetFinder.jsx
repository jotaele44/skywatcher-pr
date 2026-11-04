import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Clock,
  Copy,
  Heart,
  MapPin,
  Orbit,
  RefreshCw,
  Satellite,
  Search,
  Sparkles,
  Star,
  Sun,
  Telescope,
} from "lucide-react";

import PageHeader from "@/components/skywatcher/PageHeader";
import SkyChart from "@/components/skywatcher/SkyChart";
import { federation } from "@/api/federationClient";
import { toast } from "@/components/ui/use-toast";
import {
  describeVisibility,
  formatAltitudeBadge,
  formatCoordinateClipboard,
  formatLocalDateTime,
  formatLocalTime,
  toUtcSeconds,
} from "@/lib/skyProjection";
import {
  favoriteLookup,
  isFavorite,
  loadFavorites,
  saveFavorites,
  toggleFavorite,
} from "@/lib/skyFavorites";

// San Juan, Puerto Rico — the backend default observer (skywatcher.core.sky.DEFAULT_OBSERVER).
const DEFAULT_OBSERVER = { lat: 18.4655, lon: -66.1057, elev_m: 10 };
const TABS = [
  { id: "recommend", label: "Recommend" },
  { id: "favorites", label: "Favorites" },
  { id: "catalog", label: "Catalog" },
];
const KINDS = [
  { value: "all", label: "All" },
  { value: "star", label: "Stars" },
  { value: "messier", label: "Messier" },
  { value: "caldwell", label: "Caldwell" },
  { value: "solar_system", label: "Solar system" },
  { value: "satellite", label: "Satellites" },
];
const KIND_ICON = {
  star: Star,
  messier: Sparkles,
  caldwell: Sparkles,
  planet: Orbit,
  moon: Orbit,
  sun: Sun,
  satellite: Satellite,
};
const SEARCH_DEBOUNCE_MS = 250;
const LIST_LIMIT = 50;

function toLocalInputValue(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// A datetime-local value is the browser's local wall-clock time.
function localInputToIso(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : toUtcSeconds(date);
}

async function copyCoordinates(target, atUtc, observer) {
  try {
    if (!navigator.clipboard?.writeText) {
      throw new Error("Clipboard access is unavailable in this browser.");
    }
    await navigator.clipboard.writeText(formatCoordinateClipboard(target, atUtc, observer));
    toast({ title: "Coordinates copied", description: target.display });
  } catch (error) {
    toast({
      variant: "destructive",
      title: "Coordinates not copied",
      description: String(error?.message ?? error),
    });
  }
}

function TargetRow({ target, selected, favorite, onSelect, onToggleFavorite, onCopy, extra }) {
  const Icon = KIND_ICON[target.kind] || Star;
  const visibility = target.stale
    ? { state: "UNKNOWN", text: "Position unavailable", note: "" }
    : describeVisibility(target);
  const descriptionId = `sky-target-${target.id.replace(/[^a-z0-9]/gi, "-")}`;
  return (
    <li
      className={`flex items-center gap-3 rounded-lg border px-3 py-2.5 transition ${
        selected ? "border-primary/40 bg-primary/10" : "border-border bg-secondary/20 hover:bg-secondary/40"
      }`}
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary" aria-hidden="true">
        <Icon className="h-4 w-4 text-primary" />
      </span>
      <button
        onClick={() => onSelect(target)}
        type="button"
        aria-label={target.display}
        aria-describedby={descriptionId}
        aria-current={selected ? "true" : undefined}
        className="min-w-0 flex-1 text-left"
      >
        <span className="block truncate text-sm font-semibold text-foreground">{target.display}</span>
        <span id={descriptionId} className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
          <span className={visibility.state === "UP" ? "font-mono text-foreground" : "font-mono"}>
            {visibility.text}
          </span>
          {visibility.note ? <span>{visibility.note}</span> : null}
          {target.match?.field === "alias" ? <span>{`matches ${target.match.text}`}</span> : null}
          {extra}
        </span>
      </button>
      <button
        onClick={() => onToggleFavorite(target)}
        type="button"
        aria-label={favorite ? `Remove ${target.display} from favorites` : `Add ${target.display} to favorites`}
        aria-pressed={favorite}
        className="rounded-md p-1.5 text-muted-foreground transition hover:bg-secondary hover:text-foreground"
      >
        <Heart className={`h-4 w-4 ${favorite ? "fill-rose-400 text-rose-400" : ""}`} />
      </button>
      <button
        onClick={() => onCopy(target)}
        type="button"
        aria-label={`Copy coordinates for ${target.display}`}
        className="rounded-md p-1.5 text-muted-foreground transition hover:bg-secondary hover:text-foreground"
      >
        <Copy className="h-4 w-4" />
      </button>
    </li>
  );
}

function SatelliteNotice({ satellites }) {
  if (!satellites || satellites.state === "AVAILABLE") return null;
  const message =
    satellites.state === "DEPENDENCY_MISSING"
      ? "Satellite propagation is unavailable: the sgp4 package is not installed on the backend."
      : "No Space-Track elements are frozen locally yet, so satellites are not listed. They appear once a Space-Track collection is materialized.";
  return (
    <p role="status" className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
      <Satellite className="mr-1.5 inline h-3.5 w-3.5" />
      {`Satellites ${satellites.state}. ${message}`}
    </p>
  );
}

export default function SkyTargetFinder() {
  const [observer, setObserver] = useState(DEFAULT_OBSERVER);
  const [observerDraft, setObserverDraft] = useState({
    lat: String(DEFAULT_OBSERVER.lat),
    lon: String(DEFAULT_OBSERVER.lon),
    elev_m: String(DEFAULT_OBSERVER.elev_m),
  });
  const [observerError, setObserverError] = useState("");
  const [timeMode, setTimeMode] = useState("now");
  const [customTime, setCustomTime] = useState(() => toLocalInputValue(new Date()));
  const [nowTick, setNowTick] = useState(0);

  const [tab, setTab] = useState("recommend");
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [kind, setKind] = useState("all");
  const [list, setList] = useState({ loading: true, error: "", payload: null });
  const [listReload, setListReload] = useState(0);

  const [favorites, setFavorites] = useState(() => loadFavorites());
  const [selected, setSelected] = useState(null);
  const [fovDeg, setFovDeg] = useState(6);
  const [chart, setChart] = useState({ loading: false, error: "", payload: null });
  const [chartReload, setChartReload] = useState(0);

  const at = timeMode === "now" ? undefined : localInputToIso(customTime);
  const baseParams = useMemo(
    () => ({ lat: observer.lat, lon: observer.lon, elev_m: observer.elev_m, at }),
    [observer, at],
  );

  useEffect(() => {
    const id = setTimeout(() => setDebouncedQuery(query.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [query]);

  const listMode = debouncedQuery ? "search" : tab;
  const favoritesKey = listMode === "favorites" ? favorites.map((item) => item.id).join("|") : "";

  useEffect(() => {
    let cancelled = false;
    setList((previous) => ({ ...previous, loading: true, error: "" }));
    const load = async () => {
      if (listMode === "recommend") return federation.spaceTrack.skyRecommend(baseParams);
      if (listMode === "favorites") {
        const resolved = await Promise.all(
          favorites.map(async (favorite) => {
            try {
              const result = await federation.spaceTrack.skyTargets({
                ...baseParams,
                ...favoriteLookup(favorite),
                limit: 10,
              });
              return result.targets.find((item) => item.id === favorite.id) || { ...favorite, stale: true };
            } catch {
              return { ...favorite, stale: true };
            }
          }),
        );
        return { targets: resolved };
      }
      return federation.spaceTrack.skyTargets({
        ...baseParams,
        q: listMode === "search" ? debouncedQuery : "",
        kind,
        limit: LIST_LIMIT,
      });
    };
    load()
      .then((payload) => {
        if (!cancelled) setList({ loading: false, error: "", payload });
      })
      .catch((error) => {
        if (!cancelled) {
          setList({
            loading: false,
            error: error?.message || "Unable to read the sky catalog from the local backend.",
            payload: null,
          });
        }
      });
    return () => {
      cancelled = true;
    };
    // favoritesKey stands in for `favorites` so toggling a heart only refetches the Favorites tab.
  }, [listMode, debouncedQuery, kind, baseParams, favoritesKey, listReload, nowTick]);

  useEffect(() => {
    if (!selected) return undefined;
    let cancelled = false;
    // Keep the current chart on screen while it refreshes, but never show another target's chart.
    setChart((previous) => ({
      loading: true,
      error: "",
      payload: previous.payload?.target?.id === selected.id ? previous.payload : null,
    }));
    federation.spaceTrack
      .skyChart({ ...baseParams, target: selected.id, fov_deg: fovDeg })
      .then((payload) => {
        if (!cancelled) setChart({ loading: false, error: "", payload });
      })
      .catch((error) => {
        if (!cancelled) {
          setChart({
            loading: false,
            error: error?.message || "Unable to compute the sky chart.",
            payload: null,
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selected, fovDeg, baseParams, chartReload, nowTick]);

  const handleToggleFavorite = useCallback((target) => {
    setFavorites((current) => {
      const next = toggleFavorite(current, target);
      saveFavorites(next);
      return next;
    });
  }, []);

  const listAt = list.payload?.at_utc || chart.payload?.at_utc || at || toUtcSeconds(new Date());
  const listObserver = list.payload?.observer || observer;
  const handleCopyRow = useCallback(
    (target) => copyCoordinates(target, listAt, listObserver),
    [listAt, listObserver],
  );

  const applyObserver = (event) => {
    event.preventDefault();
    const lat = Number(observerDraft.lat);
    const lon = Number(observerDraft.lon);
    const elev = Number(observerDraft.elev_m || 0);
    if (!Number.isFinite(lat) || lat < -90 || lat > 90) {
      setObserverError("Latitude must be between -90 and 90 degrees.");
      return;
    }
    if (!Number.isFinite(lon) || lon < -180 || lon > 180) {
      setObserverError("Longitude must be between -180 and 180 degrees.");
      return;
    }
    if (!Number.isFinite(elev) || elev < -500 || elev > 10000) {
      setObserverError("Elevation must be between -500 and 10000 metres.");
      return;
    }
    setObserverError("");
    setObserver({ lat, lon, elev_m: elev });
  };

  const resetToNow = () => {
    setTimeMode("now");
    setCustomTime(toLocalInputValue(new Date()));
    setNowTick((tick) => tick + 1);
  };

  const targets = list.payload?.targets || [];
  const satellites = list.payload?.satellites;
  const showSatelliteNotice =
    (listMode === "search" || listMode === "catalog") && (kind === "all" || kind === "satellite");
  const darkWindow = list.payload?.dark_window;

  let emptyMessage = "No targets.";
  if (listMode === "search") emptyMessage = `No targets match “${debouncedQuery}”.`;
  else if (listMode === "favorites") emptyMessage = "No favorites yet. Use the heart on any target to keep it here.";
  else if (listMode === "catalog") emptyMessage = "Nothing of this kind is above the horizon right now.";
  else if (listMode === "recommend") emptyMessage = "No well-placed targets tonight from this location.";

  return (
    <div className="space-y-5">
      <PageHeader
        title="Sky Target Finder"
        subtitle="Search stars, Messier and Caldwell objects, planets and frozen Space-Track satellites; computed locally and read-only"
        icon={Telescope}
      />

      <div className="grid gap-3 rounded-xl border border-border bg-secondary/20 p-4 lg:grid-cols-[minmax(0,1fr)_auto]">
        <form onSubmit={applyObserver} className="flex flex-wrap items-end gap-2" aria-label="Observer location">
          <MapPin className="mb-2 h-4 w-4 text-primary" aria-hidden="true" />
          <label className="flex flex-col text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Latitude
            <input
              onChange={(event) => setObserverDraft((draft) => ({ ...draft, lat: event.target.value }))}
              value={observerDraft.lat}
              type="number"
              step="0.0001"
              aria-label="Observer latitude"
              className="mt-1 w-28 rounded-md border border-border bg-secondary px-2 py-1.5 font-mono text-xs text-foreground"
            />
          </label>
          <label className="flex flex-col text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Longitude
            <input
              onChange={(event) => setObserverDraft((draft) => ({ ...draft, lon: event.target.value }))}
              value={observerDraft.lon}
              type="number"
              step="0.0001"
              aria-label="Observer longitude"
              className="mt-1 w-28 rounded-md border border-border bg-secondary px-2 py-1.5 font-mono text-xs text-foreground"
            />
          </label>
          <label className="flex flex-col text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Elevation (m)
            <input
              onChange={(event) => setObserverDraft((draft) => ({ ...draft, elev_m: event.target.value }))}
              value={observerDraft.elev_m}
              type="number"
              step="1"
              aria-label="Observer elevation in metres"
              className="mt-1 w-24 rounded-md border border-border bg-secondary px-2 py-1.5 font-mono text-xs text-foreground"
            />
          </label>
          <button
            type="submit"
            className="rounded-md border border-border bg-secondary px-3 py-1.5 text-xs font-semibold text-foreground transition hover:bg-secondary/80"
          >
            Apply location
          </button>
          {observerError ? <p role="alert" className="w-full text-xs text-red-300">{observerError}</p> : null}
        </form>
        <div className="flex flex-wrap items-end gap-2">
          <Clock className="mb-2 h-4 w-4 text-primary" aria-hidden="true" />
          <label className="flex flex-col text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Observation time (local)
            <input
              onChange={(event) => {
                setCustomTime(event.target.value);
                setTimeMode("custom");
              }}
              value={customTime}
              type="datetime-local"
              aria-label="Observation time (local)"
              className="mt-1 rounded-md border border-border bg-secondary px-2 py-1.5 font-mono text-xs text-foreground"
            />
          </label>
          <button
            onClick={resetToNow}
            type="button"
            aria-pressed={timeMode === "now"}
            className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-semibold transition ${
              timeMode === "now" ? "border-primary/40 bg-primary/15 text-primary" : "border-border bg-secondary text-foreground"
            }`}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Now
          </button>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <section className="space-y-3" aria-label="Sky targets">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <input
              onChange={(event) => setQuery(event.target.value)}
              value={query}
              type="search"
              aria-label="Search sky targets"
              placeholder="Search Messier, Caldwell, stars, planets, satellites"
              className="w-full rounded-lg border border-border bg-secondary py-2 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground"
            />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <div role="tablist" aria-label="Target lists" className="flex gap-1">
              {TABS.map((item) => (
                <button
                  onClick={() => {
                    setTab(item.id);
                    setQuery("");
                    setDebouncedQuery("");
                  }}
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={listMode === item.id}
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${
                    listMode === item.id ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
            {listMode === "catalog" || listMode === "search" ? (
              <select
                onChange={(event) => setKind(event.target.value)}
                value={kind}
                aria-label="Target kind"
                className="rounded-md border border-border bg-secondary px-2 py-1.5 text-xs text-foreground"
              >
                {KINDS.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            ) : null}
          </div>

          {listMode === "recommend" && darkWindow ? (
            <p className="text-xs text-muted-foreground">
              {`Dark sky tonight (Sun below ${String(darkWindow.sun_alt_deg).replace("-", "−")}°): ${formatLocalTime(darkWindow.start_utc)}–${formatLocalTime(darkWindow.end_utc)}`}
            </p>
          ) : null}
          {list.payload?.at_utc ? (
            <p className="text-[11px] text-muted-foreground">
              {`Positions for ${formatLocalDateTime(list.payload.at_utc)} local · ${list.payload.at_utc} · ${listObserver.lat_deg ?? listObserver.lat}, ${listObserver.lon_deg ?? listObserver.lon}`}
            </p>
          ) : null}
          {showSatelliteNotice ? <SatelliteNotice satellites={satellites} /> : null}

          {list.error ? (
            <div role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
              <div className="flex items-center gap-2 font-semibold">
                <AlertTriangle className="h-4 w-4" />
                Sky data unavailable
              </div>
              <p className="mt-1 text-xs">{list.error}</p>
              <button
                onClick={() => setListReload((count) => count + 1)}
                type="button"
                className="mt-3 inline-flex items-center gap-2 rounded-lg border border-border bg-secondary px-3 py-1.5 text-xs font-semibold text-foreground"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Retry
              </button>
            </div>
          ) : null}

          {list.loading && !list.payload ? (
            <p role="status" className="text-xs text-muted-foreground">Computing positions…</p>
          ) : null}

          {!list.error && list.payload && targets.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground">
              {emptyMessage}
            </p>
          ) : null}

          {!list.error && targets.length ? (
            <ul className="space-y-1.5" aria-busy={list.loading}>
              {targets.map((target) => (
                <TargetRow
                  key={target.id}
                  target={target}
                  selected={selected?.id === target.id}
                  favorite={isFavorite(favorites, target.id)}
                  onSelect={setSelected}
                  onToggleFavorite={handleToggleFavorite}
                  onCopy={handleCopyRow}
                  extra={
                    target.recommend ? (
                      <span>{`best ${formatAltitudeBadge(target.recommend.best_alt_deg)} at ${formatLocalTime(target.recommend.best_utc)}`}</span>
                    ) : null
                  }
                />
              ))}
            </ul>
          ) : null}
        </section>

        <section aria-label="Sky chart" className="space-y-3">
          {!selected ? (
            <div className="flex h-full min-h-[18rem] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-card/40 p-6 text-center">
              <Telescope className="h-6 w-6 text-primary" aria-hidden="true" />
              <p className="text-sm font-semibold text-foreground">Select a target to open its sky chart</p>
              <p className="max-w-sm text-xs text-muted-foreground">
                The chart is centred on the target in your local horizon frame, with its field of view, nearby stars, constellations and a compass.
              </p>
            </div>
          ) : null}
          {selected && chart.error ? (
            <div role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
              <div className="flex items-center gap-2 font-semibold">
                <AlertTriangle className="h-4 w-4" />
                Sky chart unavailable
              </div>
              <p className="mt-1 text-xs">{chart.error}</p>
              <button
                onClick={() => setChartReload((count) => count + 1)}
                type="button"
                className="mt-3 inline-flex items-center gap-2 rounded-lg border border-border bg-secondary px-3 py-1.5 text-xs font-semibold text-foreground"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Retry chart
              </button>
            </div>
          ) : null}
          {selected && chart.loading && !chart.payload ? (
            <p role="status" className="text-xs text-muted-foreground">Drawing the sky chart…</p>
          ) : null}
          {selected && chart.payload && !chart.error ? (
            <SkyChart
              chart={chart.payload}
              fovDeg={fovDeg}
              onFovChange={setFovDeg}
              onCopy={copyCoordinates}
            />
          ) : null}
        </section>
      </div>
    </div>
  );
}
