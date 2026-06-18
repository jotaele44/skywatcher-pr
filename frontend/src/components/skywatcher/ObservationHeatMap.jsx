import React, { useMemo, useState } from "react";
import { projectToShell } from "@/lib/skywatcher";

const PR_PATH =
  "M30,70 Q40,55 70,52 Q120,46 170,50 Q220,54 270,58 Q300,62 310,78 Q300,92 270,96 Q220,100 170,98 Q120,100 70,96 Q40,92 30,78 Z";

// Resolve an observation to a municipality using its nearest airport, then nearest asset.
function municipalityFor(obs, airportById, assetById) {
  if (obs.nearest_airport_id) {
    const apt = airportById(obs.nearest_airport_id);
    if (apt?.municipality) return { name: apt.municipality, lat: apt.latitude, lon: apt.longitude };
  }
  if (obs.nearest_asset_id) {
    const asset = assetById(obs.nearest_asset_id);
    if (asset?.municipality) return { name: asset.municipality, lat: asset.latitude, lon: asset.longitude };
  }
  if (obs.nearest_asset_name) return { name: obs.nearest_asset_name, lat: obs.latitude, lon: obs.longitude };
  return null;
}

// Heat color ramp from cool (low) to hot (high) density.
function heatColor(t) {
  if (t >= 0.85) return "hsl(4 90% 58%)";
  if (t >= 0.6) return "hsl(24 95% 56%)";
  if (t >= 0.4) return "hsl(38 100% 55%)";
  if (t >= 0.2) return "hsl(48 95% 55%)";
  return "hsl(190 90% 50%)";
}

const W = 340;
const H = 150;

export default function ObservationHeatMap({ observations = [], airportById, assetById, height = 300 }) {
  const [hover, setHover] = useState(null);

  const municipalities = useMemo(() => {
    const map = new Map();
    for (const obs of observations) {
      const m = municipalityFor(obs, airportById, assetById);
      if (!m) continue;
      const entry = map.get(m.name) || { name: m.name, count: 0, latSum: 0, lonSum: 0, n: 0 };
      entry.count += 1;
      if (m.lat != null && m.lon != null) {
        entry.latSum += m.lat;
        entry.lonSum += m.lon;
        entry.n += 1;
      }
      map.set(m.name, entry);
    }
    const list = [...map.values()].map((e) => ({
      name: e.name,
      count: e.count,
      lat: e.n ? e.latSum / e.n : null,
      lon: e.n ? e.lonSum / e.n : null,
    }));
    list.sort((a, b) => b.count - a.count);
    return list;
  }, [observations, airportById, assetById]);

  const max = municipalities.reduce((mx, m) => Math.max(mx, m.count), 0) || 1;
  const located = municipalities.filter((m) => m.lat != null && m.lon != null);

  return (
    <div className="rounded-xl border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-sm font-bold tracking-tight text-foreground">Observation Density Heat Map</h3>
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          Synthetic observation density by Puerto Rico municipality
        </p>
      </div>

      <div className="grid gap-3 p-4 lg:grid-cols-5">
        {/* Heat overlay on PR shell */}
        <div className="relative lg:col-span-3" style={{ height }}>
          <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full" preserveAspectRatio="xMidYMid meet">
            <defs>
              <radialGradient id="heatGlow" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stopColor="white" stopOpacity="0.55" />
                <stop offset="100%" stopColor="white" stopOpacity="0" />
              </radialGradient>
            </defs>
            <path d={PR_PATH} fill="hsl(215 28% 14%)" stroke="hsl(215 20% 30%)" strokeWidth="1" />

            {located.map((m, i) => {
              const t = m.count / max;
              const { x, y } = projectToShell(m.lat, m.lon, W, H, 22);
              const r = 8 + t * 22;
              const color = heatColor(t);
              return (
                <g key={i} onMouseEnter={() => setHover(m)} onMouseLeave={() => setHover(null)} style={{ cursor: "pointer" }}>
                  <circle cx={x} cy={y} r={r} fill={color} opacity={0.32} />
                  <circle cx={x} cy={y} r={r * 0.55} fill={color} opacity={0.5} />
                  <circle cx={x} cy={y} r={r} fill="url(#heatGlow)" />
                  <circle cx={x} cy={y} r={2.5} fill={color} />
                </g>
              );
            })}
          </svg>
          {hover && (
            <div className="pointer-events-none absolute left-2 top-2 rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs shadow-lg">
              <div className="font-semibold text-foreground">{hover.name}</div>
              <div className="text-muted-foreground">{hover.count} observation{hover.count > 1 ? "s" : ""}</div>
            </div>
          )}
        </div>

        {/* Ranked municipality bars */}
        <div className="space-y-1.5 lg:col-span-2">
          {municipalities.length === 0 && (
            <p className="text-xs text-muted-foreground">No municipality-resolvable observations.</p>
          )}
          {municipalities.slice(0, 8).map((m) => {
            const t = m.count / max;
            return (
              <div key={m.name} className="flex items-center gap-2">
                <span className="w-28 shrink-0 truncate text-[11px] text-foreground/80" title={m.name}>{m.name}</span>
                <div className="relative h-3 flex-1 overflow-hidden rounded bg-secondary/50">
                  <div className="h-full rounded" style={{ width: `${Math.max(t * 100, 6)}%`, backgroundColor: heatColor(t) }} />
                </div>
                <span className="w-6 shrink-0 text-right font-mono text-[11px] text-muted-foreground">{m.count}</span>
              </div>
            );
          })}
          <div className="flex items-center gap-2 pt-1">
            <span className="text-[10px] text-muted-foreground">Low</span>
            <div className="h-2 flex-1 rounded" style={{ background: "linear-gradient(90deg, hsl(190 90% 50%), hsl(48 95% 55%), hsl(38 100% 55%), hsl(24 95% 56%), hsl(4 90% 58%))" }} />
            <span className="text-[10px] text-muted-foreground">High</span>
          </div>
        </div>
      </div>
    </div>
  );
}