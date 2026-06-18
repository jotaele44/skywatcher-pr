import React from "react";
import { Share2, Terminal, AlertOctagon } from "lucide-react";
import { useSkywatcher } from "@/lib/SkywatcherData";
import { useDrawers } from "@/components/skywatcher/drawers/DrawerHub";
import PageHeader from "@/components/skywatcher/PageHeader";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import Panel from "@/components/skywatcher/Panel";
import StatusChip from "@/components/skywatcher/StatusChip";
import SyntheticDataBadge from "@/components/skywatcher/SyntheticDataBadge";
import ExportValidationPanel from "@/components/skywatcher/ExportValidationPanel";
import CommandReferenceCard from "@/components/skywatcher/CommandReferenceCard";
import LoadingState from "@/components/skywatcher/LoadingState";
import { REPO_COMMANDS, EXPORT_STATUS } from "@/lib/skywatcher";

export default function ExportCenter() {
  const d = useSkywatcher();
  const { open } = useDrawers();
  if (d.loading) return <LoadingState />;

  return (
    <div className="space-y-5">
      <PageHeader title="Federation Export Center" subtitle="Export validation & Hub readiness — test vs production mode" icon={Share2} />
      <DiagnosticNoticeBanner />

      <div className="flex items-start gap-3 rounded-lg border border-[hsl(4_90%_58%/0.28)] bg-[hsl(4_90%_58%/0.06)] px-4 py-3">
        <AlertOctagon className="mt-0.5 h-5 w-5 shrink-0 text-[hsl(4_90%_66%)]" />
        <p className="text-sm text-foreground/85">
          <strong className="text-[hsl(4_90%_72%)]">Hard rule:</strong> production export is blocked when a package contains synthetic rows.
          All current packages are diagnostic — production eligibility remains <strong>blocked</strong> until non-synthetic observations exist.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {d.exports.map((pkg) => {
          const es = EXPORT_STATUS[pkg.export_status] || EXPORT_STATUS.draft;
          return (
            <Panel
              key={pkg.id}
              title={pkg.package_name}
              icon={Share2}
              action={
                <button onClick={() => open.export(pkg.package_id)} className="text-[10px] font-semibold uppercase tracking-wide text-primary hover:underline">Details →</button>
              }
            >
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <StatusChip tone={pkg.export_mode === "production" ? "info" : "primary"} label={`${pkg.export_mode} mode`} />
                <StatusChip tone={es.tone} label={es.label} />
                <SyntheticDataBadge synthetic={pkg.synthetic_flag} />
              </div>
              <ExportValidationPanel pkg={pkg} />
            </Panel>
          );
        })}
      </div>

      <Panel title="Read-Only Repository Command References" icon={Terminal}>
        <p className="mb-3 text-xs text-muted-foreground">
          These are copyable references to repository-side commands. They do not execute here — Federation is a visualization & validation surface only.
        </p>
        <div className="space-y-2">
          {REPO_COMMANDS.map((cmd, i) => (
            <CommandReferenceCard key={i} command={cmd} />
          ))}
        </div>
      </Panel>
    </div>
  );
}