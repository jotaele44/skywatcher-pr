import React from "react";
import {
  LayoutDashboard, Plane, IdCard, Camera, ClipboardCheck, FlaskConical,
  ShieldCheck, Network, CheckCircle2, XCircle, AlertTriangle, Share2, Activity,
} from "lucide-react";
import { useSkywatcher, useResolvers } from "@/lib/SkywatcherData";
import ObservationHeatMap from "@/components/skywatcher/ObservationHeatMap";
import HourlyObservationsChart from "@/components/skywatcher/HourlyObservationsChart";
import { useDrawers } from "@/components/skywatcher/drawers/DrawerHub";
import { computeMetrics } from "@/lib/metrics";
import { PROGRAM } from "@/lib/skywatcher";
import PageHeader from "@/components/skywatcher/PageHeader";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import MetricCard from "@/components/skywatcher/MetricCard";
import Panel from "@/components/skywatcher/Panel";
import StatusChip from "@/components/skywatcher/StatusChip";
import ConfidenceBadge from "@/components/skywatcher/ConfidenceBadge";
import SyntheticDataBadge from "@/components/skywatcher/SyntheticDataBadge";
import BlockerList from "@/components/skywatcher/BlockerList";
import ManualReviewPanel from "@/components/skywatcher/ManualReviewPanel";
import PuertoRicoMapShell from "@/components/skywatcher/PuertoRicoMapShell";
import LoadingState from "@/components/skywatcher/LoadingState";
import { REVIEW_STATUS, SYNC_STATUS } from "@/lib/skywatcher";

function IdentityRow({ label, value, tone }) {
  return (
    <div className="flex items-center justify-between border-b border-border/60 py-2 last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={`font-mono text-xs font-semibold ${tone || "text-foreground"}`}>{value}</span>
    </div>
  );
}

