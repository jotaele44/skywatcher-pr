import React from "react";
import { Share2, FileWarning } from "lucide-react";
import SideDrawer, { Field, Section } from "../SideDrawer";
import SyntheticDataBadge from "../SyntheticDataBadge";
import ExportValidationPanel from "../ExportValidationPanel";
import { useResolvers, useSkywatcher } from "@/lib/SkywatcherData";

export default function ExportDetailDrawer({ id, onClose }) {
  const d = useSkywatcher();
  const r = useResolvers();
  const pkg = d.exports.find((e) => e.id === id) || d.exports.find((e) => e.package_id === id);
  if (!pkg) return <SideDrawer open onClose={onClose} title="Export package not found" />;

  const synthProductionBlocked = pkg.export_mode === "production" && pkg.contains_synthetic_rows;

  return (
    <SideDrawer
      open
      onClose={onClose}
      title={pkg.package_name}
      subtitle={`${pkg.package_id} · ${pkg.export_mode} mode`}
      badges={<SyntheticDataBadge synthetic={pkg.synthetic_flag} />}
    >
      <Section title="Validation & Eligibility" icon={Share2}>
        <ExportValidationPanel pkg={pkg} />
      </Section>

      <Section title="Blocker Explanation" icon={FileWarning}>
        {synthProductionBlocked ? (
          <div className="rounded-lg border border-[hsl(4_90%_58%/0.3)] bg-[hsl(4_90%_58%/0.06)] px-3 py-3 text-sm text-[hsl(4_90%_72%)]">
            This package is in <strong>production</strong> mode but contains synthetic rows. Production export
            is blocked until all synthetic example rows are replaced with non-synthetic observations.
            Production eligibility remains <strong>false</strong>.
          </div>
        ) : pkg.export_status === "blocked" ? (
          <div className="rounded-lg border border-[hsl(4_90%_58%/0.3)] bg-[hsl(4_90%_58%/0.06)] px-3 py-3 text-sm text-[hsl(4_90%_72%)]">
            {pkg.validation_message}
          </div>
        ) : (
          <div className="rounded-lg border border-border bg-card px-3 py-3 text-sm text-muted-foreground">
            No blocking conditions for this package in its current mode. {pkg.export_mode === "test" ? "Test-mode packages may contain synthetic rows by design." : ""}
          </div>
        )}
        <div className="mt-2">
          <Field label="Created At">{pkg.created_at ? new Date(pkg.created_at).toLocaleString() : "—"}</Field>
        </div>
      </Section>
    </SideDrawer>
  );
}