import React, { useState, useMemo } from "react";
import { Camera, Info, AlertTriangle } from "lucide-react";
import { useSkywatcher } from "@/lib/SkywatcherData";
import { useDrawers } from "@/components/skywatcher/drawers/DrawerHub";
import PageHeader from "@/components/skywatcher/PageHeader";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import Panel from "@/components/skywatcher/Panel";
import StatusChip from "@/components/skywatcher/StatusChip";
import SyntheticDataBadge from "@/components/skywatcher/SyntheticDataBadge";
import EmptyState from "@/components/skywatcher/EmptyState";
import LoadingState from "@/components/skywatcher/LoadingState";
import { Toolbar, SearchInput, FilterSelect } from "@/components/skywatcher/Toolbar";
import { INGEST_STATUS } from "@/lib/skywatcher";

const INGEST_OPTS = [
  { value: "all", label: "All ingest states" },
  { value: "queued", label: "Queued" }, { value: "processed", label: "Processed" },
  { value: "needs_manual_review", label: "Needs Manual Review" }, { value: "duplicate", label: "Duplicate" },
  { value: "corrupt", label: "Corrupt" }, { value: "rejected", label: "Rejected" },
];

export default function FR24Intake() {
  const d = useSkywatcher();
  const { open } = useDrawers();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");

  const filtered = useMemo(() => {
    let rows = [...d.captures];
    if (q) { const s = q.toLowerCase(); rows = rows.filter((c) => [c.file_name, c.capture_id, c.sha256_hash].filter(Boolean).some((v) => v.toLowerCase().includes(s))); }
    if (status !== "all") rows = rows.filter((c) => c.ingest_status === status);
    return rows.sort((a, b) => new Date(b.captured_at) - new Date(a.captured_at));
  }, [d.captures, q, status]);

  if (d.loading) return <LoadingState />;

  return (
    <div className="space-y-5">
      <PageHeader title="FR24 Intake" subtitle="Repository-side capture metadata & review state — visualization only" icon={Camera} />
      <DiagnosticNoticeBanner />

      <div className="flex items-start gap-3 rounded-lg border border-[hsl(218_100%_56%/0.25)] bg-[hsl(218_100%_56%/0.06)] px-4 py-3">
        <Info className="mt-0.5 h-5 w-5 shrink-0 text-[hsl(200_100%_72%)]" />
        <p className="text-sm text-foreground/85">
          <strong>FR24 ingest is repository-side.</strong> Federation only visualizes capture metadata and review state.
          No scraping, OCR, or live ingestion runs here — capture actions update diagnostic state only.
        </p>
      </div>

      <Panel bodyClassName="space-y-4">
        <Toolbar>
          <SearchInput value={q} onChange={setQ} placeholder="Search file name, capture id, hash…" />
          <FilterSelect value={status} onChange={setStatus} options={INGEST_OPTS} label="Ingest status" />
        </Toolbar>

        {filtered.length === 0 ? (
          <EmptyState icon={Camera} title="No captures in queue" />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border scrollbar-thin">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2 font-semibold">File</th>
                  <th className="px-3 py-2 font-semibold">Type</th>
                  <th className="px-3 py-2 font-semibold">Ingest Status</th>
                  <th className="px-3 py-2 font-semibold">OCR</th>
                  <th className="px-3 py-2 font-semibold">Route</th>
                  <th className="px-3 py-2 font-semibold">Obs</th>
                  <th className="px-3 py-2 font-semibold">Review</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => {
                  const is = INGEST_STATUS[c.ingest_status] || INGEST_STATUS.queued;
                  return (
                    <tr key={c.id} onClick={() => open.capture(c.capture_id)} className="cursor-pointer border-b border-border/50 transition hover:bg-secondary/40">
                      <td className="px-3 py-2.5"><div className="font-mono text-xs font-semibold text-foreground">{c.file_name}</div><div className="mt-0.5"><SyntheticDataBadge synthetic={c.synthetic_flag} /></div></td>
                      <td className="px-3 py-2.5 text-muted-foreground">{c.capture_type}</td>
                      <td className="px-3 py-2.5"><StatusChip tone={is.tone} label={is.label} /></td>
                      <td className="px-3 py-2.5"><QualityCell score={c.ocr_quality_score} /></td>
                      <td className="px-3 py-2.5"><QualityCell score={c.route_quality_score} /></td>
                      <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{c.linked_observation_count ?? 0}</td>
                      <td className="px-3 py-2.5">{c.manual_review_required ? <span className="flex items-center gap-1 text-[10px] font-semibold text-[hsl(38_100%_62%)]"><AlertTriangle className="h-3 w-3" /> Required</span> : <span className="text-[10px] text-muted-foreground">—</span>}</td>
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

function QualityCell({ score }) {
  const pct = score == null ? 0 : Math.round(score * 100);
  const color = pct >= 75 ? "hsl(142 70% 55%)" : pct >= 50 ? "hsl(38 100% 56%)" : "hsl(4 90% 62%)";
  return (
    <div className="flex items-center gap-1.5">
      <span className="font-mono text-xs font-semibold" style={{ color }}>{pct}%</span>
      <div className="h-1.5 w-8 overflow-hidden rounded-full bg-secondary"><div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} /></div>
    </div>
  );
}