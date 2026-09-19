import React, { useEffect, useState, useMemo } from "react";
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
import { federation } from "@/api/federationClient";

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
  const [corpus, setCorpus] = useState(null);
  const [deepCorpus, setDeepCorpus] = useState(null);
  const [showProvenance, setShowProvenance] = useState(false);
  const [recurrence, setRecurrence] = useState(null);
  const [recurrenceMonth, setRecurrenceMonth] = useState("");
  const [recurrenceFamily, setRecurrenceFamily] = useState("");

  useEffect(() => {
    let active = true;
    Promise.allSettled([federation.flightCorpusV4.status(), federation.flightCorpusV4.deepInterface()])
      .then(([status, deep]) => {
        if (!active) return;
        setCorpus(status.status === "fulfilled" ? status.value : null);
        setDeepCorpus(deep.status === "fulfilled" ? deep.value : null);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    federation.flightCorpusV4.routeFamilyRecurrence({ month: recurrenceMonth, family: recurrenceFamily })
      .then((value) => { if (active) setRecurrence(value); })
      .catch(() => { if (active) setRecurrence(null); });
    return () => { active = false; };
  }, [recurrenceMonth, recurrenceFamily]);

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

      {corpus && (
        <Panel title="Flight Corpus V4 — Evidence State">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div><p className="text-[10px] uppercase text-muted-foreground">Certification</p><p className="font-mono font-bold">{corpus.status}</p></div>
            <div><p className="text-[10px] uppercase text-muted-foreground">Trajectory eligible</p><p className="font-mono font-bold">{corpus.denominators?.trajectory_eligible ?? "UNKNOWN"}</p></div>
            <div><p className="text-[10px] uppercase text-muted-foreground">Pair denominator</p><p className="font-mono font-bold">{corpus.denominators?.unordered_pair_denominator ?? "UNKNOWN"}</p></div>
            <div><p className="text-[10px] uppercase text-muted-foreground">Artifact</p><p className="font-mono text-xs">{corpus.artifact_bound ? "BOUND" : "UNKNOWN"}</p></div>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div>
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Blocked / unresolved vectors</p>
              <ul className="space-y-1 font-mono text-xs">{(corpus.blocked || []).map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
            <div>
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Candidate events</p>
              {(corpus.promoted_candidates || []).map((candidate) => (
                <div key={candidate.aircraft?.join("-") + candidate.date} className="rounded border border-border p-2 text-xs">
                  <p className="font-mono font-semibold">{candidate.aircraft?.join(" ↔ ")} · {candidate.date}</p>
                  <p>{candidate.classification}</p>
                  <p className="text-muted-foreground">Mission: {candidate.mission || "UNKNOWN"} · Coordination: {candidate.coordination || "UNKNOWN"}</p>
                </div>
              ))}
            </div>
          </div>
          {deepCorpus && (
            <div className="mt-4 border-t border-border pt-3">
              <div className="flex flex-wrap gap-4 text-xs">
                <span>Identity/source contradictions: <strong>{deepCorpus.contradiction_state?.identity_source_contradictions_v2 ?? "UNKNOWN"}</strong> · {deepCorpus.contradiction_state?.adjudication}</span>
                <span>Single-point exclusions: <strong>{deepCorpus.exclusion_state?.single_point_nontrajectory_records ?? "UNKNOWN"}</strong></span>
                <span>Temporal recurrence: <strong>{deepCorpus.temporal_recurrence?.availability ?? "UNKNOWN"}</strong></span>
              </div>
              <button type="button" onClick={() => setShowProvenance((value) => !value)} className="mt-3 rounded border border-border px-3 py-1.5 text-xs font-semibold hover:bg-secondary/40">
                {showProvenance ? "Hide provenance" : "Inspect provenance"}
              </button>
              {showProvenance && (
                <div className="mt-3 max-h-64 overflow-auto rounded border border-border">
                  <table className="w-full text-left text-[10px]">
                    <thead><tr className="bg-secondary/40"><th className="p-2">Member</th><th className="p-2">Bytes</th><th className="p-2">SHA-256</th></tr></thead>
                    <tbody>{(deepCorpus.members || []).map((member) => <tr key={member.path} className="border-t border-border/50"><td className="p-2 font-mono">{member.path}</td><td className="p-2 font-mono">{member.size_bytes}</td><td className="p-2 font-mono">{member.sha256}</td></tr>)}</tbody>
                  </table>
                </div>
              )}
              <div className="mt-3 grid gap-2 sm:grid-cols-2 text-[10px] text-muted-foreground">
                <p>Route-family recurrence member: {deepCorpus.temporal_recurrence?.route_family_member?.path || "BLOCKED"}</p>
                <p>Airport-edge recurrence member: {deepCorpus.temporal_recurrence?.airport_edge_member?.path || "BLOCKED"}</p>
              </div>
            </div>
          )}
          <p className="mt-3 text-[10px] text-muted-foreground">Candidate geometry, temporal recurrence, and co-route evidence do not establish mission, coordination, operator, or targeting.</p>
        </Panel>
      )}

      {recurrence && (
        <Panel title="V4 Temporal Route-Family Recurrence">
          <div className="flex flex-wrap gap-3">
            <input value={recurrenceMonth} onChange={(e) => setRecurrenceMonth(e.target.value)} placeholder="Month (YYYY-MM)" className="rounded border border-border bg-background px-3 py-2 text-xs" />
            <input value={recurrenceFamily} onChange={(e) => setRecurrenceFamily(e.target.value)} placeholder="Family ID" className="rounded border border-border bg-background px-3 py-2 text-xs" />
            <span className="self-center text-xs text-muted-foreground">{recurrence.row_count} rows · {recurrence.availability}</span>
          </div>
          <div className="mt-3 overflow-x-auto rounded border border-border">
            <table className="w-full text-xs">
              <thead><tr className="bg-secondary/40 text-left"><th className="p-2">Month</th><th className="p-2">Family</th><th className="p-2">Tracks</th></tr></thead>
              <tbody>{(recurrence.rows || []).map((row, index) => <tr key={row.utc_month + "-" + row.consensus_family_id + "-" + index} className="border-t border-border/50"><td className="p-2 font-mono">{row.utc_month}</td><td className="p-2 font-mono">{row.consensus_family_id}</td><td className="p-2 font-mono">{row.tracks}</td></tr>)}</tbody>
            </table>
          </div>
          <p className="mt-2 text-[10px] text-muted-foreground">Source member SHA-256: {recurrence.member?.sha256 || "UNKNOWN"}. These are DERIVED recurrence counts, not RAW observations and not mission classifications.</p>
        </Panel>
      )}

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