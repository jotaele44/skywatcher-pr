import React, { useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from "recharts";

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs shadow-lg">
      <div className="font-mono font-semibold text-foreground">{label}</div>
      <div className="text-muted-foreground">{payload[0].value} observation{payload[0].value !== 1 ? "s" : ""}</div>
    </div>
  );
}

export default function HourlyObservationsChart({ observations = [] }) {
  const { data, peakHour, total } = useMemo(() => {
    const buckets = Array.from({ length: 24 }, (_, h) => ({ hour: h, label: `${String(h).padStart(2, "0")}:00`, count: 0 }));
    let total = 0;
    for (const o of observations) {
      if (!o.observed_at) continue;
      const h = new Date(o.observed_at).getHours();
      if (h >= 0 && h < 24) { buckets[h].count += 1; total += 1; }
    }
    const peak = buckets.reduce((mx, b) => (b.count > mx.count ? b : mx), buckets[0]);
    return { data: buckets, peakHour: peak.count > 0 ? peak.label : null, total };
  }, [observations]);

  const max = data.reduce((mx, b) => Math.max(mx, b.count), 0);

  return (
    <div className="rounded-xl border border-border bg-card">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div>
          <h3 className="text-sm font-bold tracking-tight text-foreground">Hourly Observation Pattern</h3>
          <p className="mt-0.5 text-[11px] text-muted-foreground">Synthetic observations bucketed by hour of day (local)</p>
        </div>
        {peakHour && (
          <div className="shrink-0 text-right">
            <p className="font-mono text-sm font-bold text-primary">{peakHour}</p>
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Peak hour</p>
          </div>
        )}
      </div>
      <div className="p-4">
        {total === 0 ? (
          <p className="py-12 text-center text-xs text-muted-foreground">No time-stamped observations available.</p>
        ) : (
          <div style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(217 28% 16%)" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 9, fill: "hsl(215 16% 58%)" }} interval={1} tickLine={false} axisLine={{ stroke: "hsl(217 28% 16%)" }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: "hsl(215 16% 58%)" }} tickLine={false} axisLine={false} width={32} />
                <Tooltip cursor={{ fill: "hsl(190 100% 50% / 0.06)" }} content={<CustomTooltip />} />
                <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                  {data.map((b, i) => (
                    <Cell key={i} fill={b.count === max && max > 0 ? "hsl(38 100% 55%)" : "hsl(190 100% 50%)"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}