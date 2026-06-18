import React from "react";
import { Plane, Clock } from "lucide-react";
import ConfidenceBadge from "./ConfidenceBadge";
import SyntheticDataBadge from "./SyntheticDataBadge";
import SourceProvenanceBadge from "./SourceProvenanceBadge";

export default function AircraftProfileCard({ aircraft, onOpen }) {
  if (!aircraft) return null;
  const lowConf = (aircraft.profile_confidence ?? 1) < 0.5;
  return (
    <button
      onClick={onOpen}
      className="group w-full rounded-xl border border-border bg-card p-4 text-left transition hover:border-primary/40"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/12 ring-1 ring-primary/20">
            <Plane className="h-5 w-5 text-primary" />
          </div>
          <div className="min-w-0">
            <p className="truncate font-mono text-sm font-bold text-foreground">{aircraft.callsign}</p>
            <p className="truncate text-xs text-muted-foreground">{aircraft.aircraft_type}</p>
          </div>
        </div>
        <ConfidenceBadge score={aircraft.profile_confidence} showBar={false} />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <span className="rounded-full border border-border bg-secondary/60 px-2 py-0.5 text-[10px] font-medium text-foreground/80">
          {aircraft.operator_category}
        </span>
        <span className="rounded-full border border-primary/25 bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
          {aircraft.mission_category}
        </span>
        <SyntheticDataBadge synthetic={aircraft.synthetic_flag} />
      </div>

      <div className="mt-3 flex items-center justify-between text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {aircraft.last_seen_at ? new Date(aircraft.last_seen_at).toLocaleDateString() : "—"}
        </span>
        <span className="font-mono">{aircraft.observation_count || 0} obs</span>
      </div>

      {lowConf && (
        <div className="mt-2 rounded border border-[hsl(4_90%_58%/0.25)] bg-[hsl(4_90%_58%/0.06)] px-2 py-1 text-[10px] text-[hsl(4_90%_68%)]">
          Low-confidence profile — candidate association requires review.
        </div>
      )}
      <div className="mt-2">
        <SourceProvenanceBadge source={aircraft.registry_source ? "registry_match" : "synthetic_example"} />
      </div>
    </button>
  );
}