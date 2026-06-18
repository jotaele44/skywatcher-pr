import React from "react";
import { CircleDot, AlertTriangle, CheckCircle2, XCircle } from "lucide-react";

const ACTIONS = [
  { key: "triaged", label: "Triage", icon: CircleDot, tone: "info" },
  { key: "needs_review", label: "Needs Review", icon: AlertTriangle, tone: "warn" },
  { key: "verified", label: "Verify", icon: CheckCircle2, tone: "ready" },
  { key: "rejected", label: "Reject", icon: XCircle, tone: "blocked" },
];

const TONE = {
  info: "hover:border-[hsl(218_100%_56%/0.5)] hover:text-[hsl(200_100%_72%)]",
  warn: "hover:border-[hsl(38_100%_50%/0.5)] hover:text-[hsl(38_100%_62%)]",
  ready: "hover:border-[hsl(142_70%_45%/0.5)] hover:text-[hsl(142_70%_60%)]",
  blocked: "hover:border-[hsl(4_90%_58%/0.5)] hover:text-[hsl(4_90%_66%)]",
};
const ACTIVE = {
  info: "border-[hsl(218_100%_56%/0.6)] bg-[hsl(218_100%_56%/0.12)] text-[hsl(200_100%_72%)]",
  warn: "border-[hsl(38_100%_50%/0.6)] bg-[hsl(38_100%_50%/0.12)] text-[hsl(38_100%_62%)]",
  ready: "border-[hsl(142_70%_45%/0.6)] bg-[hsl(142_70%_45%/0.12)] text-[hsl(142_70%_60%)]",
  blocked: "border-[hsl(4_90%_58%/0.6)] bg-[hsl(4_90%_58%/0.12)] text-[hsl(4_90%_66%)]",
};

export default function ReviewActions({ current, onChange, actions = ACTIONS }) {
  return (
    <div className="flex flex-wrap gap-2">
      {actions.map((a) => {
        const Icon = a.icon;
        const active = current === a.key;
        return (
          <button
            key={a.key}
            onClick={() => onChange(a.key)}
            className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition ${
              active ? ACTIVE[a.tone] : `border-border bg-secondary text-muted-foreground ${TONE[a.tone]}`
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
            {a.label}
          </button>
        );
      })}
    </div>
  );
}

export const MANUAL_REVIEW_ACTIONS = [
  { key: "in_review", label: "Start Review", icon: CircleDot, tone: "info" },
  { key: "resolved", label: "Resolve", icon: CheckCircle2, tone: "ready" },
  { key: "rejected", label: "Reject", icon: XCircle, tone: "blocked" },
];