import React from "react";
import { Building2 } from "lucide-react";
import StatusChip from "./StatusChip";
import ConfidenceBadge from "./ConfidenceBadge";
import SourceProvenanceBadge from "./SourceProvenanceBadge";
import { REVIEW_STATUS } from "@/lib/skywatcher";

const LINK_TYPE_LABEL = {
  proximity: "Proximity link",
  route_overlap: "Route overlap",
  airport_reference: "Airport reference",
  mission_context: "Mission context",
  manual_association: "Candidate association",
};

export default function InfrastructureLinkPanel({ link, assetName, onOpen }) {
  if (!link) return null;
  const rs = REVIEW_STATUS[link.review_status] || REVIEW_STATUS.new;
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-center justify-between gap-2">
        <button onClick={onOpen} className="flex min-w-0 items-center gap-2 text-left">
          <Building2 className="h-4 w-4 shrink-0 text-[hsl(262_60%_72%)]" />
          <span className="truncate text-sm font-semibold text-foreground">
            {assetName || link.asset_id}
          </span>
        </button>
        <StatusChip tone={rs.tone} label={rs.label} />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="rounded border border-border bg-secondary/60 px-2 py-0.5 text-[10px] text-muted-foreground">
          {LINK_TYPE_LABEL[link.link_type] || link.link_type}
        </span>
        <SourceProvenanceBadge source={link.bridge_source} />
        <span className="font-mono text-[10px] text-muted-foreground">{link.distance_nm} nm</span>
        <ConfidenceBadge score={link.confidence_score} showBar={false} />
      </div>
      {link.explanation && (
        <p className="mt-2 text-xs text-muted-foreground leading-snug">{link.explanation}</p>
      )}
    </div>
  );
}