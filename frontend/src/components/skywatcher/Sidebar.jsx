import React from "react";
import { Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard, Plane, IdCard, Camera, Route as RouteIcon,
  Building2, TowerControl, ClipboardCheck, Share2, GaugeCircle,
  ScanSearch, ScanEye,
} from "lucide-react";
import { PROGRAM } from "@/lib/skywatcher";
import brandMark from "@/assets/icon-64.png?inline";

const NAV = [
  { to: "/", label: "Command Dashboard", icon: LayoutDashboard },
  { to: "/observations", label: "Airspace Observations", icon: Plane },
  { to: "/aircraft", label: "Aircraft Profiles", icon: IdCard },
  { to: "/fr24", label: "FR24 Intake", icon: Camera },
  { to: "/routes", label: "Route-Line Mining", icon: RouteIcon },
  { to: "/infrastructure", label: "Infrastructure Links", icon: Building2 },
  { to: "/airports", label: "PR Airports", icon: TowerControl },
  { to: "/review", label: "Manual Review", icon: ClipboardCheck },
  { to: "/export", label: "Federation Export", icon: Share2 },
  { to: "/readiness", label: "Readiness / Blockers", icon: GaugeCircle },
  { to: "/calibration", label: "SATIM Calibration", icon: ScanSearch },
  { to: "/analysis", label: "Analysis Lenses", icon: ScanEye },
];

export default function Sidebar({ onNavigate }) {
  const { pathname } = useLocation();
  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-border bg-[hsl(220_34%_6%)]">
      <div className="flex items-center gap-2.5 border-b border-border px-4 py-4">
        <img src={brandMark} alt="" aria-hidden="true" className="h-9 w-9 rounded-lg" />
        <div className="min-w-0">
          <p className="truncate text-sm font-bold tracking-tight text-foreground">{PROGRAM.appName}</p>
          <p className="truncate font-mono text-[10px] text-muted-foreground">{PROGRAM.federationRole}</p>
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto p-2 scrollbar-thin">
        {NAV.map((item) => {
          const active = item.to === "/" ? pathname === "/" : pathname.startsWith(item.to);
          const Icon = item.icon;
          return (
            <Link
              key={item.to}
              to={item.to}
              onClick={onNavigate}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
                active
                  ? "bg-primary/12 text-primary ring-1 ring-primary/25"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground"
              }`}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="truncate">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-border px-3 py-3">
        <div className="rounded-lg border border-[hsl(38_100%_50%/0.25)] bg-[hsl(38_100%_50%/0.06)] px-2.5 py-2">
          <p className="text-[9px] font-bold uppercase tracking-wider text-[hsl(38_100%_64%)]">Production Status</p>
          <p className="mt-0.5 font-mono text-[10px] font-semibold text-[hsl(38_100%_64%)]">
            {PROGRAM.productionStatus}
          </p>
        </div>
      </div>
    </aside>
  );
}