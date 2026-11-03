import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { liveClient } from "@/api/liveClient";
import { LiveMapEngine } from "@/live/liveMapEngine";
import { findOverlay } from "@/live/sourceCatalog";
import {
  UNIT_SYSTEMS, aircraftFeatureCollection, appendTrailPoint, callsignOf, distanceNm, formatAltitude,
  mergeSnapshot, normalizeAircraft, trailSegments, visibleAircraft,
} from "@/live/aircraftModel";
import { rangeRingCollection, requestBox } from "@/live/geo";
import { browserTimeZone, loadSettings, saveSettings, DEFAULT_SETTINGS } from "@/live/liveSettings";
import {
  DEFAULT_SPEED, clampReplayTime, composeReplayTime, frameIndexAt, frameToAircraft, utcParts,
} from "@/live/replayModel";
import { normalizeViewport } from "@/console/viewportState";
import { SideButtons, TopButtons } from "@/components/live/MapButtons";
import LayerMenu from "@/components/live/LayerMenu";
import ReplayBar from "@/components/live/ReplayBar";
import SettingsPanel from "@/components/live/SettingsPanel";
import AircraftSidebar from "@/components/live/AircraftSidebar";

const VIEWPORT_KEY = "skywatcher.live.viewport.v1";
const REPLAY_WINDOW_S = 300;
const EMPTY_FC = { type: "FeatureCollection", features: [] };
const STATIC_FIELDS = ["t", "r", "category", "dbFlags", "desc", "ownOp"];

function loadLiveViewport(home) {
  try {
    const raw = globalThis.localStorage?.getItem(VIEWPORT_KEY);
    if (raw) return normalizeViewport(JSON.parse(raw));
  } catch {
    // fall through to home
  }
  return normalizeViewport({ center: home.center, zoom: home.zoom });
}

function validTimeZone(zone) {
  if (!zone) return null;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone });
    return zone;
  } catch {
    return null;
  }
}

function inBounds(ac, bounds) {
  if (!bounds) return true;
  const [west, south, east, north] = bounds;
  return ac.lat >= south && ac.lat <= north && (west <= east ? ac.lon >= west && ac.lon <= east : ac.lon >= west || ac.lon <= east);
}

