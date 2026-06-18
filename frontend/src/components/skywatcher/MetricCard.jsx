import React from "react";

const ACCENT = {
  primary: "hsl(190 100% 50%)",
  ready: "hsl(142 70% 50%)",
  warn: "hsl(38 100% 54%)",
  blocked: "hsl(4 90% 60%)",
  synthetic: "hsl(262 52% 64%)",
  info: "hsl(218 100% 60%)",
};

export default function MetricCard({ label, value, sub, icon: Icon, accent = "primary", className = "" }) {
  const color = ACCENT[accent] || ACCENT.primary;
  return (
    <div className={`relative overflow-hidden rounded-xl border border-border bg-card p-4 ${className}`}>
      <div className="absolute left-0 top-0 h-full w-1" style={{ background: color }} />
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground truncate">
            {label}
          </p>
          <p className="mt-1.5 text-2xl font-bold font-display tabular-nums" style={{ color }}>
            {value}
          </p>
          {sub && <p className="mt-0.5 text-[11px] text-muted-foreground">{sub}</p>}
        </div>
        {Icon && (
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
            style={{ background: `${color}1f` }}
          >
            <Icon className="h-4 w-4" style={{ color }} />
          </div>
        )}
      </div>
    </div>
  );
}