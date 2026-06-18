import React from "react";

const TONES = {
  ready: "bg-[hsl(142_70%_45%/0.12)] text-[hsl(142_70%_60%)] border-[hsl(142_70%_45%/0.3)]",
  warn: "bg-[hsl(38_100%_50%/0.12)] text-[hsl(38_100%_62%)] border-[hsl(38_100%_50%/0.3)]",
  blocked: "bg-[hsl(4_90%_58%/0.12)] text-[hsl(4_90%_68%)] border-[hsl(4_90%_58%/0.3)]",
  synthetic: "bg-[hsl(262_52%_60%/0.14)] text-[hsl(262_60%_75%)] border-[hsl(262_52%_60%/0.35)]",
  info: "bg-[hsl(218_100%_56%/0.12)] text-[hsl(200_100%_72%)] border-[hsl(218_100%_56%/0.3)]",
  primary: "bg-[hsl(190_100%_50%/0.12)] text-[hsl(190_100%_70%)] border-[hsl(190_100%_50%/0.3)]",
  muted: "bg-secondary text-muted-foreground border-border",
};

export default function StatusChip({ tone = "muted", label, icon: Icon, className = "" }) {
  const cls = TONES[tone] || TONES.muted;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide whitespace-nowrap ${cls} ${className}`}
    >
      {Icon && <Icon className="w-3 h-3" />}
      {label}
    </span>
  );
}