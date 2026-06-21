import React from "react";
import { ClipboardCheck } from "lucide-react";
import StatusChip from "./StatusChip";
import SyntheticDataBadge from "./SyntheticDataBadge";
import { REVIEW_STATUS } from "@/lib/skywatcher";

const SEV = { low: "muted", medium: "warn", high: "blocked" };
const SEV_DOT = { low: "hsl(215 16% 58%)", medium: "hsl(38 100% 54%)", high: "hsl(4 90% 60%)" };

export default function ManualReviewPanel({ item, onOpen }) {
  if (!item) return null;
  const rs = REVIEW_STATUS[item.review_status] || REVIEW_STATUS.open;
  return (
    <button
      onClick={onOpen}
      className="w-full rounded-lg border border-border bg-card p-3 text-left transition hover:border-primary/40"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: SEV_DOT[item.severity] }} />
          <span className="truncate text-sm font-semibold text-foreground">{item.reason}</span>
        </div>
        <StatusChip tone={rs.tone} label={rs.label} />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
        <span className="rounded border border-border bg-secondary/60 px-2 py-0.5">{item.item_type}</span>
        <span className="font-mono">{item.item_id}</span>
        <StatusChip tone={SEV[item.severity]} label={`${item.severity}`} />
        <SyntheticDataBadge synthetic={item.synthetic_flag} />
      </div>
      {item.recommended_action && (
        <p className="mt-2 flex items-start gap-1.5 text-[11px] text-muted-foreground">
          <ClipboardCheck className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
          {item.recommended_action}
        </p>
      )}
    </button>
  );
}