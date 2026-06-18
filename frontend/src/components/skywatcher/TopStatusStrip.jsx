import React from "react";
import { Satellite, MapPin, Network, CheckCircle2, XCircle, FlaskConical } from "lucide-react";
import { PROGRAM } from "@/lib/skywatcher";

const TONE = {
  ready: "text-[hsl(142_70%_58%)]",
  blocked: "text-[hsl(4_90%_66%)]",
  synthetic: "text-[hsl(262_60%_76%)]",
  primary: "text-primary",
  default: "text-foreground",
};

const CELLS = [
  { icon: Satellite, value: PROGRAM.appName, tone: "primary" },
  { value: PROGRAM.programId },
  { icon: MapPin, value: PROGRAM.jurisdiction },
  { icon: Network, label: "Hub", value: PROGRAM.parentHub },
  { icon: CheckCircle2, label: "Discovery", value: "Ready", tone: "ready" },
  { icon: XCircle, label: "Live Exec", value: "Blocked", tone: "blocked" },
  { icon: FlaskConical, label: "Data Mode", value: "Diagnostic / Synthetic until replaced", tone: "synthetic" },
];

function Cell({ icon: Icon, label, value, tone = "default" }) {
  const toneColor = TONE[tone] || TONE.default;
  return (
    <div className="flex items-center gap-1.5 whitespace-nowrap">
      {Icon && <Icon className={`h-3.5 w-3.5 ${toneColor}`} />}
      {label && <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>}
      <span className={`text-[11px] font-semibold font-mono ${toneColor}`}>{value}</span>
    </div>
  );
}

export default function TopStatusStrip() {
  return (
    <div className="z-30 flex items-center gap-x-5 gap-y-1 overflow-x-auto border-b border-border bg-[hsl(220_34%_6%)] px-4 py-2 scrollbar-thin">
      {CELLS.map((c, i) => (
        <React.Fragment key={i}>
          {i > 0 && <span className="text-border">|</span>}
          <Cell {...c} />
        </React.Fragment>
      ))}
    </div>
  );
}