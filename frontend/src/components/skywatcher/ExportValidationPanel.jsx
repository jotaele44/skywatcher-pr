import React from "react";
import { ShieldCheck, ShieldX, FlaskConical, FileWarning } from "lucide-react";
import StatusChip from "./StatusChip";
import { EXPORT_STATUS } from "@/lib/skywatcher";

export default function ExportValidationPanel({ pkg }) {
  if (!pkg) return null;
  const es = EXPORT_STATUS[pkg.export_status] || EXPORT_STATUS.draft;
  // Enforced rule: production + synthetic rows => not eligible / blocked
  const synthProductionBlocked = pkg.export_mode === "production" && pkg.contains_synthetic_rows;
  const eligible = pkg.production_eligible && !synthProductionBlocked;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusChip tone={pkg.export_mode === "production" ? "info" : "primary"} label={`${pkg.export_mode} mode`} />
        <StatusChip tone={es.tone} label={es.label} />
        <StatusChip tone={pkg.schema_valid ? "ready" : "blocked"} label={pkg.schema_valid ? "Schema Valid" : "Schema Invalid"} icon={pkg.schema_valid ? ShieldCheck : ShieldX} />
        {pkg.contains_synthetic_rows && <StatusChip tone="synthetic" label="Synthetic Rows" icon={FlaskConical} />}
        <StatusChip tone={eligible ? "ready" : "blocked"} label={eligible ? "Production Eligible" : "Not Production Eligible"} />
      </div>

      <div className="grid grid-cols-3 gap-2">
        {[
          { label: "Observations", value: pkg.observation_count },
          { label: "Sources", value: pkg.source_count },
          { label: "Relationships", value: pkg.relationship_count },
        ].map((m) => (
          <div key={m.label} className="rounded-lg border border-border bg-card p-2.5 text-center">
            <p className="text-lg font-bold font-mono text-foreground tabular-nums">{m.value ?? 0}</p>
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{m.label}</p>
          </div>
        ))}
      </div>

      <div
        className={`flex items-start gap-2 rounded-lg border px-3 py-2.5 ${
          synthProductionBlocked || pkg.export_status === "blocked"
            ? "border-[hsl(4_90%_58%/0.3)] bg-[hsl(4_90%_58%/0.06)]"
            : "border-border bg-card"
        }`}
      >
        <FileWarning className={`mt-0.5 h-4 w-4 shrink-0 ${synthProductionBlocked ? "text-[hsl(4_90%_66%)]" : "text-muted-foreground"}`} />
        <div>
          <p className="text-xs font-semibold text-foreground/90">Validation Message</p>
          <p className="mt-0.5 text-xs text-muted-foreground leading-snug">{pkg.validation_message}</p>
          {synthProductionBlocked && (
            <p className="mt-1.5 text-[11px] font-semibold text-[hsl(4_90%_68%)]">
              Hard rule: production export is blocked when a package contains synthetic rows.
            </p>
          )}
        </div>
      </div>

      <div className="rounded-lg border border-border bg-[hsl(220_30%_4%)] px-3 py-2">
        <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Export Path</p>
        <code className="font-mono text-xs text-foreground/80">{pkg.export_path || "—"}</code>
      </div>
    </div>
  );
}