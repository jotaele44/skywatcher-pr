import React, { useState, useMemo } from "react";
import { Building2, Link2 } from "lucide-react";
import { useSkywatcher, useResolvers } from "@/lib/SkywatcherData";
import { useDrawers } from "@/components/skywatcher/drawers/DrawerHub";
import PageHeader from "@/components/skywatcher/PageHeader";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import Panel from "@/components/skywatcher/Panel";
import StatusChip from "@/components/skywatcher/StatusChip";
import SyntheticDataBadge from "@/components/skywatcher/SyntheticDataBadge";
import InfrastructureLinkPanel from "@/components/skywatcher/InfrastructureLinkPanel";
import EmptyState from "@/components/skywatcher/EmptyState";
import LoadingState from "@/components/skywatcher/LoadingState";
import { Toolbar, SearchInput, FilterSelect } from "@/components/skywatcher/Toolbar";

const CRIT = { low: "muted", medium: "info", high: "warn", strategic: "blocked" };

const RADIUS_OPTS = [
  { value: "all", label: "Any distance" },
  { value: "5", label: "Within 5 nm" },
  { value: "10", label: "Within 10 nm" },
  { value: "25", label: "Within 25 nm" },
  { value: "50", label: "Within 50 nm" },
];

export default function Infrastructure() {
  const d = useSkywatcher();
  const r = useResolvers();
  const { open } = useDrawers();
  const [q, setQ] = useState("");
  const [type, setType] = useState("all");
  const [muni, setMuni] = useState("all");
  const [radius, setRadius] = useState("all");

  const typeOpts = useMemo(() => {
    const set = new Set(d.assets.map((a) => a.asset_type));
    return [{ value: "all", label: "All asset types" }, ...[...set].map((t) => ({ value: t, label: t }))];
  }, [d.assets]);
  const muniOpts = useMemo(() => {
    const set = new Set(d.assets.map((a) => a.municipality).filter(Boolean));
    return [{ value: "all", label: "All municipalities" }, ...[...set].map((mn) => ({ value: mn, label: mn }))];
  }, [d.assets]);

  const maxNm = radius === "all" ? null : Number(radius);

  const filtered = useMemo(() => {
    let rows = [...d.assets];
    if (q) { const s = q.toLowerCase(); rows = rows.filter((a) => [a.asset_name, a.municipality, a.asset_type].filter(Boolean).some((v) => v.toLowerCase().includes(s))); }
    if (type !== "all") rows = rows.filter((a) => a.asset_type === type);
    if (muni !== "all") rows = rows.filter((a) => a.municipality === muni);
    if (maxNm != null) {
      rows = rows.filter((a) => r.linksForAsset(a.asset_id).some((l) => l.distance_nm != null && l.distance_nm <= maxNm));
    }
    return rows;
  }, [d.assets, q, type, muni, maxNm, r]);

  if (d.loading) return <LoadingState />;

  return (
    <div className="space-y-5">
      <PageHeader title="Infrastructure Links" subtitle="ILAP / AASB spatial relationship workspace — candidate associations require review" icon={Building2} />
      <DiagnosticNoticeBanner />

      <Panel bodyClassName="space-y-4">
        <Toolbar>
          <SearchInput value={q} onChange={setQ} placeholder="Search asset, municipality…" />
          <FilterSelect value={type} onChange={setType} options={typeOpts} label="Asset type" />
          <FilterSelect value={muni} onChange={setMuni} options={muniOpts} label="Municipality" />
          <FilterSelect value={radius} onChange={setRadius} options={RADIUS_OPTS} label="Proximity radius" />
        </Toolbar>

        {filtered.length === 0 ? (
          <EmptyState icon={Building2} title="No infrastructure assets" />
        ) : (
          <div className="space-y-3">
            {filtered.map((a) => {
              let links = r.linksForAsset(a.asset_id);
              if (maxNm != null) links = links.filter((l) => l.distance_nm != null && l.distance_nm <= maxNm);
              return (
                <div key={a.id} className="rounded-xl border border-border bg-card">
                  <button onClick={() => open.asset(a.asset_id)} className="flex w-full items-center justify-between gap-3 border-b border-border px-4 py-3 text-left transition hover:bg-secondary/40">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[hsl(262_52%_60%/0.14)] ring-1 ring-[hsl(262_52%_60%/0.3)]"><Building2 className="h-4 w-4 text-[hsl(262_60%_74%)]" /></div>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-bold text-foreground">{a.asset_name}</p>
                        <p className="truncate text-[11px] text-muted-foreground">{a.asset_type} · {a.municipality}</p>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <StatusChip tone={CRIT[a.criticality_level]} label={a.criticality_level} />
                      <SyntheticDataBadge synthetic={a.synthetic_flag} />
                    </div>
                  </button>
                  <div className="p-3">
                    <div className="mb-2 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide text-muted-foreground"><Link2 className="h-3 w-3 text-primary" /> {links.length} spatial relationship link(s)</div>
                    <div className="space-y-2">
                      {links.length ? links.slice(0, 3).map((l) => (
                        <InfrastructureLinkPanel key={l.id} link={l} assetName={a.asset_name} onOpen={() => open.observation(l.observation_id)} />
                      )) : <p className="text-xs text-muted-foreground">No proximity links recorded.</p>}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Panel>
    </div>
  );
}