export default function Dashboard() {
  const d = useSkywatcher();
  const { open } = useDrawers();
  const { airportById, assetById } = useResolvers();
  if (d.loading) return <LoadingState />;

  const m = computeMetrics(d);
  const recentObs = [...d.observations].sort((a, b) => new Date(b.observed_at) - new Date(a.observed_at)).slice(0, 6);
  const recentReviews = d.reviews.filter((r) => r.review_status === "open" || r.review_status === "in_review").slice(0, 5);
  const recentSyncs = [...d.syncs].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 6);
  const latestReadiness = [...d.readiness].sort((a, b) => new Date(b.report_date) - new Date(a.report_date))[0];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Command Dashboard"
        subtitle="Airspace intelligence node — diagnostic operational surface"
        icon={LayoutDashboard}
      />
      <DiagnosticNoticeBanner />

      {/* Identity + posture cards */}
      <div className="grid gap-4 lg:grid-cols-4">
        <Panel title="Program Identity" icon={ShieldCheck} className="lg:col-span-2">
          <div className="grid gap-x-6 sm:grid-cols-2">
            <div>
              <IdentityRow label="App" value={PROGRAM.appName} tone="text-primary" />
              <IdentityRow label="Program ID" value={PROGRAM.programId} />
              <IdentityRow label="Federation Role" value={PROGRAM.federationRole} />
              <IdentityRow label="Jurisdiction" value={PROGRAM.jurisdiction} />
            </div>
            <div>
              <IdentityRow label="Parent Hub" value={PROGRAM.parentHub} />
              <IdentityRow label="Active Vector" value="AIRCRAFT_INTEL" tone="text-primary" />
              <IdentityRow label="Discovery" value="READY" tone="text-[hsl(142_70%_58%)]" />
              <IdentityRow label="Live Execution" value="BLOCKED" tone="text-[hsl(4_90%_66%)]" />
            </div>
          </div>
        </Panel>

        <div className="rounded-xl border border-[hsl(38_100%_50%/0.25)] bg-[hsl(38_100%_50%/0.06)] p-4">
          <div className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-[hsl(38_100%_62%)]" />
            <p className="text-xs font-bold uppercase tracking-wide text-[hsl(38_100%_64%)]">Production Status</p>
          </div>
          <p className="mt-2 font-mono text-sm font-bold text-[hsl(38_100%_64%)]">{PROGRAM.productionStatus}</p>
          <p className="mt-1 text-[11px] text-muted-foreground">Data mode: {PROGRAM.dataMode}</p>
        </div>

        <div className="grid gap-3">
          <div className="rounded-xl border border-[hsl(142_70%_45%/0.25)] bg-[hsl(142_70%_45%/0.06)] p-3">
            <div className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-[hsl(142_70%_58%)]" /><p className="text-[11px] font-bold uppercase tracking-wide text-[hsl(142_70%_60%)]">Hub Discovery</p></div>
            <p className="mt-1 font-mono text-sm font-bold text-[hsl(142_70%_60%)]">READY</p>
          </div>
          <div className="rounded-xl border border-[hsl(4_90%_58%/0.25)] bg-[hsl(4_90%_58%/0.06)] p-3">
            <div className="flex items-center gap-2"><XCircle className="h-4 w-4 text-[hsl(4_90%_66%)]" /><p className="text-[11px] font-bold uppercase tracking-wide text-[hsl(4_90%_66%)]">Hub Live Execution</p></div>
            <p className="mt-1 font-mono text-sm font-bold text-[hsl(4_90%_66%)]">BLOCKED</p>
          </div>
        </div>
      </div>

      {/* Metrics */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Total Observations" value={m.totalObservations} icon={Plane} accent="primary" sub={`${m.highConfidence} high-confidence`} />
        <MetricCard label="Aircraft Profiles" value={m.aircraftCount} icon={IdCard} accent="info" />
        <MetricCard label="FR24 Captures" value={m.captureCount} icon={Camera} accent="info" />
        <MetricCard label="Manual Review Backlog" value={m.manualReviewBacklog} icon={ClipboardCheck} accent="warn" />
        <MetricCard label="Synthetic Observations" value={m.syntheticObservations} icon={FlaskConical} accent="synthetic" sub="all records diagnostic" />
        <MetricCard label="Verified Observations" value={m.verifiedObservations} icon={CheckCircle2} accent="ready" />
        <MetricCard label="Needs Review / Low Conf" value={`${m.needsReviewCount} / ${m.lowConfidence}`} icon={AlertTriangle} accent="warn" />
        <MetricCard label="Blocked Exports" value={`${m.blockedExportCount} blk · ${m.productionEligibleExports} prod`} icon={Share2} accent="blocked" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Map */}
        <div className="lg:col-span-2">
          <PuertoRicoMapShell
            observations={d.observations}
            airports={d.airports}
            assets={d.assets}
            routes={d.routes}
            height={320}
            title="Observation & Infrastructure Context"
          />
        </div>

        {/* Blockers */}
        <Panel title="Top Blockers" icon={AlertTriangle}>
          <BlockerList title={null} blockers={latestReadiness?.blockers || []} warnings={latestReadiness?.warnings || []} />
        </Panel>
      </div>

      {/* Hourly observation pattern chart */}
      <HourlyObservationsChart observations={d.observations} />

      {/* Observation density heat map */}
      <ObservationHeatMap
        observations={d.observations}
        airportById={airportById}
        assetById={assetById}
        height={300}
      />

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Recent observations */}
        <Panel title="Recent Observations" icon={Plane} className="lg:col-span-2" bodyClassName="p-0">
          <div className="overflow-x-auto scrollbar-thin">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                  <th className="px-4 py-2 font-semibold">Callsign</th>
                  <th className="px-4 py-2 font-semibold">Mission</th>
                  <th className="px-4 py-2 font-semibold">Nearest</th>
                  <th className="px-4 py-2 font-semibold">Conf</th>
                  <th className="px-4 py-2 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {recentObs.map((o) => {
                  const rs = REVIEW_STATUS[o.review_status] || REVIEW_STATUS.new;
                  return (
                    <tr key={o.id} onClick={() => open.observation(o.observation_id)} className="cursor-pointer border-b border-border/50 transition hover:bg-secondary/50">
                      <td className="px-4 py-2.5"><span className="font-mono font-semibold text-foreground">{o.callsign}</span><div className="mt-0.5"><SyntheticDataBadge synthetic={o.synthetic_flag} /></div></td>
                      <td className="px-4 py-2.5 text-muted-foreground">{o.mission_inference}</td>
                      <td className="px-4 py-2.5 text-muted-foreground">{o.nearest_airport_name?.split(" ")[0]}</td>
                      <td className="px-4 py-2.5"><ConfidenceBadge score={o.confidence_score} showBar={false} /></td>
                      <td className="px-4 py-2.5"><StatusChip tone={rs.tone} label={rs.label} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>

        {/* Recent reviews */}
        <Panel title="Manual Review Items" icon={ClipboardCheck}>
          <div className="space-y-2">
            {recentReviews.length ? recentReviews.map((r) => (
              <ManualReviewPanel key={r.id} item={r} onOpen={() => open.review(r.review_id)} />
            )) : <p className="text-xs text-muted-foreground">No open review items.</p>}
          </div>
        </Panel>
      </div>

      {/* Federation sync events */}
      <Panel title="Recent Federation Sync Events" icon={Network} bodyClassName="p-0">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                <th className="px-4 py-2 font-semibold">Type</th>
                <th className="px-4 py-2 font-semibold">Status</th>
                <th className="px-4 py-2 font-semibold">Command Reference</th>
                <th className="px-4 py-2 font-semibold">Result</th>
              </tr>
            </thead>
            <tbody>
              {recentSyncs.map((s) => {
                const ss = SYNC_STATUS[s.status] || SYNC_STATUS.queued;
                return (
                  <tr key={s.id} className="border-b border-border/50">
                    <td className="px-4 py-2.5"><span className="flex items-center gap-1.5 text-foreground/90"><Activity className="h-3 w-3 text-primary" />{s.sync_type}</span></td>
                    <td className="px-4 py-2.5"><StatusChip tone={ss.tone} label={ss.label} /></td>
                    <td className="px-4 py-2.5"><code className="font-mono text-[10px] text-muted-foreground">{s.command_reference}</code></td>
                    <td className="px-4 py-2.5 text-muted-foreground">{s.result_summary}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}