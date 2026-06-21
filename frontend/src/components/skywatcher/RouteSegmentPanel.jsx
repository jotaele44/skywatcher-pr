import React from "react";
import { Route as RouteIcon } from "lucide-react";
import StatusChip from "./StatusChip";
import { REVIEW_STATUS } from "@/lib/skywatcher";

export default function RouteSegmentPanel({ route, onOpen }) {
  if (!route) return null;
  const rs = REVIEW_STATUS[route.review_status] || REVIEW_STATUS.new;
  return (
    <button
      onClick={onOpen}
      className="w-full rounded-lg border border-border bg-card p-3 text-left transition hover:border-primary/40"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <RouteIcon className="h-4 w-4 shrink-0 text-primary" />
          <span className="truncate text-sm font-semibold text-foreground">{route.inferred_route_name}</span>
        </div>
        <StatusChip tone={rs.tone} label={rs.label} />
      </div>
      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[10px] text-muted-foreground">
        <span>start {route.start_lat?.toFixed(3)}, {route.start_lon?.toFixed(3)}</span>
        <span>end {route.end_lat?.toFixed(3)}, {route.end_lon?.toFixed(3)}</span>
        <span>length {route.segment_length_nm} nm</span>
        <span>method {route.extraction_method}</span>
      </div>
    </button>
  );
}