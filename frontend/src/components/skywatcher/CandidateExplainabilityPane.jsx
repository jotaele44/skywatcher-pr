import React from "react";

const SECTIONS = [
  ["why_flagged", "Why flagged"],
  ["observations", "Observations"],
  ["negative_evidence", "Negative evidence"],
  ["contradictions", "Contradictions"],
  ["unknowns", "Unknowns"],
  ["falsifiers", "What would falsify it"],
  ["next_evidence", "Next evidence"],
];

export default function CandidateExplainabilityPane({ candidate }) {
  if (!candidate) {
    return (
      <div className="rounded-lg border border-dashed border-border p-4 text-xs text-muted-foreground">
        Select an ILAP review candidate to inspect its evidence, contradictions, falsifiers, and next-evidence requirements.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-bold text-foreground">Candidate explainability</p>
          <p className="text-[11px] text-muted-foreground">{candidate.candidate_id || "UNIDENTIFIED_CANDIDATE"}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge>{candidate.candidate_family || "UNRESOLVED_FAMILY"}</Badge>
          <Badge>{candidate.review_state || "REVIEW_UNRESOLVED"}</Badge>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        {SECTIONS.map(([key, label]) => (
          <EvidenceSection key={key} title={label} values={candidate[key]} emphasis={key === "contradictions" || key === "falsifiers"} />
        ))}
      </div>

      <div className="rounded-lg border border-border bg-card p-3">
        <p className="mb-2 text-[10px] font-bold uppercase tracking-wide text-muted-foreground">Component scores</p>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(candidate.components || {}).map(([name, payload]) => {
            const value = typeof payload === "object" && payload !== null ? payload.value : payload;
            const state = typeof payload === "object" && payload !== null ? payload.state : "UNSPECIFIED";
            return (
              <div key={name} className="rounded-md border border-border px-2.5 py-2">
                <p className="truncate text-[10px] text-muted-foreground">{name}</p>
                <div className="mt-1 flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-foreground">{value == null ? "UNKNOWN" : Number(value).toFixed(3)}</span>
                  <span className="text-[9px] text-muted-foreground">{state}</span>
                </div>
              </div>
            );
          })}
          {!Object.keys(candidate.components || {}).length && (
            <p className="text-xs text-muted-foreground">No component-score payload loaded.</p>
          )}
        </div>
      </div>

      <div className="grid gap-2 text-xs md:grid-cols-3">
        <Meta label="Source lineage" value={candidate.source_lineage_id || "UNKNOWN"} />
        <Meta label="Independent source count" value={candidate.independent_source_count ?? "UNKNOWN"} />
        <Meta label="Composite state" value={candidate.composite_state || "CALIBRATION_REQUIRED"} />
      </div>

      <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-[10px] leading-relaxed text-amber-100/80">
        ILAP discovery output is review prioritization only. It does not establish hidden infrastructure, purpose, mission, wrongdoing, underground facilities, ownership, or causal linkage.
      </p>
    </div>
  );
}

function EvidenceSection({ title, values, emphasis = false }) {
  const rows = Array.isArray(values) ? values : values ? [values] : [];
  return (
    <section className={`rounded-lg border p-3 ${emphasis ? "border-amber-500/25 bg-amber-500/[0.03]" : "border-border bg-card"}`}>
      <p className="mb-2 text-[10px] font-bold uppercase tracking-wide text-muted-foreground">{title}</p>
      {rows.length ? (
        <ul className="space-y-1.5 text-xs text-foreground">
          {rows.map((row, i) => <li key={`${title}-${i}`} className="leading-relaxed">• {typeof row === "string" ? row : JSON.stringify(row)}</li>)}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">None recorded.</p>
      )}
    </section>
  );
}

function Badge({ children }) {
  return <span className="rounded-full border border-border bg-secondary px-2 py-1 text-[10px] text-muted-foreground">{children}</span>;
}

function Meta({ label, value }) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2">
      <p className="text-[9px] font-bold uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 break-words text-xs text-foreground">{value}</p>
    </div>
  );
}
