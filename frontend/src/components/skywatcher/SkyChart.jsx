import React, { useMemo, useState } from "react";
import { Copy, Minus, Plus } from "lucide-react";
import {
  compassVectors,
  formatAltitudeBadge,
  formatLocalTime,
  fovRectangle,
  gnomonic,
} from "@/lib/skyProjection";

// Sky atlas centred on the selected target, in the observer's horizon frame: screen up
// is towards the zenith and screen right towards increasing azimuth, so the view matches
// what a telescope pointed at the target sees. The backend supplies apparent alt/az; the
// gnomonic projection happens here so zooming never refetches.
const W = 900;
const H = 560;
// The view spans this many FOV widths at zoom 1; the backend sends a radius that covers it.
const VIEW_FOV_MULTIPLE = 3;
const FOV_OPTIONS = [1, 2, 3, 6, 12];
const ZOOM_LEVELS = [1, 1.5, 2, 3, 4];

function starRadius(mag, limit) {
  return Math.min(5, Math.max(0.6, 0.7 + (limit - mag) * 0.55));
}

function project(point, center, scale) {
  const p = gnomonic(point.alt, point.az, center.alt, center.az);
  if (!p.visible) return null;
  return { x: W / 2 + p.x * scale, y: H / 2 - p.y * scale };
}

function inView(p, margin = 40) {
  return p && p.x > -margin && p.x < W + margin && p.y > -margin && p.y < H + margin;
}

function polylineSegments(points, center, scale) {
  const segments = [];
  let current = [];
  for (const [alt, az] of points) {
    const p = project({ alt, az }, center, scale);
    if (p && Math.abs(p.x) < W * 4 && Math.abs(p.y) < H * 4) {
      current.push(`${p.x.toFixed(1)},${p.y.toFixed(1)}`);
    } else if (current.length) {
      segments.push(current);
      current = [];
    }
  }
  if (current.length) segments.push(current);
  return segments.filter((segment) => segment.length > 1);
}