export default function LiveAirspace() {
  const rootRef = useRef(null);
  const mapContainerRef = useRef(null);
  const engineRef = useRef(null);
  const storeRef = useRef(new Map());
  const trailsRef = useRef(new Map());
  const tracesRef = useRef(new Map());
  const knownRef = useRef(new Map());
  const viewRef = useRef(null);
  const renderRef = useRef(() => {});
  const selectRef = useRef(() => {});
  const selectedRef = useRef(new Set());
  const replayRef = useRef({ frames: [], fields: [], index: 0, timer: null, controller: null, prev: new Map() });
  const replayStateRef = useRef(null);
  const togglesRef = useRef(null);
  const viewDebounceRef = useRef(null);
  const jumpDebounceRef = useRef(null);

  const [settings, setSettings] = useState(() => loadSettings());
  const updateSettings = useCallback((patch) => setSettings((current) => saveSettings({ ...current, ...patch })), []);
  const timeZone = validTimeZone(settings.timeZone) || browserTimeZone();

  const [toggles, setToggles] = useState({ U: false, T: false, M: false, P: false, I: false, F: false });
  const [selected, setSelected] = useState(() => new Set());
  const [panel, setPanel] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [mapError, setMapError] = useState(null);
  const [feed, setFeed] = useState({ status: "loading" });
  const [aircraftList, setAircraftList] = useState([]);
  const [details, setDetails] = useState({});
  const [liveStatus, setLiveStatus] = useState(null);
  const [sourceErrors, setSourceErrors] = useState({});
  const [youPosition, setYouPosition] = useState(null);
  const [geoError, setGeoError] = useState(null);
  const [viewVersion, setViewVersion] = useState(0);
  const [replay, setReplay] = useState({ open: false, playing: true, speed: DEFAULT_SPEED, ts: Date.now(), loading: false, error: null, clamped: false });

  togglesRef.current = toggles;
  replayStateRef.current = replay;

  // ── rendering ──────────────────────────────────────────────────────────────
  const renderMap = useCallback(() => {
    const engine = engineRef.current;
    const view = viewRef.current;
    const reference = youPosition || view?.center || settings.home.center;
    const all = [...storeRef.current.values()].map((ac) => ({
      ...ac,
      distance_nm: ac.lat === null ? null : distanceNm(reference[1], reference[0], ac.lat, ac.lon),
    }));
    const visible = visibleAircraft(all, {
      isolate: toggles.I,
      selected,
      // Live military mode is filtered upstream (/v2/mil); replay uses what
      // the live feed taught us about each airframe.
      military: toggles.U && replay.open,
    });
    engine?.setAircraft(aircraftFeatureCollection(visible, {
      labels: settings.labels, extended: settings.extendedLabels, selected, units: settings.units,
    }));

    const trailHexes = toggles.T ? visible.map((ac) => ac.hex) : [...selected];
    const trailFeatures = [];
    const labelFeatures = [];
    for (const hex of trailHexes) {
      const trace = tracesRef.current.get(hex) || [];
      const live = trailsRef.current.get(hex) || [];
      const lastTrace = trace.length ? trace[trace.length - 1].t : 0;
      const points = [...trace, ...live.filter((p) => p.t > lastTrace)];
      trailFeatures.push(...trailSegments(points));
      if (settings.trackLabels && selected.has(hex) && points.length) {
        const every = Math.max(1, Math.floor(points.length / 40));
        points.forEach((point, index) => {
          if (index % every) return;
          const time = point.t ? new Date(point.t).toISOString().slice(11, 19) : "";
          labelFeatures.push({
            type: "Feature",
            properties: { label: `${formatAltitude(point.alt, settings.units)}\n${time}` },
            geometry: { type: "Point", coordinates: [point.lon, point.lat] },
          });
        });
      }
    }
    engine?.setTrails({ type: "FeatureCollection", features: trailFeatures });
    engine?.setTrackLabels(labelFeatures.length ? { type: "FeatureCollection", features: labelFeatures } : EMPTY_FC);
    setAircraftList(visible.filter((ac) => selected.has(ac.hex) || inBounds(ac, view?.bounds)));

    if (toggles.F && engine) {
      const target = visible.find((ac) => selected.has(ac.hex));
      if (target) engine.panTo([target.lon, target.lat]);
    }
  }, [toggles, selected, replay.open, settings.labels, settings.extendedLabels, settings.units, settings.trackLabels, settings.home, youPosition]);

  renderRef.current = renderMap;
  useEffect(() => { renderMap(); }, [renderMap]);

  const remember = useCallback((rawList) => {
    for (const raw of rawList) {
      if (!raw?.hex) continue;
      const known = knownRef.current.get(raw.hex) || {};
      const next = { ...known };
      for (const field of STATIC_FIELDS) if (raw[field] !== undefined && raw[field] !== null) next[field] = raw[field];
      knownRef.current.set(raw.hex, next);
    }
  }, []);

  const ingest = useCallback((rawList, nowMs, { staleAfterMs = 60_000 } = {}) => {
    const incoming = rawList.map((raw) => normalizeAircraft({ ...knownRef.current.get(raw.hex), ...raw }, nowMs));
    storeRef.current = mergeSnapshot(storeRef.current, incoming, {
      nowMs, persistence: togglesRef.current.P, staleAfterMs,
    });
    for (const ac of incoming) appendTrailPoint(trailsRef.current, ac, ac.updated_ms);
  }, []);

  const resetAircraft = useCallback(() => {
    storeRef.current = new Map();
    trailsRef.current = new Map();
    replayRef.current.prev = new Map();
  }, []);

  // ── map engine lifecycle ───────────────────────────────────────────────────
  useEffect(() => {
    const container = mapContainerRef.current;
    if (!container) return undefined;
    const initial = loadSettings();
    let engine;
    try {
      engine = new LiveMapEngine({
        maplibregl,
        container,
        viewport: loadLiveViewport(initial.home),
        baseLayerId: initial.baseLayer,
        customTemplate: initial.customTemplate,
        apiBase: liveClient.apiBase(),
        onSelect: (hex, options) => selectRef.current(hex, options),
        onViewChange: (view) => {
          viewRef.current = view;
          try {
            globalThis.localStorage?.setItem(VIEWPORT_KEY, JSON.stringify(normalizeViewport({ center: view.center, zoom: view.zoom })));
          } catch {
            // storage unavailable; viewport simply is not remembered
          }
          renderRef.current();
          clearTimeout(viewDebounceRef.current);
          viewDebounceRef.current = setTimeout(() => setViewVersion((v) => v + 1), 400);
        },
        onSourceError: (sourceId, message) => {
          if (!sourceId) return;
          setSourceErrors((current) => (current[sourceId] === message ? current : { ...current, [sourceId]: message }));
        },
      });
    } catch (error) {
      // No WebGL: keep the feed and aircraft list working around the home view.
      const [lon, lat] = initial.home.center;
      viewRef.current = { center: [lon, lat], zoom: initial.home.zoom, bounds: [lon - 2, lat - 1.5, lon + 2, lat + 1.5] };
      setMapError(error);
      setViewVersion((v) => v + 1);
      return undefined;
    }
    engineRef.current = engine;
    viewRef.current = engine.view();
    setViewVersion((v) => v + 1);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => engine.resize());
    observer?.observe(container);
    return () => {
      observer?.disconnect();
      clearTimeout(viewDebounceRef.current);
      engine.destroy();
      engineRef.current = null;
    };
  }, []);

  // settings → engine
  const firstBase = useRef(true);
  useEffect(() => {
    if (firstBase.current) { firstBase.current = false; return; }
    setSourceErrors((current) => { const { "sw-base": _drop, ...rest } = current; return rest; });
    engineRef.current?.setBaseLayer(settings.baseLayer, settings.customTemplate);
  }, [settings.baseLayer, settings.customTemplate]);

  useEffect(() => {
    const engine = engineRef.current;
    if (!engine) return;
    // Key-gated overlays (openAIP) stay off until the backend reports a key.
    const openaipReady = Boolean(liveStatus?.openaip?.configured);
    const wanted = new Set(settings.overlays.filter((id) => findOverlay(id)?.requires !== "openaip_key" || openaipReady));
    for (const id of [...engine.overlays]) if (!wanted.has(id)) engine.setOverlay(id, false);
    for (const id of wanted) if (!engine.overlays.has(id)) engine.setOverlay(id, true);
  }, [settings.overlays, mapError, liveStatus]);

  useEffect(() => { engineRef.current?.setFeatureVisibility(settings.features); }, [settings.features, mapError]);
  useEffect(() => { engineRef.current?.setDim(settings.mapDim, settings.mapDimAmount); }, [settings.mapDim, settings.mapDimAmount, mapError]);
  useEffect(() => { engineRef.current?.setScaleUnit(UNIT_SYSTEMS[settings.units].scale); }, [settings.units, mapError]);
  useEffect(() => {
    const center = youPosition || settings.home.center;
    engineRef.current?.setRangeRings(rangeRingCollection(center, settings.rangeRings, settings.units));
  }, [youPosition, settings.home, settings.rangeRings, settings.units, mapError]);
  useEffect(() => { engineRef.current?.setYourPosition(youPosition); }, [youPosition, mapError]);

  // backend feed configuration (openAIP key present?)
  useEffect(() => {
    const controller = new AbortController();
    liveClient.status({ signal: controller.signal }).then(setLiveStatus).catch(() => setLiveStatus(null));
    return () => controller.abort();
  }, []);

  // "Your position": browser geolocation, only while the layer is enabled.
  useEffect(() => {
    if (!settings.features.yourPosition || typeof navigator === "undefined" || !navigator.geolocation) return undefined;
    const id = navigator.geolocation.watchPosition(
      (position) => { setGeoError(null); setYouPosition([position.coords.longitude, position.coords.latitude]); },
      (error) => setGeoError(error.message || "Location unavailable"),
      { enableHighAccuracy: false, maximumAge: 60_000, timeout: 20_000 },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [settings.features.yourPosition]);

  // ── live polling ───────────────────────────────────────────────────────────
  useEffect(() => {
    if (replay.open) return undefined;
    let cancelled = false;
    let timer = null;
    let controller = null;
    const tick = async () => {
      const view = viewRef.current;
      if (!view?.bounds || (typeof document !== "undefined" && document.hidden)) {
        timer = setTimeout(tick, 1000);
        return;
      }
      controller = new AbortController();
      try {
        const selectedHexes = [...selectedRef.current];
        const response = await liveClient.aircraft(requestBox(view.bounds), {
          military: togglesRef.current.U, hexes: selectedHexes, signal: controller.signal,
        });
        if (cancelled) return;
        if (response.status === "available") {
          remember(response.aircraft);
          ingest(response.aircraft, Date.now());
        }
        setFeed({
          status: response.status, reason: response.reason, fetchedAt: response.fetched_at_utc,
          count: response.count, coverage: response.coverage,
        });
        renderRef.current();
      } catch (error) {
        if (error?.name === "AbortError" || cancelled) return;
        setFeed({ status: "error", reason: error.message || "Live feed request failed" });
      }
      if (!cancelled) timer = setTimeout(tick, settings.refreshS * 1000);
    };
    tick();
    return () => {
      cancelled = true;
      controller?.abort();
      clearTimeout(timer);
    };
  }, [replay.open, toggles.U, settings.refreshS, viewVersion, ingest, remember]);

  // ── selection ──────────────────────────────────────────────────────────────
  selectedRef.current = selected;
  const select = useCallback((hex, { additive = false } = {}) => {
    setSelected((current) => {
      if (!hex) return togglesRef.current.M || togglesRef.current.I ? current : new Set();
      const multi = togglesRef.current.M || additive;
      if (multi) {
        const next = new Set(current);
        if (next.has(hex)) next.delete(hex);
        else next.add(hex);
        return next;
      }
      return current.size === 1 && current.has(hex) ? new Set() : new Set([hex]);
    });
  }, []);
  selectRef.current = select;

  // Load the full trace and the route for each newly selected aircraft.
  useEffect(() => {
    const controller = new AbortController();
    const replayDay = replay.open ? utcParts(replay.ts).date : undefined;
    for (const hex of selected) {
      if (details[hex]?.traceFor === (replayDay || "live")) continue;
      setDetails((current) => ({ ...current, [hex]: { ...current[hex], traceFor: replayDay || "live", traceStatus: "loading…", routeStatus: "loading" } }));
      liveClient.trace(hex, { date: replayDay, signal: controller.signal })
        .then((response) => {
          remember([{ hex, t: response.type, r: response.registration, desc: response.description, ownOp: response.operator, dbFlags: response.db_flags }]);
          const points = (response.points || []).map((p) => ({ lat: p.lat, lon: p.lon, alt: p.alt_baro, t: p.t * 1000, new_leg: p.new_leg, stale: p.stale }));
          tracesRef.current.set(hex, points);
          setDetails((current) => ({ ...current, [hex]: { ...current[hex], traceStatus: response.status === "available" ? `${points.length} points` : response.reason || response.status } }));
          renderRef.current();
        })
        .catch((error) => {
          if (error?.name !== "AbortError") setDetails((current) => ({ ...current, [hex]: { ...current[hex], traceStatus: error.message } }));
        });
      const ac = storeRef.current.get(hex);
      if (ac?.flight && ac.lat !== null) {
        liveClient.routes([{ callsign: ac.flight, lat: ac.lat, lng: ac.lon }], { signal: controller.signal })
          .then((response) => {
            const match = (response.routes || []).find((r) => String(r.callsign).toUpperCase() === ac.flight.toUpperCase());
            const route = match?.route ? `${match.route}${match.cities ? ` (${match.cities})` : ""}` : null;
            setDetails((current) => ({ ...current, [hex]: { ...current[hex], route: route || (response.status === "available" ? "unknown" : response.reason), routeStatus: "done" } }));
          })
          .catch(() => setDetails((current) => ({ ...current, [hex]: { ...current[hex], routeStatus: "done" } })));
      } else {
        setDetails((current) => ({ ...current, [hex]: { ...current[hex], routeStatus: "done" } }));
      }
    }
    return () => controller.abort();
    // details is intentionally read, not watched: it is what this effect writes.
  }, [selected, replay.open]);

  // ── replay ─────────────────────────────────────────────────────────────────
  const showFrame = useCallback((index) => {
    const state = replayRef.current;
    const frame = state.frames[index];
    if (!frame) return;
    const rows = frameToAircraft(frame, state.fields, state.prev);
    for (const row of rows) state.prev.set(row.hex, { lat: row.lat, lon: row.lon, track: row.track });
    ingest(rows, frame.t * 1000, { staleAfterMs: 90_000 });
    renderRef.current();
  }, [ingest]);

  const stopReplayTimer = () => {
    clearTimeout(replayRef.current.timer);
    replayRef.current.timer = null;
  };

  const scheduleStep = useCallback(() => {
    const state = replayRef.current;
    stopReplayTimer();
    const current = state.frames[state.index];
    if (!current || !replayStateRef.current.playing || !replayStateRef.current.open) return;
    state.timer = setTimeout(() => {
      const next = state.index + 1;
      if (next >= state.frames.length) {
        const last = state.frames[state.frames.length - 1];
        loadReplayRef.current((last.t + (last.interval_s || 10)) * 1000, { reset: false });
        return;
      }
      state.index = next;
      showFrame(next);
      setReplay((r) => ({ ...r, ts: state.frames[next].t * 1000 }));
      scheduleStep();
    }, ((current.interval_s || 10) * 1000) / Math.max(1, replayStateRef.current.speed));
  }, [showFrame]);

  const loadReplayRef = useRef(() => {});
  const loadReplay = useCallback(async (tsMs, { reset = true } = {}) => {
    const view = viewRef.current;
    if (!view?.bounds) return;
    const { ts, clamped } = clampReplayTime(tsMs);
    const state = replayRef.current;
    stopReplayTimer();
    state.controller?.abort();
    state.controller = new AbortController();
    setReplay((r) => ({ ...r, ts, clamped, loading: true, error: null }));
    try {
      const response = await liveClient.replay(new Date(ts).toISOString(), requestBox(view.bounds), {
        windowS: REPLAY_WINDOW_S, signal: state.controller.signal,
      });
      if (!replayStateRef.current.open) return;
      if (response.status !== "available" || !response.frames?.length) {
        setReplay((r) => ({ ...r, loading: false, error: `${response.reason || "No data"} — no data for this timestamp` }));
        return;
      }
      if (reset) resetAircraft();
      state.frames = response.frames;
      state.fields = response.fields;
      state.index = Math.max(0, frameIndexAt(response.frames, ts));
      showFrame(state.index);
      setReplay((r) => ({ ...r, loading: false, clamped: response.clamped_to_latest, ts: response.frames[state.index].t * 1000 }));
      scheduleStep();
    } catch (error) {
      if (error?.name === "AbortError") return;
      setReplay((r) => ({ ...r, loading: false, error: error.message || "Replay request failed" }));
    }
  }, [resetAircraft, scheduleStep, showFrame]);
  loadReplayRef.current = loadReplay;

  const openReplay = useCallback(() => {
    setReplay((r) => {
      if (r.open) {
        stopReplayTimer();
        replayRef.current.controller?.abort();
        resetAircraft();
        return { ...r, open: false, loading: false, error: null };
      }
      return { ...r, open: true, playing: true, error: null };
    });
  }, [resetAircraft]);

  // Opening replay starts at the newest available half hour, like adsb.lol.
  const replayOpenedRef = useRef(false);
  useEffect(() => {
    if (replay.open && !replayOpenedRef.current) {
      replayOpenedRef.current = true;
      resetAircraft();
      renderRef.current();
      loadReplay(Date.now());
    } else if (!replay.open && replayOpenedRef.current) {
      replayOpenedRef.current = false;
      setFeed((f) => ({ ...f, status: "loading" }));
    }
  }, [replay.open, loadReplay, resetAircraft]);

  // Panning during replay reloads the current window for the new view.
  const lastReplayView = useRef(viewVersion);
  useEffect(() => {
    if (!replay.open || lastReplayView.current === viewVersion) return;
    lastReplayView.current = viewVersion;
    loadReplay(replayStateRef.current.ts, { reset: false });
  }, [viewVersion, replay.open, loadReplay]);

  useEffect(() => {
    if (replay.open && replay.playing && !replay.loading) scheduleStep();
    else stopReplayTimer();
  }, [replay.playing, replay.speed, replay.open, replay.loading, scheduleStep]);

  useEffect(() => () => { stopReplayTimer(); replayRef.current.controller?.abort(); }, []);

  const jumpTo = (ts) => {
    // Stop playback first so the step timer cannot overwrite the new time.
    stopReplayTimer();
    replayRef.current.controller?.abort();
    setReplay((r) => ({ ...r, ts, loading: true, error: null }));
    clearTimeout(jumpDebounceRef.current);
    jumpDebounceRef.current = setTimeout(() => loadReplay(ts, { reset: true }), 350);
  };
  const replayParts = utcParts(replay.ts);

  // ── buttons ────────────────────────────────────────────────────────────────
  const resetMap = useCallback(() => {
    engineRef.current?.flyTo(settings.home.center, settings.home.zoom);
    setSelected(new Set());
    setToggles((t) => ({ ...t, F: false, I: false }));
  }, [settings.home]);

  const followRandom = useCallback(() => {
    const candidates = aircraftList.filter((ac) => !ac.stale && ac.alt_baro !== "ground");
    const pool = candidates.length ? candidates : aircraftList;
    if (!pool.length) return;
    const pick = pool[Math.floor(Math.random() * pool.length)];
    setSelected(new Set([pick.hex]));
    setToggles((t) => ({ ...t, F: true }));
    engineRef.current?.flyTo([pick.lon, pick.lat]);
  }, [aircraftList]);

  const press = useCallback((id) => {
    switch (id) {
      case "U":
        resetAircraft();
        setToggles((t) => ({ ...t, U: !t.U }));
        break;
      case "H": resetMap(); break;
      case "T": setToggles((t) => ({ ...t, T: !t.T })); break;
      case "L": updateSettings({ labels: !settings.labels }); break;
      case "O": updateSettings({ extendedLabels: !settings.extendedLabels, labels: settings.labels || !settings.extendedLabels }); break;
      case "K": updateSettings({ trackLabels: !settings.trackLabels }); break;
      case "M": setToggles((t) => ({ ...t, M: !t.M })); break;
      case "P": setToggles((t) => ({ ...t, P: !t.P })); break;
      case "I": setToggles((t) => ({ ...t, I: !t.I })); break;
      case "R": followRandom(); break;
      case "F": setToggles((t) => ({ ...t, F: !t.F })); break;
      default: break;
    }
  }, [followRandom, resetAircraft, resetMap, settings.extendedLabels, settings.labels, settings.trackLabels, updateSettings]);

  const activeButtons = {
    U: toggles.U, T: toggles.T, L: settings.labels, O: settings.extendedLabels, K: settings.trackLabels,
    M: toggles.M, P: toggles.P, I: toggles.I, F: toggles.F,
  };

  // fullscreen (Fullscreen API, CSS fallback where it is missing, e.g. iPhone)
  const fullscreenSupported = typeof document !== "undefined" && Boolean(document.fullscreenEnabled);
  const toggleFullscreen = useCallback(() => {
    if (fullscreenSupported) {
      if (document.fullscreenElement) document.exitFullscreen?.();
      else rootRef.current?.requestFullscreen?.().catch(() => setFullscreen((f) => !f));
    } else {
      setFullscreen((f) => !f);
    }
  }, [fullscreenSupported]);
  useEffect(() => {
    if (!fullscreenSupported) return undefined;
    const onChange = () => setFullscreen(document.fullscreenElement === rootRef.current);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, [fullscreenSupported]);
  useEffect(() => { engineRef.current?.resize(); }, [fullscreen, sidebarOpen]);

  // keyboard shortcuts (same letters as the buttons)
  useEffect(() => {
    const onKey = (event) => {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      const tag = event.target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || event.target?.isContentEditable) return;
      const key = event.key.toUpperCase();
      if ("UHTLOKMPIRF".includes(key) && key.length === 1) press(key);
      else if (key === "Y") openReplay();
      else if (key === "B") updateSettings({ mapDim: !settings.mapDim });
      else if (key === "ESCAPE") { setSelected(new Set()); setPanel(null); }
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [press, openReplay, settings.mapDim, updateSettings]);

  const status = useMemo(() => {
    if (mapError) return { tone: "error", text: `Map unavailable: ${mapError.message}` };
    if (replay.open) return { tone: "replay", text: `REPLAY · ${aircraftList.length} aircraft` };
    if (feed.status === "available") {
      const partial = feed.coverage && feed.coverage.complete === false;
      return { tone: partial ? "warn" : "live", text: `LIVE${toggles.U ? " · MIL" : ""} · ${aircraftList.length} aircraft${partial ? " · zoom in for full coverage" : ""}` };
    }
    if (feed.status === "loading") return { tone: "muted", text: "Connecting to adsb.lol…" };
    return { tone: "error", text: `Live feed unavailable: ${feed.reason || feed.status}` };
  }, [mapError, replay.open, feed, aircraftList.length, toggles.U]);

  const toneClass = {
    live: "border-emerald-400/40 text-emerald-200",
    replay: "border-sky-400/40 text-sky-200",
    warn: "border-amber-400/40 text-amber-200",
    muted: "border-white/20 text-slate-300",
    error: "border-red-400/50 text-red-200",
  }[status.tone];

  const selectedHex = [...selected][0];
  const selectedAc = selectedHex ? storeRef.current.get(selectedHex) : null;

  return (
    <div
      ref={rootRef}
      className={`relative flex bg-[#0b1622] ${fullscreen && !fullscreenSupported ? "fixed inset-0 z-50" : "h-full w-full"}`}
      data-testid="live-airspace"
    >
      <div className="flex min-w-0 flex-1 flex-col">
      <div className="relative min-h-0 flex-1">
        {/* maplibre-gl.css forces position:relative on the map container, so it
            fills an absolutely positioned wrapper instead of being positioned itself. */}
        <div className="absolute inset-0">
          <div ref={mapContainerRef} className="h-full w-full" aria-label="Live airspace map" role="region" />
        </div>
        {mapError && (
          <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-slate-200">
            <div className="max-w-md rounded-lg border border-red-400/40 bg-slate-900/90 p-4">
              <p className="font-semibold">The interactive map could not start.</p>
              <p className="mt-1 text-slate-400">{mapError.message}. The map needs WebGL; the aircraft list (sidebar) still updates from the live feed around the home position.</p>
            </div>
          </div>
        )}
        <div className={`pointer-events-none absolute left-2 z-20 max-w-[70%] rounded-md border bg-slate-900/80 px-2 py-1 font-mono text-[10px] uppercase tracking-wide bottom-14 ${toneClass}`} role="status" aria-live="polite">
          {status.text}
          {selectedAc && <span className="block normal-case text-slate-300">{callsignOf(selectedAc)} selected</span>}
        </div>

        <TopButtons
          active={activeButtons}
          onPress={press}
          replayOpen={replay.open}
          onReplay={openReplay}
          layersOpen={panel === "layers"}
          onLayers={() => setPanel((p) => (p === "layers" ? null : "layers"))}
        />
        <SideButtons
          active={activeButtons}
          onPress={press}
          sidebarOpen={sidebarOpen}
          onSidebar={() => setSidebarOpen((open) => !open)}
          fullscreen={fullscreen}
          onFullscreen={toggleFullscreen}
          settingsOpen={panel === "settings"}
          onSettings={() => setPanel((p) => (p === "settings" ? null : "settings"))}
          onZoom={(delta) => engineRef.current?.zoomBy(delta)}
        />

        {panel === "layers" && (
          <LayerMenu
            settings={settings}
            onChange={updateSettings}
            onClose={() => setPanel(null)}
            openaipConfigured={Boolean(liveStatus?.openaip?.configured)}
            sourceErrors={sourceErrors}
            geoError={geoError}
          />
        )}
        {panel === "settings" && (
          <SettingsPanel
            settings={settings}
            timeZone={timeZone}
            onChange={updateSettings}
            onClose={() => setPanel(null)}
            onSetHome={() => {
              const view = viewRef.current;
              if (view) updateSettings({ home: { center: view.center, zoom: view.zoom } });
            }}
            onReset={() => setSettings(saveSettings({ ...DEFAULT_SETTINGS }))}
          />
        )}
      </div>

        {/* Like adsb.lol, the replay bar sits below the map rather than over it. */}
        {replay.open && (
          <ReplayBar
            replay={replay}
            timeZone={timeZone}
            onPlayPause={() => setReplay((r) => ({ ...r, playing: !r.playing }))}
            onDate={(dateText) => jumpTo(composeReplayTime(dateText, replayParts.hours, replayParts.minutes))}
            onHour={(hours) => jumpTo(composeReplayTime(replayParts.date, hours, replayParts.minutes))}
            onMinute={(minutes) => jumpTo(composeReplayTime(replayParts.date, replayParts.hours, minutes))}
            onSpeed={(speed) => setReplay((r) => ({ ...r, speed }))}
            onClose={openReplay}
          />
        )}
      </div>

      {sidebarOpen && (
        <div className="absolute inset-0 z-40 md:static md:z-auto md:h-full">
          <button type="button" onClick={() => setSidebarOpen(false)} className="absolute right-2 top-2 z-50 rounded border border-white/20 bg-slate-800 px-2 py-0.5 text-xs text-white md:hidden">Close</button>
          <AircraftSidebar
            aircraft={aircraftList}
            selected={selected}
            details={details}
            units={settings.units}
            onSelect={select}
            onClear={() => setSelected(new Set())}
            following={toggles.F}
            onFollow={() => setToggles((t) => ({ ...t, F: !t.F }))}
            isolating={toggles.I}
            onIsolate={() => setToggles((t) => ({ ...t, I: !t.I }))}
            feed={feed}
            mode={replay.open ? "replay" : "live"}
          />
        </div>
      )}
    </div>
  );
}
