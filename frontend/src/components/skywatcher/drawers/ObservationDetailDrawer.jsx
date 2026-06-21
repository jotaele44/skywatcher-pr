import React from "react";
import { IdCard, Camera, Route as RouteIcon, Building2, MapPin, Gauge } from "lucide-react";
import SideDrawer, { Field, Section, LinkChip } from "../SideDrawer";
import StatusChip from "../StatusChip";
import ConfidenceBadge from "../ConfidenceBadge";
import SyntheticDataBadge from "../SyntheticDataBadge";
import SourceProvenanceBadge from "../SourceProvenanceBadge";
import ReviewActions from "../ReviewActions";
import RouteSegmentPanel from "../RouteSegmentPanel";
import InfrastructureLinkPanel from "../InfrastructureLinkPanel";
import { useSkywatcher, useResolvers } from "@/lib/SkywatcherData";
import { REVIEW_STATUS } from "@/lib/skywatcher";

export default function ObservationDetailDrawer({ id, onClose, go }) {
  const d = useSkywatcher();
  const r = useResolvers();
  const obs = d.observations.find((o) => o.id === id) || r.observationById(id);
  if (!obs) return <SideDrawer open onClose={onClose} title="Observation not found" />;

  const aircraft = r.aircraftByTail(obs.tail_number);
  const capture = r.captureById(obs.linked_capture_id);
  const routes = r.routesForObservation(obs.observation_id);
  const links = r.linksForObservation(obs.observation_id);
  const rs = REVIEW_STATUS[obs.review_status] || REVIEW_STATUS.new;

  return (
    <SideDrawer
      open
      onClose={onClose}
      title={obs.callsign}
      subtitle={`${obs.observation_id} · ${obs.aircraft_type}`}
      badges={
        <>
          <StatusChip tone={rs.tone} label={rs.label} />
          <ConfidenceBadge score={obs.confidence_score} showBar={false} />
          <SyntheticDataBadge synthetic={obs.synthetic_flag} />
          <SourceProvenanceBadge source={obs.source_type} />
        </>
      }
    >
      <Section title="Review State" icon={Gauge}>
        <ReviewActions current={obs.review_status} onChange={(s) => d.updateRecord("observations", obs.id, { review_status: s })} />
        <p className="mt-2 text-[11px] text-muted-foreground">
          Prototype review action updates diagnostic state only. Spatial relationships are candidate associations and require review.
        </p>
      </Section>

      <Section title="Observation Telemetry" icon={MapPin}>
        <div className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-card p-3">
          <Field label="Tail Number" mono>{obs.tail_number}</Field>
          <Field label="Operator">{obs.operator_name}</Field>
          <Field label="Operator Category">{obs.operator_category}</Field>
          <Field label="Mission Inference">{obs.mission_inference}</Field>
          <Field label="Observed At">{obs.observed_at ? new Date(obs.observed_at).toLocaleString() : "—"}</Field>
          <Field label="Altitude" mono>{obs.altitude_ft} ft</Field>
          <Field label="Speed" mono>{obs.speed_kt} kt</Field>
          <Field label="Heading" mono>{obs.heading_deg}°</Field>
          <Field label="Coordinates" mono>{obs.latitude?.toFixed(4)}, {obs.longitude?.toFixed(4)}</Field>
          <Field label="Nearest Airport">{obs.nearest_airport_name}</Field>
          <Field label="Nearest Asset">{obs.nearest_asset_name || "—"}</Field>
          <Field label="Distance" mono>{obs.distance_nm} nm</Field>
        </div>
        {obs.provenance_note && (
          <p className="mt-2 rounded border border-border bg-secondary/40 px-3 py-2 text-xs text-muted-foreground">
            <span className="font-semibold text-foreground/80">Provenance: </span>{obs.provenance_note}
          </p>
        )}
      </Section>

      <Section title="Linked Aircraft Profile" icon={IdCard}>
        {aircraft ? (
          <LinkChip onClick={() => go.aircraft(aircraft.aircraft_id)} label={`${aircraft.callsign} · ${aircraft.aircraft_type}`} sublabel={aircraft.aircraft_id} />
        ) : <p className="text-xs text-muted-foreground">No linked aircraft profile.</p>}
      </Section>

      <Section title="Linked FR24 Capture" icon={Camera}>
        {capture ? (
          <LinkChip onClick={() => go.capture(capture.capture_id)} label={capture.file_name} sublabel={`${capture.capture_id} · ${capture.ingest_status}`} />
        ) : <p className="text-xs text-muted-foreground">No linked capture.</p>}
      </Section>

      <Section title="Linked Route Segments" icon={RouteIcon}>
        <div className="space-y-2">
          {routes.length ? routes.map((rt) => (
            <RouteSegmentPanel key={rt.id} route={rt} onOpen={() => go.route(rt.route_segment_id)} />
          )) : <p className="text-xs text-muted-foreground">No linked route segments.</p>}
        </div>
      </Section>

      <Section title="Infrastructure Links" icon={Building2}>
        <div className="space-y-2">
          {links.length ? links.map((l) => (
            <InfrastructureLinkPanel key={l.id} link={l} assetName={r.assetById(l.asset_id)?.asset_name} onOpen={() => go.asset(l.asset_id)} />
          )) : <p className="text-xs text-muted-foreground">No infrastructure links.</p>}
        </div>
      </Section>
    </SideDrawer>
  );
}