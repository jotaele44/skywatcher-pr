import React from "react";
import { ShieldAlert, Radar } from "lucide-react";
import { DISCLAIMER, PROGRAM } from "@/lib/skywatcher";

export default function DiagnosticNoticeBanner({ compact = false }) {
  return (
    <div className="rounded-lg border border-[hsl(38_100%_50%/0.25)] bg-[hsl(38_100%_50%/0.06)] px-4 py-3">
      <div className="flex items-start gap-3">
        <ShieldAlert className="w-5 h-5 text-[hsl(38_100%_60%)] shrink-0 mt-0.5" />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-bold uppercase tracking-wider text-[hsl(38_100%_64%)]">
              Diagnostic Notice
            </span>
            <span className="inline-flex items-center gap-1 rounded border border-[hsl(38_100%_50%/0.3)] bg-[hsl(38_100%_50%/0.1)] px-2 py-0.5 text-[10px] font-mono font-semibold text-[hsl(38_100%_64%)]">
              {PROGRAM.productionStatus}
            </span>
            <span className="inline-flex items-center gap-1 text-[10px] font-mono text-muted-foreground">
              <Radar className="w-3 h-3 text-primary" />
              {PROGRAM.activeVector}
            </span>
          </div>
          {!compact && (
            <p className="mt-1 text-sm text-foreground/80 leading-snug">{DISCLAIMER}</p>
          )}
        </div>
      </div>
    </div>
  );
}