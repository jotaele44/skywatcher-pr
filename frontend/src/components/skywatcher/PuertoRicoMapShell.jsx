import React, { useState } from "react";
import { Radar, MapPin } from "lucide-react";
import { projectToShell } from "@/lib/skywatcher";

// Simplified Puerto Rico mainland + outer islands silhouette (projected within PR_BOUNDS)
// Path is a stylized diagnostic outline — not a survey-grade boundary.
const PR_MAINLAND =
  "M 60 150 L 90 138 L 130 132 L 180 130 L 240 128 L 300 130 L 360 134 L 410 140 L 450 150 " +
  "L 470 168 L 460 188 L 430 200 L 380 206 L 320 208 L 260 208 L 200 206 L 150 200 L 100 190 " +
  "L 70 175 Z";

const MARKER_STYLES = {
  observation: { color: "hsl(190 100% 55%)", r: 4 },
  airport: { color: "hsl(38 100% 56%)", r: 5 },
  asset: { color: "hsl(262 52% 66%)", r: 4 },
};

export default function PuertoRicoMapShell({
  observations = [],
  airports = [],
  assets = [],
  routes = [],
  height = 300,
  title = "Puerto Rico Airspace Context",
  diagnostic = true,
}) {
  const W = 520;
  const H = height;
  const [hover, setHover] = useState(null);

  const obsPts = observations
    .filter((o) => o.latitude != null && o.longitude != null)
    .map((o) => ({ ...projectToShell(o.latitude, o.longitude, W, H), data: o, kind: "observation" }));
  const aptPts = airports
    .filter((a) => a.latitude != null && a.longitude != null)
    .map((a) => ({ ...projectToShell(a.latitude, a.longitude, W, H), data: a, kind: "airport" }));
  const assetPts = assets
    .filter((a) => a.latitude != null && a.longitude != null)
    .map((a) => ({ ...projectToShell(a.latitude, a.longitude, W, H), data: a, kind: "asset" }));
  const routeLines = routes
    .filter((r) => r.start_lat != null && r.end_lat != null)
    .map((r) => ({
      a: projectToShell(r.start_lat, r.start_lon, W, H),
      b: projectToShell(r.end_lat, r.end_lon, W, H),
      data: r,
    }));

  return (
    <div className="relative overflow-hidden rounded-xl border border-border bg-[hsl(220_34%_4%)]">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Radar className="h-4 w-4 text-primary" />
          <span className="text-xs font-bold uppercase tracking-wider text-foreground/90">{title}</span>
        </div>
        {diagnostic && (
          <span className="rounded-full border border-[hsl(262_52%_60%/0.35)] bg-[hsl(262_52%_60%/0.14)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[hsl(262_60%_76%)]">
            Diagnostic / Sample
          </span>
        )}
      </div>

      <div className="relative bg-grid-radar">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: H }}>
          {/* radar sweep rings */}
          <g opacity="0.25">
            <circle cx={W / 2} cy={H / 2} r="60" fill="none" stroke="hsl(190 100% 50% / 0.3)" strokeWidth="0.5" />
            <circle cx={W / 2} cy={H / 2} r="120" fill="none" stroke="hsl(190 100% 50% / 0.2)" strokeWidth="0.5" />
            <circle cx={W / 2} cy={H / 2} r="190" fill="none" stroke="hsl(190 100% 50% / 0.12)" strokeWidth="0.5" />
          </g>

          {/* PR silhouette */}
          <path d={PR_MAINLAND} fill="hsl(217 32% 12% / 0.8)" stroke="hsl(190 100% 50% / 0.4)" strokeWidth="1" />
          {/* Vieques + Culebra dots */}
          <ellipse cx="470" cy="230" rx="14" ry="5" fill="hsl(217 32% 12% / 0.8)" stroke="hsl(190 100% 50% / 0.4)" strokeWidth="1" />
          <circle cx="492" cy="210" r="5" fill="hsl(217 32% 12% / 0.8)" stroke="hsl(190 100% 50% / 0.4)" strokeWidth="1" />

          {/* route lines */}
          {routeLines.map((r, i) => (
            <line
              key={`rt-${i}`}
              x1={r.a.x} y1={r.a.y} x2={r.b.x} y2={r.b.y}
              stroke="hsl(190 100% 60% / 0.55)" strokeWidth="1.4" strokeDasharray="4 3"
            />
          ))}

          {/* asset markers (diamonds) */}
          {assetPts.map((p, i) => (
            <rect
              key={`as-${i}`} x={p.x - 3.5} y={p.y - 3.5} width="7" height="7"
              transform={`rotate(45 ${p.x} ${p.y})`}
              fill={MARKER_STYLES.asset.color} opacity="0.85"
              onMouseEnter={() => setHover({ ...p })} onMouseLeave={() => setHover(null)}
              style={{ cursor: "pointer" }}
            />
          ))}

          {/* airport markers (squares) */}
          {aptPts.map((p, i) => (
            <rect
              key={`ap-${i}`} x={p.x - 4} y={p.y - 4} width="8" height="8" rx="1"
              fill={MARKER_STYLES.airport.color}
              onMouseEnter={() => setHover({ ...p })} onMouseLeave={() => setHover(null)}
              style={{ cursor: "pointer" }}
            />
          ))}

          {/* observation markers (pulse dots) */}
          {obsPts.map((p, i) => (
            <g key={`ob-${i}`} onMouseEnter={() => setHover({ ...p })} onMouseLeave={() => setHover(null)} style={{ cursor: "pointer" }}>
              <circle cx={p.x} cy={p.y} r="7" fill="hsl(190 100% 55% / 0.15)" />
              <circle cx={p.x} cy={p.y} r="3.5" fill={MARKER_STYLES.observation.color} />
            </g>
          ))}
        </svg>

        {hover && (
          <div
            className="pointer-events-none absolute z-10 max-w-[200px] rounded-md border border-border bg-popover px-2.5 py-1.5 text-[10px] shadow-lg"
            style={{ left: `${(hover.x / W) * 100}%`, top: `${(hover.y / H) * 100}%`, transform: "translate(-50%, -120%)" }}
          >
            <p className="font-semibold text-foreground">
              {hover.data.callsign || hover.data.airport_name || hover.data.asset_name || "Record"}
            </p>
            <p className="font-mono text-muted-foreground">
              {(hover.data.latitude ?? 0).toFixed(3)}, {(hover.data.longitude ?? 0).toFixed(3)}
            </p>
          </div>
        )}
      </div>

      {/* legend */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-4 py-2 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full" style={{ background: MARKER_STYLES.observation.color }} /> Observation</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: MARKER_STYLES.airport.color }} /> Airport</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5" style={{ background: MARKER_STYLES.asset.color, transform: "rotate(45deg)" }} /> Infrastructure</span>
        <span className="flex items-center gap-1.5"><span className="inline-block h-0 w-3 border-t-2 border-dashed" style={{ borderColor: "hsl(190 100% 60%)" }} /> Route segment</span>
        <span className="ml-auto flex items-center gap-1 font-mono"><MapPin className="h-3 w-3" /> PR_BOUNDS projection</span>
      </div>
    </div>
  );
}