export default function SkyChart({ chart, fovDeg, onFovChange, onCopy }) {
  const [zoomIndex, setZoomIndex] = useState(0);
  const zoom = ZOOM_LEVELS[zoomIndex];
  const target = chart.target;
  const center = { alt: target.alt_deg, az: target.az_deg };
  const scale = (W * zoom) / (fovDeg * VIEW_FOV_MULTIPLE);
  const limit = chart.limiting_magnitude ?? 6;

  const layers = useMemo(() => {
    const stars = [];
    for (const star of chart.stars || []) {
      const p = project(star, center, scale);
      if (inView(p, 8)) stars.push({ ...star, p });
    }
    const lines = [];
    for (const line of chart.lines || []) {
      for (const segment of polylineSegments(line.points, center, scale)) {
        lines.push({ key: `${line.constellation}-${lines.length}`, points: segment.join(" ") });
      }
    }
    const project1 = (items) =>
      (items || []).map((item) => ({ ...item, p: project(item, center, scale) })).filter((item) => inView(item.p));
    const horizon = [];
    for (let az = center.az - 120; az <= center.az + 120; az += 2) {
      const p = project({ alt: 0, az }, center, scale);
      if (p && Math.abs(p.x) < W * 4 && Math.abs(p.y) < H * 4) horizon.push(`${p.x.toFixed(1)},${p.y.toFixed(1)}`);
    }
    return {
      stars,
      lines,
      constellations: project1(chart.constellation_labels),
      dso: project1(chart.dso_markers),
      solar: project1(chart.solar_system),
      satellites: project1(chart.satellites),
      horizon: horizon.length > 1 ? horizon.join(" ") : null,
    };
  }, [chart, scale, center.alt, center.az]);

  const fov = fovRectangle(fovDeg);
  const rectW = fov.width * scale;
  const rectH = fov.height * scale;
  const compass = compassVectors(center.alt, center.az, 0.35);
  const compassCenter = { x: W / 2, y: H - 64 };
  const compassRadius = 26;
  const longName = target.long_designation || target.designation;

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
        <p className="text-xs font-semibold text-foreground">Sky chart</p>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            Field of view
            <select
              onChange={(event) => onFovChange(Number(event.target.value))}
              value={fovDeg}
              aria-label="Field of view"
              className="rounded-md border border-border bg-secondary px-2 py-1 text-xs text-foreground"
            >
              {FOV_OPTIONS.map((value) => (
                <option key={value} value={value}>{`${value.toFixed(1)}°`}</option>
              ))}
            </select>
          </label>
          <button
            onClick={() => setZoomIndex((index) => Math.max(0, index - 1))}
            type="button"
            aria-label="Zoom out"
            disabled={zoomIndex === 0}
            className="rounded-md border border-border bg-secondary p-1.5 text-foreground disabled:opacity-40"
          >
            <Minus className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => setZoomIndex((index) => Math.min(ZOOM_LEVELS.length - 1, index + 1))}
            type="button"
            aria-label="Zoom in"
            disabled={zoomIndex === ZOOM_LEVELS.length - 1}
            className="rounded-md border border-border bg-secondary p-1.5 text-foreground disabled:opacity-40"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Sky chart centred on ${longName}`}
        className="block h-auto w-full bg-[hsl(222_47%_5%)]"
        preserveAspectRatio="xMidYMid meet"
      >
        <rect x="0" y="0" width={W} height={H} fill="hsl(222 47% 5%)" />
        {layers.horizon ? (
          <polyline points={layers.horizon} fill="none" stroke="hsl(30 60% 45% / 0.7)" strokeWidth="1.5" strokeDasharray="6 5" />
        ) : null}
        <g stroke="hsl(205 70% 70% / 0.32)" strokeWidth="1" fill="none">
          {layers.lines.map((line) => (
            <polyline key={line.key} points={line.points} />
          ))}
        </g>
        <g fill="hsl(205 40% 75% / 0.35)" fontSize="13" fontStyle="italic">
          {layers.constellations.map((item) => (
            <text key={item.id} x={item.p.x} y={item.p.y} textAnchor="middle">{item.name}</text>
          ))}
        </g>
        <g>
          {layers.stars.map((star, index) => (
            <circle
              key={star.id || `deep-${index}`}
              cx={star.p.x.toFixed(1)}
              cy={star.p.y.toFixed(1)}
              r={starRadius(star.mag, limit).toFixed(2)}
              fill={star.mag < 2 ? "hsl(48 100% 96%)" : "hsl(210 40% 92%)"}
              opacity={star.mag > 6 ? 0.65 : 0.95}
            />
          ))}
        </g>
        <g fill="hsl(210 30% 82%)" fontSize="12">
          {layers.stars
            .filter((star) => star.label)
            .map((star) => (
              <text key={`label-${star.id}`} x={star.p.x + 7} y={star.p.y - 6}>{star.label}</text>
            ))}
        </g>
        <g>
          {layers.dso.map((item) => (
            <g key={item.id}>
              <circle cx={item.p.x} cy={item.p.y} r="7" fill="none" stroke="hsl(150 45% 60% / 0.8)" strokeWidth="1.2" />
              <text x={item.p.x + 10} y={item.p.y + 4} fill="hsl(150 45% 70%)" fontSize="12">{item.designation}</text>
            </g>
          ))}
        </g>
        <g>
          {layers.solar.map((item) => (
            <g key={item.id}>
              <circle cx={item.p.x} cy={item.p.y} r="6" fill="hsl(38 100% 60%)" />
              <text x={item.p.x + 9} y={item.p.y + 4} fill="hsl(38 100% 70%)" fontSize="12">{item.display}</text>
            </g>
          ))}
          {layers.satellites.map((item) => (
            <g key={item.id}>
              <rect x={item.p.x - 4} y={item.p.y - 4} width="8" height="8" transform={`rotate(45 ${item.p.x} ${item.p.y})`} fill={item.sunlit ? "hsl(190 90% 60%)" : "hsl(190 30% 45%)"} />
              <text x={item.p.x + 9} y={item.p.y + 4} fill="hsl(190 80% 70%)" fontSize="12">{item.display}</text>
            </g>
          ))}
        </g>

        <g>
          <rect
            x={W / 2 - rectW / 2}
            y={H / 2 - rectH / 2}
            width={rectW}
            height={rectH}
            fill="none"
            stroke="hsl(160 30% 70% / 0.9)"
            strokeWidth="1.5"
          />
          <text x={W / 2} y={H / 2 - rectH / 2 - 8} textAnchor="middle" fill="hsl(0 0% 96%)" fontSize="15" fontWeight="600">
            {longName}
          </text>
          <text x={W / 2} y={H / 2 + rectH / 2 + 18} textAnchor="middle" fill="hsl(210 20% 80%)" fontSize="13">
            {`FOV ${fovDeg.toFixed(1)}°`}
          </text>
          <line x1={W / 2 - 6} y1={H / 2} x2={W / 2 + 6} y2={H / 2} stroke="hsl(0 0% 96%)" strokeWidth="1" />
          <line x1={W / 2} y1={H / 2 - 6} x2={W / 2} y2={H / 2 + 6} stroke="hsl(0 0% 96%)" strokeWidth="1" />
        </g>

        <g aria-label="Compass">
          <circle cx={compassCenter.x} cy={compassCenter.y} r={compassRadius + 10} fill="hsl(222 47% 8% / 0.75)" stroke="hsl(210 20% 70% / 0.5)" />
          {["N", "E", "S", "W"].map((letter) => {
            const v = compass[letter];
            const length = Math.hypot(v.x, v.y) || 1;
            const x = compassCenter.x + (v.x / length) * compassRadius;
            const y = compassCenter.y - (v.y / length) * compassRadius;
            return (
              <text
                key={letter}
                x={x}
                y={y + 4}
                textAnchor="middle"
                fontSize="12"
                fontWeight="700"
                fill={letter === "N" ? "hsl(0 85% 65%)" : "hsl(210 20% 88%)"}
              >
                {letter}
              </text>
            );
          })}
        </g>

        <text x={W - 16} y={H - 18} textAnchor="end" fill="hsl(210 20% 88%)" fontSize="15" fontWeight="600">
          {formatLocalTime(chart.at_utc)}
        </text>
      </svg>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-foreground">{target.designation}</p>
          {target.name && target.name !== target.designation ? (
            <p className="truncate text-xs text-muted-foreground">{target.name}</p>
          ) : null}
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="font-mono text-foreground">{formatAltitudeBadge(target.alt_deg)}</span>
            <span className="font-mono">{`Az ${Number(target.az_deg).toFixed(1)}°`}</span>
            {target.filter_hint ? (
              <span
                title="Heuristic suggestion from the object type"
                className="rounded border border-border bg-secondary px-1.5 py-0.5 text-[10px] font-semibold text-foreground"
              >
                {target.filter_hint.label}
              </span>
            ) : null}
          </div>
        </div>
        <button
          onClick={() => onCopy(target, chart.at_utc, chart.observer)}
          type="button"
          aria-label="Copy target coordinates"
          className="inline-flex items-center gap-2 rounded-lg border border-border bg-secondary px-3 py-2 text-xs font-semibold text-foreground transition hover:bg-secondary/80"
        >
          <Copy className="h-4 w-4" />
          Copy coordinates
        </button>
      </div>
    </div>
  );
}
