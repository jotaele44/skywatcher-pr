import React from 'react';
import { Database, Layers3, Map, Shield, WifiOff } from 'lucide-react';
import { LAYER_REGISTRY } from './LayerRegistry';
import { useConsoleState } from './ConsoleStateContext';

function StatusRow({ label, value, tone = 'default' }) {
  const toneClass = tone === 'good' ? 'text-emerald-300' : tone === 'warn' ? 'text-amber-300' : 'text-foreground';
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border/60 py-2 last:border-b-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={`text-right font-mono text-[10px] ${toneClass}`}>{value}</span>
    </div>
  );
}

export function ConsoleStatusPanel() {
  const { state, dispatch } = useConsoleState();
  const availableRepositories = state.repositories.filter((item) => item.status === 'available').length;

  return (
    <aside className="flex max-h-48 w-full shrink-0 flex-col overflow-y-auto border-r border-border bg-[hsl(220_34%_5%)] md:max-h-none md:w-64" aria-label="Console status and layers">
      <section className="border-b border-border p-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-foreground/90">
          <Map className="h-4 w-4 text-primary" aria-hidden="true" /> Runtime
        </div>
        <StatusRow label="Map runtime" value={state.runtimeStatus} tone={state.runtimeStatus === 'ready' ? 'good' : 'warn'} />
        <StatusRow label="WebGL" value={state.webglSupported === true ? 'supported' : state.webglSupported === false ? 'unavailable' : 'probing'} tone={state.webglSupported ? 'good' : 'warn'} />
        <StatusRow label="Bootstrap" value={state.bootstrapStatus} tone={state.bootstrapStatus === 'ready' ? 'good' : 'warn'} />
      </section>

      <section className="border-b border-border p-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-foreground/90">
          <Layers3 className="h-4 w-4 text-primary" aria-hidden="true" /> Layers
        </div>
        <div className="space-y-1">
          {LAYER_REGISTRY.map((layer) => (
            <label key={layer.id} className="flex items-center justify-between gap-2 rounded-md px-1 py-1.5 text-xs text-muted-foreground">
              <span>{layer.label}</span>
              <input
                type="checkbox"
                checked={state.visibleLayerIds.includes(layer.id)}
                onChange={() => dispatch({ type: 'layer/toggle', layerId: layer.id })}
                disabled
                title="Data layers are capability-gated for a later phase"
              />
            </label>
          ))}
        </div>
      </section>

      <section className="border-b border-border p-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-foreground/90">
          <Database className="h-4 w-4 text-primary" aria-hidden="true" /> Repositories
        </div>
        <StatusRow label="Reported" value={String(state.repositories.length)} />
        <StatusRow label="Available" value={String(availableRepositories)} />
        <StatusRow label="Capability count" value={String(state.capabilities.length)} />
      </section>

      <section className="mt-auto p-3">
        <div className="rounded-lg border border-cyan-400/20 bg-cyan-400/5 p-3 text-[10px] leading-5 text-muted-foreground">
          <div className="mb-1 flex items-center gap-2 font-semibold uppercase tracking-wider text-cyan-200">
            <Shield className="h-3.5 w-3.5" aria-hidden="true" /> Policy
          </div>
          <p className="flex items-center gap-2"><WifiOff className="h-3.5 w-3.5" aria-hidden="true" /> Blank mode needs no internet provider.</p>
          <p>No FR24 visual assets are loaded or copied.</p>
          <p>Geolocation is manual, transient, and client-only.</p>
        </div>
      </section>
    </aside>
  );
}
