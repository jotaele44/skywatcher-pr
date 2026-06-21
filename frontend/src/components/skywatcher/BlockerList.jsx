import React from "react";
import { AlertOctagon, AlertTriangle } from "lucide-react";

export default function BlockerList({ blockers = [], warnings = [], title = "Top Blockers" }) {
  return (
    <div className="space-y-3">
      {title && <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">{title}</h3>}
      <ul className="space-y-2">
        {blockers.map((b, i) => (
          <li key={`b-${i}`} className="flex items-start gap-2 rounded-lg border border-[hsl(4_90%_58%/0.25)] bg-[hsl(4_90%_58%/0.06)] px-3 py-2">
            <AlertOctagon className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(4_90%_64%)]" />
            <span className="text-sm text-foreground/90">{b}</span>
          </li>
        ))}
        {warnings.map((w, i) => (
          <li key={`w-${i}`} className="flex items-start gap-2 rounded-lg border border-[hsl(38_100%_50%/0.25)] bg-[hsl(38_100%_50%/0.06)] px-3 py-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(38_100%_62%)]" />
            <span className="text-sm text-foreground/90">{w}</span>
          </li>
        ))}
        {blockers.length === 0 && warnings.length === 0 && (
          <li className="text-sm text-muted-foreground">No active blockers.</li>
        )}
      </ul>
    </div>
  );
}