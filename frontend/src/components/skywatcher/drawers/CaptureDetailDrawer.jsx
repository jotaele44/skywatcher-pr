import React from "react";
import { Camera, Plane, Route as RouteIcon, ClipboardCheck, Copy } from "lucide-react";
import SideDrawer, { Field, Section, LinkChip } from "../SideDrawer";
import StatusChip from "../StatusChip";
import SyntheticDataBadge from "../SyntheticDataBadge";
import CaptureQualityPanel from "../CaptureQualityPanel";
import RouteSegmentPanel from "../RouteSegmentPanel";
import { useSkywatcher, useResolvers } from "@/lib/SkywatcherData";
import { INGEST_STATUS } from "@/lib/skywatcher";
import { toast } from "@/components/ui/use-toast";

export default function CaptureDetailDrawer({ id, onClose, go }) {
  const d = useSkywatcher();
  const r = useResolvers();
  const cap = d.captures.find((c) => c.id === id) || r.captureById(id);
  if (!cap) return <SideDrawer open onClose={onClose} title="Capture not found" />;

  const observations = r.observationsForCapture(cap.capture_id);
  const routes = r.routesForCapture(cap.capture_id);
  const is = INGEST_STATUS[cap.ingest_status] || INGEST_STATUS.queued;

  const setStatus = (s, msg) => {
    d.updateRecord("captures", cap.id, { ingest_status: s });
    toast({ title: "Diagnostic state updated", description: msg });
  };
  const placeholder = (msg) => toast({ title: "Repository-side action (placeholder)", description: msg });
  const openReview = async () => {
    await d.createReview({
      review_id: `rev_cap_${Date.now()}`, item_type: "capture", item_id: cap.capture_id,
      reason: "Manual review opened from FR24 Intake for capture metadata.",
      severity: "medium", assigned_to: "operator_diagnostic", review_status: "open",
      recommended_action: "Review capture metadata and extraction quality.",
      created_at: new Date().toISOString(), notes: "Created from capture drawer (diagnostic).", synthetic_flag: true,
    });
    toast({ title: "Manual review item created", description: `Linked to ${cap.capture_id}` });
  };

  return (
    <SideDrawer
      open
      onClose={onClose}
      title={cap.file_name}
      subtitle={`${cap.capture_id} · ${cap.capture_type}`}
      badges={
        <>
          <StatusChip tone={is.tone} label={is.label} />
          {cap.manual_review_required && <StatusChip tone="warn" label="Review Required" />}
          <SyntheticDataBadge synthetic={cap.synthetic_flag} />
        </>
      }
      footer={
        <div className="space-y-2">
          <p className="text-[10px] text-muted-foreground">
            FR24 ingest is repository-side. Federation only visualizes capture metadata and review state — these actions update diagnostic state only.
          </p>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => placeholder("Capture queued (diagnostic placeholder, no execution).")} className="rounded-lg border border-border bg-secondary px-3 py-1.5 text-xs font-semibold text-foreground/80 hover:text-primary">Queue Capture</button>
            <button onClick={openReview} className="rounded-lg border border-border bg-secondary px-3 py-1.5 text-xs font-semibold text-foreground/80 hover:text-[hsl(38_100%_62%)]">Open Manual Review</button>
            <button onClick={() => placeholder("Observation link recorded (diagnostic placeholder).")} className="rounded-lg border border-border bg-secondary px-3 py-1.5 text-xs font-semibold text-foreground/80 hover:text-primary">Link Observation</button>
            <button onClick={() => setStatus("duplicate", "Marked as duplicate.")} className="rounded-lg border border-border bg-secondary px-3 py-1.5 text-xs font-semibold text-foreground/80 hover:text-[hsl(262_60%_76%)]">Mark Duplicate</button>
            <button onClick={() => setStatus("rejected", "Capture rejected.")} className="rounded-lg border border-border bg-secondary px-3 py-1.5 text-xs font-semibold text-foreground/80 hover:text-[hsl(4_90%_66%)]">Reject Capture</button>
          </div>
        </div>
      }
    >
      <Section title="Capture Metadata" icon={Camera}>
        <div className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-card p-3">
          <Field label="Capture Type">{cap.capture_type}</Field>
          <Field label="Captured At">{cap.captured_at ? new Date(cap.captured_at).toLocaleString() : "—"}</Field>
          <Field label="Linked Observations" mono>{cap.linked_observation_count ?? observations.length}</Field>
          <Field label="Provenance">{cap.provenance_note}</Field>
        </div>
        <div className="mt-2 flex items-center gap-2 rounded border border-border bg-[hsl(220_30%_4%)] px-3 py-2">
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground shrink-0">sha256</span>
          <code className="flex-1 overflow-x-auto whitespace-nowrap font-mono text-[10px] text-foreground/70 scrollbar-thin">{cap.sha256_hash}</code>
          <button onClick={() => { navigator.clipboard?.writeText(cap.sha256_hash); toast({ title: "Hash copied" }); }} className="text-muted-foreground hover:text-primary"><Copy className="h-3 w-3" /></button>
        </div>
      </Section>

      <Section title="Extraction Quality" icon={ClipboardCheck}>
        <CaptureQualityPanel capture={cap} />
      </Section>

      <Section title="Linked Observations" icon={Plane}>
        <div className="space-y-2">
          {observations.length ? observations.map((o) => (
            <LinkChip key={o.id} onClick={() => go.observation(o.observation_id)} label={`${o.callsign} · ${o.mission_inference}`} sublabel={o.observation_id} />
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