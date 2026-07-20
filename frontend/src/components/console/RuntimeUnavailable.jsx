import React from 'react';
import { AlertTriangle, Radar } from 'lucide-react';

export function RuntimeUnavailable({ reason, title = 'Interactive map unavailable' }) {
  return (
    <section
      className="flex h-full min-h-[24rem] items-center justify-center bg-[hsl(220_34%_4%)] p-6"
      role="status"
      aria-live="polite"
      data-testid="console-runtime-unavailable"
    >
      <div className="max-w-lg rounded-xl border border-amber-400/30 bg-amber-400/5 p-6 text-center shadow-2xl">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-amber-300/30 bg-amber-300/10">
          <AlertTriangle className="h-6 w-6 text-amber-300" aria-hidden="true" />
        </div>
        <h1 className="text-lg font-semibold text-foreground">{title}</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">{reason}</p>
        <div className="mt-5 flex items-center justify-center gap-2 text-xs text-muted-foreground">
          <Radar className="h-4 w-4" aria-hidden="true" />
          Existing diagnostic pages and the Puerto Rico SVG shell remain available.
        </div>
      </div>
    </section>
  );
}
