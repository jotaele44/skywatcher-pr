import React from "react";
import { FlaskConical } from "lucide-react";

export default function SyntheticDataBadge({ synthetic = true, className = "" }) {
  if (!synthetic) {
    return (
      <span className={`inline-flex items-center gap-1 rounded-full border border-[hsl(142_70%_45%/0.3)] bg-[hsl(142_70%_45%/0.1)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[hsl(142_70%_60%)] ${className}`}>
        Live
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border border-[hsl(262_52%_60%/0.35)] bg-[hsl(262_52%_60%/0.14)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[hsl(262_60%_76%)] ${className}`}
      title="Synthetic / sample diagnostic record"
    >
      <FlaskConical className="w-2.5 h-2.5" />
      Synthetic
    </span>
  );
}