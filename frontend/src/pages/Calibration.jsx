import React, { useEffect, useMemo, useState } from "react";
import { ScanSearch, Layers, AlertTriangle, Plane, Sigma } from "lucide-react";
import PageHeader from "@/components/skywatcher/PageHeader";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import Panel from "@/components/skywatcher/Panel";
import MetricCard from "@/components/skywatcher/MetricCard";
import StatusChip from "@/components/skywatcher/StatusChip";
import ConfidenceBadge from "@/components/skywatcher/ConfidenceBadge";
import EmptyState from "@/components/skywatcher/EmptyState";
import LoadingState from "@/components/skywatcher/LoadingState";

// Static calibration summary produced by the backend
// (`scripts/satim_score_labels.py --frontend-out`). The view is intentionally
// decoupled from the federation `/api` client: it reads a committed artifact so
// it renders with no backend.
const SUMMARY_URL = `${import.meta.env.BASE_URL}satim/moca_fr24_2025.summary.json`;

const DECISION = {
  candidate: { tone: "ready", label: "Candidate" },
  cross_source_required: { tone: "info", label: "Cross-source" },
  review: { tone: "warn", label: "Review" },
  suppressed: { tone: "muted", label: "Suppressed" },
};

const DECISION_ORDER = ["candidate", "cross_source_required", "review", "suppressed"];

function ScoreBar({ label, score, accent }) {
  const pct = score == null ? 0 : Math.round(score * 100);
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[11px]">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono font-semibold" style={{ color: accent }}>{pct}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: accent }} />
      </div>
    </div>
  );
}

export default function Calibration() {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetch(SUMMARY_URL)
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load calibration summary (${res.status})`);
        return res.json();
      })
      .then((data) => { if (active) { setSummary(data); setLoading(false); } })
      .catch((err) => { if (active) { setError(err.message); setLoading(false); } });
    return () => { active = false; };
  }, []);

  const decisionCounts = summary?.decision_breakdown || {};
  const aircraft = summary?.aircraft || {};
  const labels = useMemo(() => summary?.labels || [], [summary]);

  if (loading) return <LoadingState label="Loading SATIM calibration…" />;

  if (error || !summary) {
    return (
      <div className="space-y-5">
        <PageHeader title="SATIM Calibration" subtitle="Visual-analysis false-positive calibration" icon={ScanSearch} />
        <EmptyState
          icon={ScanSearch}
          title="No calibration summary"
          message={error || "Run scripts/satim_score_labels.py --frontend-out to generate the static summary."}
        />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="SATIM Calibration"
        subtitle={`${summary.calibration_id} · ${summary.evidence_tier}`}
        icon={ScanSearch}
        actions={
          <div className="flex items-center gap-2">
            <StatusChip tone="primary" icon={Plane} label={aircraft.primary_label || "—"} />
            <StatusChip tone="synthetic" label={summary.evidence_tier?.startsWith("T2") ? "T2 screenshot" : summary.evidence_tier} />
          </div>
        }
      />
      <DiagnosticNoticeBanner />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Marked labels" value={summary.counts?.labels ?? 0} sub={`${summary.counts?.frames ?? 0} frames`} icon={ScanSearch} accent="primary" />
        <MetricCard label="Mean adjusted" value={`${Math.round((summary.score_summary?.mean_adjusted ?? 0) * 100)}%`} sub={`raw ${Math.round((summary.score_summary?.mean_raw ?? 0) * 100)}%`} icon={Sigma} accent="info" />
        <MetricCard label="Suppressed" value={decisionCounts.suppressed ?? 0} sub="below review band" icon={Layers} accent="blocked" />
        <MetricCard label="In review" value={(decisionCounts.review ?? 0) + (decisionCounts.cross_source_required ?? 0) + (decisionCounts.candidate ?? 0)} sub="review or higher" icon={Layers} accent="warn" />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Score Summary" icon={Sigma} bodyClassName="space-y-3">
          <ScoreBar label="Mean raw confidence" score={summary.score_summary?.mean_raw} accent="hsl(190 100% 50%)" />
          <ScoreBar label="Mean adjusted (after suppression)" score={summary.score_summary?.mean_adjusted} accent="hsl(38 100% 54%)" />
          <div className="flex flex-wrap gap-2 pt-1 text-[10px] text-muted-foreground">
            <span className="rounded border border-border px-2 py-0.5">min adj {Math.round((summary.score_summary?.min_adjusted ?? 0) * 100)}%</span>
            <span className="rounded border border-border px-2 py-0.5">max adj {Math.round((summary.score_summary?.max_adjusted ?? 0) * 100)}%</span>
            <span className="rounded border border-border px-2 py-0.5">promote ≥ {Math.round((summary.promotion_thresholds?.promote_to_candidate ?? 0.8) * 100)}%</span>
          </div>
        </Panel>

        <Panel title="Promotion Decisions" icon={Layers} bodyClassName="space-y-3">
          <div className="flex flex-wrap gap-2">
            {DECISION_ORDER.map((key) => (
              <StatusChip key={key} tone={DECISION[key].tone} label={`${DECISION[key].label} · ${decisionCounts[key] ?? 0}`} />
            ))}
          </div>
          {(summary.warnings || []).length > 0 && (
            <div className="space-y-2 rounded-lg border border-[hsl(38_100%_50%/0.25)] bg-[hsl(38_100%_50%/0.06)] p-3">
              {summary.warnings.map((w, i) => (
                <div key={i} className="flex items-start gap-2 text-[11px] text-[hsl(38_100%_64%)]">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span>{w}</span>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <Panel title="Marked Features" icon={ScanSearch} bodyClassName="space-y-0">
        {labels.length === 0 ? (
          <EmptyState icon={ScanSearch} title="No marked features" />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border scrollbar-thin">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2 font-semibold">Frame</th>
                  <th className="px-3 py-2 font-semibold">Marker</th>
                  <th className="px-3 py-2 font-semibold">Feature class</th>
                  <th className="px-3 py-2 font-semibold">FP class</th>
                  <th className="px-3 py-2 font-semibold">Raw → Adjusted</th>
                  <th className="px-3 py-2 font-semibold">Decision</th>
                </tr>
              </thead>
              <tbody>
                {labels.map((row, i) => {
                  const dec = DECISION[row.decision] || DECISION.suppressed;
                  return (
                    <tr key={`${row.image_id}-${i}`} className="border-b border-border/50 transition hover:bg-secondary/40">
                      <td className="px-3 py-2.5 font-mono text-[11px] text-muted-foreground">{row.frame}</td>
                      <td className="px-3 py-2.5 text-xs text-foreground">{row.marker_type}</td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground">{row.feature_class}</td>
                      <td className="px-3 py-2.5">
                        <span className="font-mono text-[11px] text-foreground">{row.false_positive_class}</span>
                        {row.unknown_false_positive_class && (
                          <span className="ml-1.5 inline-flex items-center rounded border border-[hsl(38_100%_50%/0.3)] px-1 py-0.5 text-[9px] font-semibold uppercase text-[hsl(38_100%_64%)]" title="Not a canonical scoring class — no adjustment applied">
                            non-canonical
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[11px] text-muted-foreground">{Math.round(row.raw_confidence * 100)}%</span>
                          <span className="text-muted-foreground">→</span>
                          <ConfidenceBadge score={row.adjusted_score} showBar={false} />
                        </div>
                      </td>
                      <td className="px-3 py-2.5"><StatusChip tone={dec.tone} label={dec.label} /></td>
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
