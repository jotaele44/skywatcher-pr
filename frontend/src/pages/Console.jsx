import React, { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import { Crosshair, Layers3, LocateFixed, Map as MapIcon, RotateCcw, ShieldCheck } from "lucide-react";
import PageHeader from "@/components/skywatcher/PageHeader";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import Panel from "@/components/skywatcher/Panel";
import PuertoRicoMapShell from "@/components/skywatcher/PuertoRicoMapShell";
import MapRuntime from "@/components/skywatcher/MapRuntime";
import { federation } from "@/api/federationClient";
import { useSkywatcher } from "@/lib/SkywatcherData";
import { capabilityReason, capabilityTone, indexCapabilities, isCapabilityEnabled } from "@/console/capabilityGate";
import { getBasemap, listBasemaps, LOCAL_BLANK_STYLE_ID } from "@/console/basemapRegistry";
import { LAYER_REGISTRY } from "@/console/layerRegistry";
import { EMPTY_SELECTION, selectionReducer } from "@/console/selectionState";
import { DEFAULT_VIEWPORT, loadViewport, saveViewport } from "@/console/viewportState";

const toneClass = {
  success: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  warning: "border-amber-400/30 bg-amber-400/10 text-amber-300",
  muted: "border-border bg-secondary/50 text-muted-foreground",
};

export default function Console() {
  const data = useSkywatcher();
  const [capabilities, setCapabilities] = useState(null);
  const [capabilityError, setCapabilityError] = useState(null);
  const [runtimeError, setRuntimeError] = useState(null);
  const [basemapId, setBasemapId] = useState(LOCAL_BLANK_STYLE_ID);
  const [viewport, setViewport] = useState(() => loadViewport());
  const [selection, dispatchSelection] = useReducer(selectionReducer, EMPTY_SELECTION);
  const [layerVisibility, setLayerVisibility] = useState(() => Object.fromEntries(LAYER_REGISTRY.map((layer) => [layer.id, layer.defaultVisible])));

  useEffect(() => {
    const controller = new AbortController();
    federation.request("/console/capabilities", { signal: controller.signal })
      .then(setCapabilities)
      .catch((error) => {
        if (error?.name !== "AbortError") setCapabilityError(error);
      });
    return () => controller.abort();
  }, []);

  const capabilityIndex = useMemo(() => indexCapabilities(capabilities), [capabilities]);
  const mapEnabled = isCapabilityEnabled(capabilityIndex, "map_navigation");
  const geolocationEnabled = isCapabilityEnabled(capabilityIndex, "geolocation")
    && typeof navigator !== "undefined"
    && Boolean(navigator.geolocation);

  const onViewportChange = useCallback((next) => {
    setViewport(next);
    saveViewport(next);
  }, []);
  const onSelectionChange = useCallback((action) => dispatchSelection(action), []);
  const onRuntimeError = useCallback((error) => setRuntimeError(error), []);

  const resetViewport = () => {
    const next = { ...DEFAULT_VIEWPORT, center: [...DEFAULT_VIEWPORT.center] };
    setViewport(next);
    saveViewport(next);
    setRuntimeError(null);
  };

  const basemaps = listBasemaps();
  const basemap = getBasemap(basemapId);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Interactive Airspace Console"
        subtitle="Capability-gated MapLibre runtime with an offline diagnostic baseline"
        icon={MapIcon}
        actions={(
          <div className="flex items-center gap-2">
            <span className={`rounded-full border px-2.5 py-1 font-mono text-[10px] ${mapEnabled ? toneClass.success : toneClass.muted}`}>
              {mapEnabled ? "MAP RUNTIME AVAILABLE" : "MAP RUNTIME GATED"}
            </span>
          </div>
        )}
      />
      <DiagnosticNoticeBanner />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_310px]">
        <Panel
          title="Puerto Rico Map Runtime"
          icon={MapIcon}
          bodyClassName="space-y-3"
          action={(
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={basemapId}
                onChange={(event) => setBasemapId(event.target.value)}
                className="h-8 rounded-md border border-border bg-secondary px-2 text-xs text-foreground"
                aria-label="Basemap"
              >
                {basemaps.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
              <button onClick={resetViewport} className="flex h-8 items-center gap-1.5 rounded-md border border-border bg-secondary px-2 text-xs text-foreground hover:bg-secondary/70">
                <RotateCcw className="h-3.5 w-3.5" /> Reset
              </button>
            </div>
          )}
        >
          {mapEnabled && !runtimeError ? (
            <MapRuntime
              capabilityIndex={capabilityIndex}
              basemapId={basemapId}
              viewport={viewport}
              selection={selection}
              layerVisibility={layerVisibility}
              onViewportChange={onViewportChange}
              onSelectionChange={onSelectionChange}
              onRuntimeError={onRuntimeError}
            />
          ) : (
            <div className="space-y-3">
              <div className="rounded-lg border border-amber-400/30 bg-amber-400/8 px-3 py-2 text-xs text-amber-200">
                {runtimeError?.message || capabilityError?.message || capabilityReason(capabilityIndex, "map_navigation")}
              </div>
              <PuertoRicoMapShell routes={data.routes} airports={data.airports} observations={[]} assets={data.assets} height={480} title="SVG diagnostic fallback" />
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-[hsl(220_34%_6%)] px-3 py-2 text-[10px] text-muted-foreground">
            <span>{basemap.attribution}</span>
            <span className="font-mono">network_required={String(basemap.networkRequired)} · provider_keys={String(basemap.providerKeysRequired)}</span>
          </div>
        </Panel>

        <div className="space-y-4">
          <Panel title="Viewport State" icon={Crosshair}>
            <dl className="space-y-2 font-mono text-xs">
              <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Longitude</dt><dd>{viewport.center[0].toFixed(5)}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Latitude</dt><dd>{viewport.center[1].toFixed(5)}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Zoom</dt><dd>{viewport.zoom.toFixed(2)}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Bearing</dt><dd>{viewport.bearing.toFixed(1)}°</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Pitch</dt><dd>{viewport.pitch.toFixed(1)}°</dd></div>
            </dl>
          </Panel>

          <Panel title="Selection State" icon={LocateFixed}>
            <div className="space-y-2 text-xs">
              <p className="text-muted-foreground">Click the map to create a local coordinate selection.</p>
              <p className="font-mono text-foreground">
                {selection.coordinate ? `${selection.coordinate[1].toFixed(5)}, ${selection.coordinate[0].toFixed(5)}` : "No selection"}
              </p>
              {selection.coordinate && (
                <button onClick={() => dispatchSelection({ type: "clear" })} className="rounded-md border border-border bg-secondary px-2 py-1 text-[10px] text-foreground">Clear selection</button>
              )}
            </div>
          </Panel>

          <Panel title="Layer Registry" icon={Layers3}>
            <div className="space-y-2">
              {LAYER_REGISTRY.map((layer) => {
                const enabled = isCapabilityEnabled(capabilityIndex, layer.capabilityId);
                return (
                  <label key={layer.id} className="flex items-center justify-between gap-3 rounded-md border border-border bg-secondary/30 px-2.5 py-2 text-xs">
                    <span>
                      <span className="block text-foreground">{layer.label}</span>
                      {layer.capabilityId && <span className="font-mono text-[9px] text-muted-foreground">{layer.capabilityId}</span>}
                    </span>
                    <input
                      type="checkbox"
                      checked={Boolean(layerVisibility[layer.id])}
                      disabled={!enabled}
                      onChange={(event) => setLayerVisibility((current) => ({ ...current, [layer.id]: event.target.checked }))}
                      aria-label={`Toggle ${layer.label}`}
                    />
                  </label>
                );
              })}
            </div>
          </Panel>

          <Panel title="Runtime Controls" icon={ShieldCheck}>
            <div className="space-y-2 text-xs">
              {["map_navigation", "geolocation", "basemap_controls"].map((id) => {
                const entry = capabilityIndex[id];
                const tone = capabilityTone(entry?.status);
                return (
                  <div key={id} className={`rounded-md border px-2.5 py-2 ${toneClass[tone]}`}>
                    <div className="flex justify-between gap-2"><span className="font-mono">{id}</span><span>{entry?.status || "unreported"}</span></div>
                    <p className="mt-1 text-[10px] opacity-80">{entry?.reason || "Awaiting capability report."}</p>
                  </div>
                );
              })}
              <p className="font-mono text-[10px] text-muted-foreground">browser_geolocation={String(geolocationEnabled)}</p>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
