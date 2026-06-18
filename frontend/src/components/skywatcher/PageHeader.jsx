import React from "react";
import { Radar } from "lucide-react";
import { PROGRAM, DISCLAIMER } from "@/lib/skywatcher";

export default function PageHeader({ title, subtitle, icon: Icon, actions }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex items-start gap-3">
          {Icon && (
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/12 ring-1 ring-primary/25">
              <Icon className="h-5 w-5 text-primary" />
            </div>
          )}
          <div>
            <h1 className="text-xl font-bold tracking-tight text-foreground">{title}</h1>
            {subtitle && <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p>}
          </div>
        </div>
        {actions}
      </div>
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card/60 px-3 py-2">
        <Radar className="h-3.5 w-3.5 text-primary shrink-0" />
        <span className="font-mono text-[10px] font-semibold text-primary">{PROGRAM.activeVector}</span>
        <span className="hidden text-border sm:inline">|</span>
        <span className="text-[11px] italic text-muted-foreground">{DISCLAIMER}</span>
      </div>
    </div>
  );
}