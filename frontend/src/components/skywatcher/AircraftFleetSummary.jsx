import React, { useMemo } from "react";
import { Plane, Link2, IdCard, Crosshair } from "lucide-react";

function Stat({ icon: Icon, label, value, accent }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-secondary/30 px-3 py-2.5">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg" style={{ backgroundColor: `${accent}1f`, color: accent }}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <p className="font-mono text-lg font-bold leading-none text-foreground">{value}</p>
        <p className="mt-1 truncate text-[11px] text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}

export default function AircraftFleetSummary({ aircraft = [], linksForAircraftTail }) {
  const stats = useMemo(() => {
    const profileCount = aircraft.length;
    const totalObservations = aircraft.reduce((sum, a) => sum + (a.observation_count || 0), 0);
    const linkSet = new Set();
    let highConfidence = 0;
    for (const a of aircraft) {
      if ((a.profile_confidence || 0) >= 0.75) highConfidence += 1;
      const links = linksForAircraftTail ? linksForAircraftTail(a.tail_number) : [];
      links.forEach((l) => linkSet.add(l.link_id || l.id));
    }
    return { profileCount, totalObservations, infraLinks: linkSet.size, highConfidence };
  }, [aircraft, linksForAircraftTail]);

  return (
    <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
      <Stat icon={IdCard} label="Aircraft profiles" value={stats.profileCount} accent="hsl(190 100% 50%)" />
      <Stat icon={Plane} label="Total observations" value={stats.totalObservations} accent="hsl(218 100% 62%)" />
      <Stat icon={Link2} label="Infrastructure links" value={stats.infraLinks} accent="hsl(262 60% 70%)" />
      <Stat icon={Crosshair} label="High-confidence profiles" value={stats.highConfidence} accent="hsl(142 70% 52%)" />
    </div>
  );
}