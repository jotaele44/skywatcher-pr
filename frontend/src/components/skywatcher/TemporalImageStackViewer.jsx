import React, { useMemo, useState } from "react";

export default function TemporalImageStackViewer({ frames = [] }) {
  const ordered = useMemo(
    () => [...frames].sort((a, b) => String(a.imagery_epoch || "9999").localeCompare(String(b.imagery_epoch || "9999"))),
    [frames]
  );
  const [index, setIndex] = useState(0);
  const frame = ordered[Math.min(index, Math.max(ordered.length - 1, 0))];

  if (!ordered.length) {
    return (
      <div className="rounded-lg border border-dashed border-border p-4 text-xs text-muted-foreground">
        No temporal imagery frames loaded. Screenshot/device time must not be substituted for imagery epoch.
      </div>
    );
  }

  const step = (delta) => setIndex((current) => Math.max(0, Math.min(ordered.length - 1, current + delta)));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-bold text-foreground">Temporal image stack</p>
          <p className="text-[11px] text-muted-foreground">Source lineage and imagery epoch remain frame-specific.</p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => step(-1)} disabled={index === 0} className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40">Previous</button>
          <span className="text-[11px] text-muted-foreground">{index + 1}/{ordered.length}</span>
          <button type="button" onClick={() => step(1)} disabled={index === ordered.length - 1} className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40">Next</button>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-black/20">
        {frame.image_url ? (
          <img src={frame.image_url} alt={frame.label || frame.frame_id || "Temporal imagery frame"} className="max-h-[520px] w-full object-contain" />
        ) : (
          <div className="flex min-h-48 items-center justify-center text-xs text-muted-foreground">Frame image unavailable</div>
        )}
      </div>

      <div className="grid gap-2 text-xs md:grid-cols-2 lg:grid-cols-4">
        <Meta label="Frame" value={frame.frame_id} />
        <Meta label="Imagery epoch" value={frame.imagery_epoch || "UNKNOWN_DATE"} />
        <Meta label="Provider/source" value={frame.provider || frame.source || "UNKNOWN"} />
        <Meta label="Lineage" value={frame.source_lineage_id || "UNKNOWN"} />
        <Meta label="Registration" value={frame.registration_state || "UNRESOLVED"} />
        <Meta label="Persistence" value={frame.persistence_state || "UNRESOLVED"} />
        <Meta label="Quality" value={frame.quality_state || "UNKNOWN"} />
        <Meta label="Independent source" value={frame.independent_source == null ? "UNKNOWN" : frame.independent_source ? "YES" : "NO"} />
      </div>
    </div>
  );
}

function Meta({ label, value }) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2">
      <p className="text-[9px] font-bold uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 break-words text-xs text-foreground">{value ?? "—"}</p>
    </div>
  );
}
