import React from "react";
import { Route as RouteIcon, Camera, Plane, Gauge } from "lucide-react";
import SideDrawer, { Field, Section, LinkChip } from "../SideDrawer";
import StatusChip from "../StatusChip";
import ConfidenceBadge from "../ConfidenceBadge";
import SyntheticDataBadge from "../SyntheticDataBadge";
import ReviewActions from "../ReviewActions";
import { useSkywatcher, useResolvers } from "@/lib/SkywatcherData";
import { REVIEW_STATUS } from "@/lib/skywatcher";

export default function RouteDetailDrawer({ id, onClose, go }) {
  const d = useSkywatcher();
  const r = useResolvers();
  const route = d.routes.find((x) => x.id === id) || r.routeById(id);
  if (!route) return <SideDrawer open onClose={onClose} title="Route segment not found" />;

  const capture = r.captureById(route.capture_id);
  const obs = r.observationById(route.observation_id);
  const rs = REVIEW_STATUS[route.review_status] || REVIEW_STATUS.new;

  return (
    <SideDrawer
      open
      onClose={onClose}
      title={route.inferred_route_name}
      subtitle={`${route.route_segment_id} · cluster ${route.route_cluster_id}`}
      badges={
        <>
          <StatusChip tone={rs.tone} label={rs.label} />
          <ConfidenceBadge score={route.confidence_score} showBar={false} />
          <SyntheticDataBadge synthetic={route.synthetic_flag} />
        </>
      }
    >
      <Section title="Review State" icon={Gauge}>
        <ReviewActions current={route.review_status} onChange={(s) => d.updateRecord("routes", route.id, { review_status: s })} />
      </Section>

      <Section title="Segment Geometry" icon={RouteIcon}>
        <div className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-card p-3">
          <Field label="Start" mono>{route.start_lat?.toFixed(4)}, {route.start_lon?.toFixed(4)}</Field>
          <Field label="End" mono>{route.end_lat?.toFixed(4)}, {route.end_lon?.toFixed(4)}</Field>
          <Field label="Length" mono>{route.segment_length_nm} nm</Field>
          <Field label="Extraction Method">{route.extraction_method}</Field>
          <Field label="Cluster" mono>{route.route_cluster_id}</Field>
        </div>
      </Section>

      <Section title="Linked Capture" icon={Camera}>
        {capture ? (
          <LinkChip onClick={() => go.capture(capture.capture_id)} label={capture.file_name} sublabel={`${capture.capture_id} · ${capture.ingest_status}`} />
        ) : <p className="text-xs text-muted-foreground">No linked capture.</p>}
      </Section>

      <Section title="Linked Observation" icon={Plane}>
        {obs ? (
          <LinkChip onClick={() => go.observation(obs.observation_id)} label={`${obs.callsign} · ${obs.mission_inference}`} sublabel={obs.observation_id} />
        ) : <p className="text-xs text-muted-foreground">No linked observation.</p>}
      </Section>
    </SideDrawer>
  );
}