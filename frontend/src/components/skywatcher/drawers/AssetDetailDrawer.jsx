import React from "react";
import { Building2, Plane, Link2 } from "lucide-react";
import SideDrawer, { Field, Section, LinkChip } from "../SideDrawer";
import StatusChip from "../StatusChip";
import SyntheticDataBadge from "../SyntheticDataBadge";
import InfrastructureLinkPanel from "../InfrastructureLinkPanel";
import { useSkywatcher, useResolvers } from "@/lib/SkywatcherData";

const CRIT = {
  low: "muted", medium: "info", high: "warn", strategic: "blocked",
};

export default function AssetDetailDrawer({ id, onClose, go }) {
  const d = useSkywatcher();
  const r = useResolvers();
  const asset = d.assets.find((a) => a.id === id) || r.assetById(id);
  if (!asset) return <SideDrawer open onClose={onClose} title="Asset not found" />;

  const links = r.linksForAsset(asset.asset_id);
  const observations = r.observationsForAsset(asset.asset_id);

  return (
    <SideDrawer
      open
      onClose={onClose}
      title={asset.asset_name}
      subtitle={`${asset.asset_id} · ${asset.asset_type}`}
      badges={
        <>
          <StatusChip tone={CRIT[asset.criticality_level] || "muted"} label={`${asset.criticality_level} criticality`} />
          <SyntheticDataBadge synthetic={asset.synthetic_flag} />
        </>
      }
    >
      <Section title="Asset Detail" icon={Building2}>
        <div className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-card p-3">
          <Field label="Asset Type">{asset.asset_type}</Field>
          <Field label="Municipality">{asset.municipality}</Field>
          <Field label="Coordinates" mono>{asset.latitude?.toFixed(4)}, {asset.longitude?.toFixed(4)}</Field>
          <Field label="Linked Observations" mono>{asset.linked_observation_count ?? observations.length}</Field>
          <Field label="Public Source">{asset.public_source}</Field>
        </div>
      </Section>

      <Section title="Spatial Relationship Links" icon={Link2}>
        <div className="space-y-2">
          {links.length ? links.map((l) => (
            <InfrastructureLinkPanel key={l.id} link={l} assetName={asset.asset_name}
              onOpen={() => go.observation(l.observation_id)} />
          )) : <p className="text-xs text-muted-foreground">No proximity links recorded.</p>}
        </div>
      </Section>

      <Section title="Linked Observations" icon={Plane}>
        <div className="space-y-2">
          {observations.length ? observations.map((o) => (
            <LinkChip key={o.id} onClick={() => go.observation(o.observation_id)} label={`${o.callsign} · ${o.mission_inference}`} sublabel={`${o.observation_id} · ${o.distance_nm} nm`} />
          )) : <p className="text-xs text-muted-foreground">No linked observations.</p>}
        </div>
      </Section>
    </SideDrawer>
  );
}