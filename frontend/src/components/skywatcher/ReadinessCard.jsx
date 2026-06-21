import React from "react";
import { CheckCircle2, XCircle, MinusCircle, Clock } from "lucide-react";

const STATE = {
  ready: { icon: CheckCircle2, color: "hsl(142 70% 52%)", label: "Ready" },
  blocked: { icon: XCircle, color: "hsl(4 90% 62%)", label: "Blocked" },
  deferred: { icon: MinusCircle, color: "hsl(215 16% 58%)", label: "Deferred" },
  pending: { icon: Clock, color: "hsl(38 100% 56%)", label: "Pending" },
};

export default function ReadinessCard({ title, description, state = "pending", value }) {
  const cfg = STATE[state] || STATE.pending;
  const Icon = cfg.icon;
  return (
    <div className="flex items-start gap-3 rounded-xl border border-border bg-card p-4">
      <Icon className="mt-0.5 h-5 w-5 shrink-0" style={{ color: cfg.color }} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-foreground">{title}</p>
          <span
            className="rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide"
            style={{ color: cfg.color, borderColor: `${cfg.color}55`, background: `${cfg.color}14` }}
          >
            {value || cfg.label}
          </span>
        </div>
        {description && <p className="mt-1 text-xs text-muted-foreground leading-snug">{description}</p>}
      </div>
    </div>
  );
}