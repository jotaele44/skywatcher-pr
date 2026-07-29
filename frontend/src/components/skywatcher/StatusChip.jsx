import React from "react";
import { federationTone } from "@pr-federation/react";

// Map this app's status tones onto the canonical federation status vocabulary
// (see @pr-federation/react + federation.css). Colors now come from the shared
// design system's `.fd-status` tokens instead of hard-coded HSL literals.
const TONE_ROLE = {
  ready: "success",
  warn: "warning",
  blocked: "danger",
  synthetic: "process",
  info: "info",
  primary: "tier",
  muted: "neutral",
};

export default function StatusChip({ tone = "muted", label, icon: Icon, className = "" }) {
  const { className: fdClass, ...toneAttrs } = federationTone(TONE_ROLE[tone] || "neutral");
  return (
    <span
      className={`${fdClass} gap-1.5 text-[11px] uppercase tracking-wide whitespace-nowrap ${className}`}
      {...toneAttrs}
    >
      {Icon && <Icon className="w-3 h-3" />}
      {label}
    </span>
  );
}