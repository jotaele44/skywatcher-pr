import React, { useState, useMemo } from "react";
import { Route as RouteIcon, Layers } from "lucide-react";
import { useSkywatcher } from "@/lib/SkywatcherData";
import { useDrawers } from "@/components/skywatcher/drawers/DrawerHub";
import PageHeader from "@/components/skywatcher/PageHeader";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import Panel from "@/components/skywatcher/Panel";
import StatusChip from "@/components/skywatcher/StatusChip";
import ConfidenceBadge from "@/components/skywatcher/ConfidenceBadge";
import SyntheticDataBadge from "@/components/skywatcher/SyntheticDataBadge";
import PuertoRicoMapShell from "@/components/skywatcher/PuertoRicoMapShell";
import EmptyState from "@/components/skywatcher/EmptyState";
import LoadingState from "@/components/skywatcher/LoadingState";
import { Toolbar, SearchInput, FilterSelect } from "@/components/skywatcher/Toolbar";
import { REVIEW_STATUS } from "@/lib/skywatcher";

const REVIEW_OPTS = [
  { value: "all", label: "All review states" },
  { value: "new", label: "New" }, { value: "triaged", label: "Triaged" },
  { value: "needs_review", label: "Needs Review" }, { value: "verified", label: "Verified" },
  { value: "rejected", label: "Rejected" },
];

export default function Routes() {
  const d = useSkywatcher();
  const { open } = useDrawers();
  const [q, setQ] = useState("");
  const [review, setReview] = useState("all");

  const filtered = useMemo(() => {
    let rows = [...d.routes];
    if (q) { const s = q.toLowerCase(); rows = rows.filter((r) => [r.inferred_route_name, r.route_segment_id, r.route_cluster_id, r.extraction_method].filter(Boolean).some((v) => v.toLowerCase().includes(s))); }
    if (review !== "all") rows = rows.filter((r) => r.review_status === review);
    return rows;
  }, [d.routes, q, review]);

  const clusters = useMemo(() => {
    const map = {};
    filtered.forEach((r) => {
      const k = r.route_cluster_id || "unclustered";
      if (!map[k]) map[k] = { id: k, segments: [], totalNm: 0, avgConf: 0 };
      map[k].segments.push(r);
      map[k].totalNm += r.segment_length_nm || 0;
    });
    return Object.values(map).map((c) => ({ ...c, avgConf: c.segments.reduce((s, r) => s + (r.confidence_score || 0), 0) / c.segments.length }));
  }, [filtered]);

  if (d.loading) return <LoadingState />;

  return (
    <div className="space-y-5">
      <PageHeader title="Route-Line Mining" subtitle="Route-line-segment mining outputs & cluster analysis" icon={RouteIcon} />
      <DiagnosticNoticeBanner />

      <PuertoRicoMapShell routes={filtered} airports={d.airports} observations={[]} assets={d.assets} height={280} title="Route-Line Segment Context" />

      <Panel title="Route Clusters" icon={Layers}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {clusters.map((c) => (
            <div key={c.id} className="rounded-lg border border-border bg-[hsl(220_30%_6%)] p-3">
              <p className="font-mono text-xs font-bold text-primary">{c.id}</p>
              <p className="mt-1 text-2xl font-bold text-foreground">{c.segments.length}</p>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">segments</p>
              <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground">
                <span className="font-mono">{c.totalNm.toFixed(1)} nm</span>
                <ConfidenceBadge score={c.avgConf} showBar={false} />
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel bodyClassName="space-y-4">
        <Toolbar>
          <SearchInput value={q} onChange={setQ} placeholder="Search route name, cluster, method…" />
          <FilterSelect value={review} onChange={setReview} options={REVIEW_OPTS} label="Review status" />
        </Toolbar>

        {filtered.length === 0 ? (
          <EmptyState icon={RouteIcon} title="No route segments" />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border scrollbar-thin">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2 font-semibold">Route</th>
                  <th className="px-3 py-2 font-semibold">Cluster</th>
                  <th className="px-3 py-2 font-semibold">Start → End</th>
                  <th className="px-3 py-2 font-semibold">Length</th>
                  <th className="px-3 py-2 font-semibold">Method</th>
                  <th className="px-3 py-2 font-semibold">Conf</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => {
                  const rs = REVIEW_STATUS[r.review_status] || REVIEW_STATUS.new;
                  return (
                    <tr key={r.id} onClick={() => open.route(r.route_segment_id)} className="cursor-pointer border-b border-border/50 transition hover:bg-secondary/40">
                      <td className="px-3 py-2.5"><div className="font-semibold text-foreground">{r.inferred_route_name}</div><div className="mt-0.5"><SyntheticDataBadge synthetic={r.synthetic_flag} /></div></td>
                      <td className="px-3 py-2.5 font-mono text-xs text-primary">{r.route_cluster_id}</td>
                      <td className="px-3 py-2.5 font-mono text-[10px] text-muted-foreground">{r.start_lat?.toFixed(2)},{r.start_lon?.toFixed(2)} → {r.end_lat?.toFixed(2)},{r.end_lon?.toFixed(2)}</td>
                      <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{r.segment_length_nm} nm</td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground">{r.extraction_method}</td>
                      <td className="px-3 py-2.5"><ConfidenceBadge score={r.confidence_score} showBar={false} /></td>
                      <td className="px-3 py-2.5"><StatusChip tone={rs.tone} label={rs.label} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}