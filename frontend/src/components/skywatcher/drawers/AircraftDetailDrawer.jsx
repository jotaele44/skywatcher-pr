import React from "react";
import { History, Route as RouteIcon, IdCard } from "lucide-react";
import SideDrawer, { Field, Section, LinkChip } from "../SideDrawer";
import ConfidenceBadge from "../ConfidenceBadge";
import SyntheticDataBadge from "../SyntheticDataBadge";
import SourceProvenanceBadge from "../SourceProvenanceBadge";
import RouteSegmentPanel from "../RouteSegmentPanel";
import { useResolvers } from "@/lib/SkywatcherData";

export default function AircraftDetailDrawer({ id, onClose, go }) {
  const r = useResolvers();
  const ac = r.aircraftById(id);
  if (!ac) return <SideDrawer open onClose={onClose} title="Aircraft profile not found" />;

  const observations = r.observationsForAircraft(ac.tail_number);
  const routes = r.routesForAircraftTail(ac.tail_number);
  const lowConf = (ac.profile_confidence ?? 1) < 0.5;

  return (
    <SideDrawer
      open
      onClose={onClose}
      title={ac.callsign}
      subtitle={`${ac.aircraft_id} · ${ac.aircraft_type}`}
      badges={
        <>
          <ConfidenceBadge score={ac.profile_confidence} showBar={false} />
          <SyntheticDataBadge synthetic={ac.synthetic_flag} />
          <SourceProvenanceBadge source="registry_match" />
        </>
      }
    >
      {lowConf && (
        <div className="mb-4 rounded-lg border border-[hsl(4_90%_58%/0.25)] bg-[hsl(4_90%_58%/0.06)] px-3 py-2 text-xs text-[hsl(4_90%_68%)]">
          Low-confidence profile. Treat as candidate association — requires review before any analytical use.
        </div>
      )}

      <Section title="Profile" icon={IdCard}>
        <div className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-card p-3">
          <Field label="Tail Number" mono>{ac.tail_number}</Field>
          <Field label="Operator">{ac.operator_name}</Field>
          <Field label="Operator Category">{ac.operator_category}</Field>
          <Field label="Mission Category">{ac.mission_category}</Field>
          <Field label="Registry Source">{ac.registry_source}</Field>
          <Field label="Observation Count" mono>{ac.observation_count}</Field>
          <Field label="First Seen">{ac.first_seen_at ? new Date(ac.first_seen_at).toLocaleDateString() : "—"}</Field>
          <Field label="Last Seen">{ac.last_seen_at ? new Date(ac.last_seen_at).toLocaleDateString() : "—"}</Field>
        </div>
        {ac.notes && <p className="mt-2 rounded border border-border bg-secondary/40 px-3 py-2 text-xs text-muted-foreground">{ac.notes}</p>}
      </Section>

      <Section title="Observation History" icon={History}>
        <div className="space-y-2">
          {observations.length ? observations.map((o) => (
            <LinkChip key={o.id} onClick={() => go.observation(o.observation_id)}
              label={`${o.callsign} · ${o.mission_inference}`}
              sublabel={`${o.observation_id} · ${o.observed_at ? new Date(o.observed_at).toLocaleString() : ""}`} />
          )) : <p className="text-xs text-muted-foreground">No linked observations.</p>}
        </div>
      </Section>

      <Section title="Linked Route Segments" icon={RouteIcon}>
        <div className="space-y-2">
          {routes.length ? routes.map((rt) => (
            <RouteSegmentPanel key={rt.id} route={rt} onOpen={() => go.route(rt.route_segment_id)} />
          )) : <p className="text-xs text-muted-foreground">No linked route segments.</p>}
        </div>
      </Section>
    </SideDrawer>
  );
}