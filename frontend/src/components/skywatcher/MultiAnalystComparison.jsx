import React, { useMemo } from "react";

function pct(value) {
  return value == null ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
}

export default function MultiAnalystComparison({ analysts = [], comparisons = [] }) {
  const unresolved = useMemo(
    () => comparisons.filter((row) => row.state === "REVIEW_UNRESOLVED" || row.class_agreement === false),
    [comparisons]
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-bold text-foreground">Multi-analyst comparison</p>
          <p className="text-[11px] text-muted-foreground">Consensus never overrides hard contradictions.</p>
        </div>
        <span className="rounded-full border border-border px-2 py-1 text-[10px] text-muted-foreground">
          {analysts.length} analyst(s) · {unresolved.length} unresolved
        </span>
      </div>

      {comparisons.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-4 text-xs text-muted-foreground">
          No comparable annotation geometries loaded.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[720px] text-xs">
            <thead className="bg-secondary/60 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-2">Feature</th>
                <th className="px-3 py-2">Analysts</th>
                <th className="px-3 py-2">IoU</th>
                <th className="px-3 py-2">Symmetric diff.</th>
                <th className="px-3 py-2">Centroid Δ</th>
                <th className="px-3 py-2">Class agreement</th>
                <th className="px-3 py-2">State</th>
              </tr>
            </thead>
            <tbody>
              {comparisons.map((row) => (
                <tr key={row.feature_id} className="border-t border-border">
                  <td className="px-3 py-2 font-semibold text-foreground">{row.feature_id}</td>
                  <td className="px-3 py-2 text-muted-foreground">{row.analyst_pair || "—"}</td>
                  <td className="px-3 py-2">{pct(row.iou)}</td>
                  <td className="px-3 py-2">{row.symmetric_difference ?? "—"}</td>
                  <td className="px-3 py-2">{row.centroid_displacement ?? "—"}</td>
                  <td className="px-3 py-2">{row.class_agreement == null ? "—" : row.class_agreement ? "Yes" : "No"}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-[10px] ${
                      row.state === "REVIEW_UNRESOLVED" ? "bg-amber-500/10 text-amber-300" : "bg-secondary text-muted-foreground"
                    }`}>
                      {row.state || "UNRESOLVED"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
