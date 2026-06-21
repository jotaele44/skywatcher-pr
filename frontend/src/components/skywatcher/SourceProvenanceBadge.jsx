import React from "react";
import { FileSearch } from "lucide-react";

const SOURCE_LABELS = {
  fr24_screenshot: "FR24 Screenshot",
  fr24_track: "FR24 Track",
  manual_entry: "Manual Entry",
  registry_match: "Registry Match",
  synthetic_example: "Synthetic Example",
  ILAP: "ILAP Bridge",
  AASB: "AASB Bridge",
  manual: "Manual Bridge",
};

export default function SourceProvenanceBadge({ source, className = "" }) {
  const label = SOURCE_LABELS[source] || source || "Unknown";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border border-border bg-secondary/60 px-2 py-0.5 text-[10px] font-medium tracking-wide text-muted-foreground ${className}`}
      title={`Provenance: ${label}`}
    >
      <FileSearch className="w-2.5 h-2.5 text-primary" />
      {label}
    </span>
  );
}