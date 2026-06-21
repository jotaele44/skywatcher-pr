import React, { useMemo } from "react";
import { ClipboardCheck } from "lucide-react";
import { useSkywatcher } from "@/lib/SkywatcherData";
import { useDrawers } from "@/components/skywatcher/drawers/DrawerHub";
import PageHeader from "@/components/skywatcher/PageHeader";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import MetricCard from "@/components/skywatcher/MetricCard";
import ManualReviewPanel from "@/components/skywatcher/ManualReviewPanel";
import LoadingState from "@/components/skywatcher/LoadingState";

const COLUMNS = [
  { key: "open", label: "Open", accent: "warn" },
  { key: "in_review", label: "In Review", accent: "info" },
  { key: "resolved", label: "Resolved", accent: "ready" },
  { key: "rejected", label: "Rejected", accent: "blocked" },
];

export default function ManualReview() {
  const d = useSkywatcher();
  const { open } = useDrawers();

  const grouped = useMemo(() => {
    const g = { open: [], in_review: [], resolved: [], rejected: [] };
    d.reviews.forEach((r) => { (g[r.review_status] || g.open).push(r); });
    return g;
  }, [d.reviews]);

  if (d.loading) return <LoadingState />;

  const backlog = grouped.open.length + grouped.in_review.length;
  const high = d.reviews.filter((r) => r.severity === "high" && (r.review_status === "open" || r.review_status === "in_review")).length;

  return (
    <div className="space-y-5">
      <PageHeader title="Manual Review Queue" subtitle="Human-in-the-loop review of diagnostic records" icon={ClipboardCheck} />
      <DiagnosticNoticeBanner />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Review Backlog" value={backlog} accent="warn" sub="open + in review" />
        <MetricCard label="High Severity Open" value={high} accent="blocked" />
        <MetricCard label="Resolved" value={grouped.resolved.length} accent="ready" />
        <MetricCard label="Rejected" value={grouped.rejected.length} accent="muted" />
      </div>

      <div className="grid gap-4 lg:grid-cols-4">
        {COLUMNS.map((col) => (
          <div key={col.key} className="flex flex-col">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-bold uppercase tracking-wider text-foreground/80">{col.label}</h3>
              <span className="rounded-full border border-border bg-secondary px-2 py-0.5 text-[10px] font-mono text-muted-foreground">{grouped[col.key].length}</span>
            </div>
            <div className="flex-1 space-y-2 rounded-xl border border-dashed border-border bg-card/30 p-2">
              {grouped[col.key].length ? grouped[col.key].map((r) => (
                <ManualReviewPanel key={r.id} item={r} onOpen={() => open.review(r.review_id)} />
              )) : <p className="px-2 py-6 text-center text-[11px] text-muted-foreground">No items</p>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}