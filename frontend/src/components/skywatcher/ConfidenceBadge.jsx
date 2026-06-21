import React from "react";
import { confidenceTier } from "@/lib/skywatcher";

const TIER = {
  high: { color: "hsl(142 70% 50%)", label: "High" },
  medium: { color: "hsl(38 100% 52%)", label: "Medium" },
  low: { color: "hsl(4 90% 60%)", label: "Low" },
  unknown: { color: "hsl(215 16% 50%)", label: "—" },
};

export default function ConfidenceBadge({ score, showBar = true, size = "sm" }) {
  const tier = confidenceTier(score);
  const cfg = TIER[tier];
  const pct = score == null ? 0 : Math.round(score * 100);
  return (
    <div className="inline-flex items-center gap-2" title={`Confidence score: ${pct}%`}>
      <div className="flex flex-col items-end">
        <span
          className={`font-mono font-semibold ${size === "lg" ? "text-base" : "text-xs"}`}
          style={{ color: cfg.color }}
        >
          {score == null ? "—" : pct + "%"}
        </span>
        <span className="text-[9px] uppercase tracking-wide text-muted-foreground leading-none">
          {cfg.label} conf
        </span>
      </div>
      {showBar && (
        <div className="w-10 h-1.5 rounded-full bg-secondary overflow-hidden">
          <div className="h-full rounded-full" style={{ width: `${pct}%`, background: cfg.color }} />
        </div>
      )}
    </div>
  );
}