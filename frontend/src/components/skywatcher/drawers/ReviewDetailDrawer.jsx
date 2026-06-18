import React, { useState } from "react";
import { ClipboardCheck, ArrowRight, StickyNote } from "lucide-react";
import SideDrawer, { Field, Section, LinkChip } from "../SideDrawer";
import StatusChip from "../StatusChip";
import SyntheticDataBadge from "../SyntheticDataBadge";
import ReviewActions, { MANUAL_REVIEW_ACTIONS } from "../ReviewActions";
import { useSkywatcher, useResolvers } from "@/lib/SkywatcherData";
import { REVIEW_STATUS } from "@/lib/skywatcher";
import { toast } from "@/components/ui/use-toast";

const SEV = { low: "muted", medium: "warn", high: "blocked" };

export default function ReviewDetailDrawer({ id, onClose, go }) {
  const d = useSkywatcher();
  const r = useResolvers();
  const item = d.reviews.find((x) => x.id === id) || d.reviews.find((x) => x.review_id === id);
  const [notes, setNotes] = useState(item?.notes || "");
  if (!item) return <SideDrawer open onClose={onClose} title="Review item not found" />;

  const rs = REVIEW_STATUS[item.review_status] || REVIEW_STATUS.open;
  const target = r.reviewItemTarget(item);

  const setStatus = (s) => {
    const patch = { review_status: s };
    if (s === "resolved" || s === "rejected") patch.resolved_at = new Date().toISOString();
    d.updateRecord("reviews", item.id, patch);
  };
  const saveNotes = () => {
    d.updateRecord("reviews", item.id, { notes });
    toast({ title: "Notes saved" });
  };

  const openTarget = () => {
    if (!target.rec) return;
    const map = { observation: "observation", capture: "capture", route: "route", aircraft: "aircraft", export: "export" };
    if (target.kind === "link") { go.observation(target.rec.observation_id); return; }
    if (map[target.kind]) go[map[target.kind]](target.rec[idField(target.kind)]);
  };

  return (
    <SideDrawer
      open
      onClose={onClose}
      title={item.reason}
      subtitle={`${item.review_id} · ${item.item_type}`}
      badges={
        <>
          <StatusChip tone={rs.tone} label={rs.label} />
          <StatusChip tone={SEV[item.severity] || "muted"} label={`${item.severity} severity`} />
          <SyntheticDataBadge synthetic={item.synthetic_flag} />
        </>
      }
    >
      <Section title="Review Actions" icon={ClipboardCheck}>
        <ReviewActions current={item.review_status} onChange={setStatus} actions={MANUAL_REVIEW_ACTIONS} />
      </Section>

      <Section title="Detail">
        <div className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-card p-3">
          <Field label="Item Type">{item.item_type}</Field>
          <Field label="Item ID" mono>{item.item_id}</Field>
          <Field label="Assigned To">{item.assigned_to}</Field>
          <Field label="Created">{item.created_at ? new Date(item.created_at).toLocaleString() : "—"}</Field>
          <Field label="Resolved">{item.resolved_at ? new Date(item.resolved_at).toLocaleString() : "—"}</Field>
        </div>
        <div className="mt-2 rounded-lg border border-[hsl(38_100%_50%/0.2)] bg-[hsl(38_100%_50%/0.05)] px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-[hsl(38_100%_62%)]">Recommended Action</p>
          <p className="mt-0.5 text-sm text-foreground/90">{item.recommended_action}</p>
        </div>
      </Section>

      <Section title="Underlying Linked Record" icon={ArrowRight}>
        {target.rec ? (
          <LinkChip
            onClick={openTarget}
            label={recordLabel(target)}
            sublabel={`${item.item_type} · ${item.item_id}`}
          />
        ) : (
          <p className="text-xs text-muted-foreground">Linked record not available in current dataset.</p>
        )}
      </Section>

      <Section title="Notes" icon={StickyNote}>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary/50 focus:outline-none"
          placeholder="Add diagnostic review notes…"
        />
        <button onClick={saveNotes} className="mt-2 rounded-lg border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/20">
          Save Notes
        </button>
      </Section>
    </SideDrawer>
  );
}

function idField(kind) {
  return {
    observation: "observation_id", capture: "capture_id", route: "route_segment_id",
    aircraft: "aircraft_id", export: "package_id",
  }[kind];
}

function recordLabel(target) {
  const r = target.rec;
  switch (target.kind) {
    case "observation": return `${r.callsign} · ${r.observation_id}`;
    case "capture": return `${r.file_name} · ${r.capture_id}`;
    case "route": return `${r.inferred_route_name} · ${r.route_segment_id}`;
    case "aircraft": return `${r.callsign} · ${r.aircraft_id}`;
    case "export": return `${r.package_name} · ${r.package_id}`;
    case "link": return `Asset link · ${r.link_id}`;
    default: return "Linked record";
  }
}