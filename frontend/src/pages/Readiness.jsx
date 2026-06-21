import React from "react";
import { GaugeCircle, ListChecks, AlertTriangle } from "lucide-react";
import { useSkywatcher } from "@/lib/SkywatcherData";
import PageHeader from "@/components/skywatcher/PageHeader";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import Panel from "@/components/skywatcher/Panel";
import ReadinessCard from "@/components/skywatcher/ReadinessCard";
import BlockerList from "@/components/skywatcher/BlockerList";
import LoadingState from "@/components/skywatcher/LoadingState";

const READINESS_ITEMS = [
  { title: "Ready for Hub discovery", description: "Node registered on Hub discovery surface as airspace_intelligence_node.", state: "ready", value: "Yes" },
  { title: "Ready for Hub live execution", description: "Live execution blocked until non-synthetic observations and validated production export exist.", state: "blocked", value: "No" },
  { title: "Live observations", description: "No non-synthetic observations loaded. Dataset is synthetic/diagnostic only.", state: "blocked", value: "Missing" },
  { title: "Synthetic example package", description: "Synthetic airspace example package present and valid in test mode.", state: "ready", value: "Present" },
  { title: "Canonical export adapter", description: "Canonical federation export adapter operates in test-mode only.", state: "pending", value: "Test-mode only" },
  { title: "FR24 ingest", description: "FR24 ingest is repository-side and requires local screenshots / track inputs.", state: "pending", value: "Repository-side" },
  { title: "GEBCO terrain layer", description: "GEBCO terrain processing is optional and deferred for this node.", state: "deferred", value: "Optional / Deferred" },
  { title: "RAG / EarthGPT", description: "Retrieval-augmented and EarthGPT modules are deferred.", state: "deferred", value: "Deferred" },
  { title: "Satellite ingest", description: "Satellite ingestion pipeline is deferred.", state: "deferred", value: "Deferred" },
  { title: "Mission / operational-intelligence modules", description: "Mission and operational-intelligence modules are deferred.", state: "deferred", value: "Deferred" },
  { title: "ILAP intake external data gap", description: "ILAP intake requires local FR24 screenshots / tracks to close the external data gap.", state: "pending", value: "Data gap" },
];

const NEXT_ACTIONS = [
  "Load non-synthetic observations",
  "Resolve manual review queue",
  "Validate export package",
  "Generate canonical federation export",
  "Sync with Hub discovery surface",
  "Only then reassess live execution readiness",
];

export default function Readiness() {
  const d = useSkywatcher();
  if (d.loading) return <LoadingState />;

  const latest = [...d.readiness].sort((a, b) => new Date(b.report_date) - new Date(a.report_date))[0];

  return (
    <div className="space-y-5">
      <PageHeader title="Readiness / Blockers" subtitle="Readiness intelligence for Hub discovery & live execution" icon={GaugeCircle} />
      <DiagnosticNoticeBanner />

      <div className="grid gap-3 lg:grid-cols-2">
        {READINESS_ITEMS.map((item) => <ReadinessCard key={item.title} {...item} />)}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Active Blockers & Warnings" icon={AlertTriangle}>
          <BlockerList title={null} blockers={latest?.blockers || []} warnings={latest?.warnings || []} />
        </Panel>

        <Panel title="Recommended Next Actions" icon={ListChecks}>
          <ol className="space-y-2">
            {NEXT_ACTIONS.map((a, i) => (
              <li key={i} className="flex items-start gap-3 rounded-lg border border-border bg-card px-3 py-2.5">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/15 font-mono text-xs font-bold text-primary">{i + 1}</span>
                <span className="text-sm text-foreground/90">{a}</span>
              </li>
            ))}
          </ol>
          <p className="mt-3 rounded-lg border border-[hsl(38_100%_50%/0.2)] bg-[hsl(38_100%_50%/0.05)] px-3 py-2 text-[11px] text-muted-foreground">
            Live execution remains blocked by design until each action above is complete and verified.
          </p>
        </Panel>
      </div>
    </div>
  );
}