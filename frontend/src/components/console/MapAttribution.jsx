import React from 'react';

export function MapAttribution({ attribution }) {
  return (
    <footer
      className="flex min-h-8 flex-wrap items-center justify-between gap-2 border-t border-border bg-[hsl(220_34%_6%)] px-3 py-1.5 text-[10px] text-muted-foreground"
      data-testid="permanent-map-attribution"
    >
      <span>{attribution}</span>
      <span className="font-mono">OFFLINE BLANK STYLE · NO PROVIDER KEY</span>
    </footer>
  );
}
