import React from "react";

function Bar({ label, score }) {
  const pct = score == null ? 0 : Math.round(score * 100);
  const color = pct >= 75 ? "hsl(142 70% 50%)" : pct >= 50 ? "hsl(38 100% 52%)" : "hsl(4 90% 60%)";
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[11px]">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono font-semibold" style={{ color }}>{pct}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

export default function CaptureQualityPanel({ capture }) {
  if (!capture) return null;
  return (
    <div className="space-y-3 rounded-lg border border-border bg-card p-3">
      <Bar label="OCR Quality Score" score={capture.ocr_quality_score} />
      <Bar label="Route Quality Score" score={capture.route_quality_score} />
      <div className="flex flex-wrap gap-2 pt-1 text-[10px]">
        <span className={`rounded border px-2 py-0.5 ${capture.route_extracted ? "border-[hsl(142_70%_45%/0.3)] text-[hsl(142_70%_60%)]" : "border-border text-muted-foreground"}`}>
          Route {capture.route_extracted ? "extracted" : "not extracted"}
        </span>
        <span className={`rounded border px-2 py-0.5 ${capture.labels_extracted ? "border-[hsl(142_70%_45%/0.3)] text-[hsl(142_70%_60%)]" : "border-border text-muted-foreground"}`}>
          Labels {capture.labels_extracted ? "extracted" : "not extracted"}
        </span>
        {capture.manual_review_required && (
          <span className="rounded border border-[hsl(38_100%_50%/0.3)] px-2 py-0.5 text-[hsl(38_100%_62%)]">
            Manual review required
          </span>
        )}
      </div>
    </div>
  );
}