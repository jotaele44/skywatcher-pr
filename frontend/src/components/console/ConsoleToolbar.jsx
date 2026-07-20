import React from 'react';
import { Crosshair, RotateCcw, ShieldCheck } from 'lucide-react';
import { BASEMAP_REGISTRY } from './BasemapRegistry';
import { resolveCapability } from './CapabilityGate';
import { DEFAULT_VIEWPORT, MAP_CAPABILITY_IDS } from './consoleDefaults';
import { GeolocationControl } from './GeolocationControl';
import { useConsoleState } from './ConsoleStateContext';

export function ConsoleToolbar({ onResetViewport, onLocation }) {
  const { state, dispatch } = useConsoleState();
  const runtimeReady = state.runtimeStatus === 'ready';
  const geolocation = resolveCapability({
    capabilities: state.capabilities,
    capabilityId: MAP_CAPABILITY_IDS.geolocation,
    runtimeReady,
  });

  return (
    <header className="flex min-h-12 flex-wrap items-center gap-2 border-b border-border bg-[hsl(220_34%_6%)] px-3 py-2" aria-label="Interactive console toolbar">
      <div className="mr-auto flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-md border border-primary/30 bg-primary/10">
          <Crosshair className="h-4 w-4 text-primary" aria-hidden="true" />
        </div>
        <div>
          <h1 className="text-sm font-semibold text-foreground">Interactive Airspace Console</h1>
          <p className="font-mono text-[10px] text-muted-foreground">DIAGNOSTIC PRODUCER SURFACE · OFFLINE-FIRST</p>
        </div>
      </div>

      <label className="flex items-center gap-2 text-xs text-muted-foreground">
        Basemap
        <select
          value={state.activeBasemapId}
          onChange={(event) => dispatch({ type: 'basemap/set', basemapId: event.target.value })}
          className="h-9 rounded-md border border-border bg-secondary px-2 text-xs text-foreground"
          aria-label="Select basemap"
        >
          {BASEMAP_REGISTRY.map((entry) => (
            <option key={entry.id} value={entry.id}>{entry.label}</option>
          ))}
        </select>
      </label>

      <button
        type="button"
        onClick={() => onResetViewport?.(DEFAULT_VIEWPORT)}
        disabled={!runtimeReady}
        className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-secondary px-3 text-xs font-medium text-foreground hover:bg-secondary/80 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <RotateCcw className="h-4 w-4" aria-hidden="true" />
        Reset view
      </button>

      <GeolocationControl
        disabled={!geolocation.enabled}
        onLocation={onLocation}
        onStatusChange={(status, detail) => dispatch({
          type: 'geolocation/status',
          status,
          location: status === 'ready' ? detail : undefined,
        })}
      />

      <div className="hidden items-center gap-1.5 rounded-md border border-emerald-400/20 bg-emerald-400/5 px-2.5 py-2 text-[10px] font-medium text-emerald-300 lg:flex">
        <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
        External requests blocked
      </div>
    </header>
  );
}
