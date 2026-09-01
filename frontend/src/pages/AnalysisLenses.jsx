import React, { useState, useMemo, useEffect } from "react";
import { ScanEye, ShieldAlert, Target, Gauge } from "lucide-react";
import PageHeader from "@/components/skywatcher/PageHeader";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import Panel from "@/components/skywatcher/Panel";
import EmptyState from "@/components/skywatcher/EmptyState";
import LoadingState from "@/components/skywatcher/LoadingState";
import StatusChip from "@/components/skywatcher/StatusChip";
import { Toolbar, SearchInput } from "@/components/skywatcher/Toolbar";
import { appParams } from "@/lib/app-params";

// Same base the federation client resolves, so this page follows the app's API origin
// rather than inventing one. Defaults to the same-origin "/api" the desktop build uses.
const API_BASE = (appParams.apiBaseUrl || "/api").replace(/\/+$/, "");

const STAGE_LABEL = {
  flight_data_collection: "Flight Data Collection",
  satellite_image_processing: "Satellite Image Processing",
  cross_domain: "Cross-domain",
};

const LENS_STATUS_TONE = {
  active: "ready",
  experimental: "warn",
  deprecated: "muted",
};

// A threshold's governance status is the point of showing it: an EXECUTABLE_CANDIDATE
// cutoff is a running-but-unvalidated number, and a reader must be able to tell it from
// a VALIDATED one rather than seeing a bare value.
const THRESHOLD_TONE = {
  VALIDATED: "ready",
  CANONICAL: "ready",
  EXECUTABLE_CANDIDATE: "warn",
  CANDIDATE: "muted",
  CANDIDATE_PROJECT_GATE: "muted",
  PROHIBITED: "blocked",
};

export default function AnalysisLenses() {
  const [registry, setRegistry] = useState(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [stage, setStage] = useState("all");

  useEffect(() => {
    let cancelled = false;
    // Fetched, not hardcoded. Every other vocabulary in this dashboard is a literal in
    // JSX that must be hand-updated when the backend changes; adding a lens reaches this
    // page with no frontend edit at all.
    fetch(`${API_BASE}/analysis/registry`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled) setRegistry(data);
      })
      .catch(() => {
        if (!cancelled) setRegistry(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const lenses = registry?.lenses ?? [];
  const objectives = registry?.objectives ?? [];
  const thresholds = registry?.thresholds ?? [];

  const filtered = useMemo(() => {
    let rows = [...lenses];
    if (stage !== "all") rows = rows.filter((l) => l.stage === stage);
    if (q) {
      const s = q.toLowerCase();
      rows = rows.filter((l) =>
        [l.lens_id, l.name, l.owner, l.objective]
          .filter(Boolean)
          .some((v) => v.toLowerCase().includes(s))
      );
    }
    return rows;
  }, [lenses, q, stage]);

  if (loading) return <LoadingState />;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Analysis Lenses"
        subtitle="Required parameters, objectives and thresholds for both analysis stages"
        icon={ScanEye}
      />
      <DiagnosticNoticeBanner />

      {registry?.available === false && (
        <Panel>
          <EmptyState
            icon={ShieldAlert}
            title="Lens registry unavailable"
            message="The backend could not load configs/analysis. The ontology gate fails closed on this; this page only reports it."
          />
        </Panel>
      )}

      <Panel title="Objective profiles" bodyClassName="space-y-3">
        {objectives.length === 0 ? (
          <EmptyState icon={Target} title="No objective profiles" />
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {objectives.map((o) => (
              <div key={o.profile_id} className="rounded-lg border border-border p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="font-semibold text-foreground">{o.name}</div>
                  <StatusChip tone={LENS_STATUS_TONE[o.status] || "muted"} label={o.status} />
                </div>
                <div className="mt-1 font-mono text-[10px] text-muted-foreground">
                  {o.profile_id} · v{o.version}
                </div>
                <div className="mt-2 text-xs text-muted-foreground">
                  <span className="font-semibold text-foreground">
                    {o.required_lenses.length}
                  </span>{" "}
                  required ·{" "}
                  <span className="font-semibold text-foreground">
                    {o.optional_lenses.length}
                  </span>{" "}
                  optional
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {o.required_lenses.map((id) => (
                    <span
                      key={id}
                      className="rounded border border-primary/30 bg-primary/10 px-1.5 py-0.5 font-mono text-[10px] text-primary"
                    >
                      {id}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel bodyClassName="space-y-4">
        <Toolbar>
          <SearchInput value={q} onChange={setQ} placeholder="Search lens, owner, objective…" />
          <select
            value={stage}
            onChange={(e) => setStage(e.target.value)}
            aria-label="Filter by stage"
            className="rounded-lg border border-border bg-secondary/60 px-2 py-1.5 text-xs text-foreground"
          >
            <option value="all">All stages</option>
            {(registry?.stages ?? []).map((s) => (
              <option key={s} value={s}>
                {STAGE_LABEL[s] || s}
              </option>
            ))}
          </select>
        </Toolbar>

        {filtered.length === 0 ? (
          <EmptyState icon={ScanEye} title="No lenses" />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border scrollbar-thin">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2 font-semibold">Lens</th>
                  <th className="px-3 py-2 font-semibold">Stage</th>
                  <th className="px-3 py-2 font-semibold">Owner</th>
                  <th className="px-3 py-2 font-semibold">Required params</th>
                  <th className="px-3 py-2 font-semibold">Optional</th>
                  <th className="px-3 py-2 font-semibold">Emits</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((l) => (
                  <tr key={l.lens_id} className="border-b border-border/50 align-top">
                    <td className="px-3 py-2.5">
                      <div className="font-semibold text-foreground">{l.name}</div>
                      <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                        {l.lens_id}
                      </div>
                      <div className="mt-1 max-w-md text-xs text-muted-foreground">
                        {l.objective}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-xs text-muted-foreground">
                      {STAGE_LABEL[l.stage] || l.stage}
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-primary">{l.owner}</td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {l.required_parameters.map((p) => (
                          <span
                            key={p.parameter_id}
                            title={p.description}
                            className="rounded border border-border bg-secondary/60 px-1.5 py-0.5 font-mono text-[10px] text-foreground/80"
                          >
                            {p.parameter_id}
                          </span>
                        ))}
                        {l.required_parameters.length === 0 && (
                          <span className="text-[10px] text-muted-foreground">—</span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {l.optional_parameters.map((p) => (
                          // The tooltip is the degraded_behavior: what analysis is lost
                          // when this parameter is absent.
                          <span
                            key={p.parameter_id}
                            title={p.degraded_behavior}
                            className="rounded border border-dashed border-border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
                          >
                            {p.parameter_id}
                          </span>
                        ))}
                        {l.optional_parameters.length === 0 && (
                          <span className="text-[10px] text-muted-foreground">—</span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-[10px] text-muted-foreground">
                      {l.emits.length}
                    </td>
                    <td className="px-3 py-2.5">
                      <StatusChip
                        tone={LENS_STATUS_TONE[l.status] || "muted"}
                        label={l.status}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Threshold registry" bodyClassName="space-y-3">
        {thresholds.length === 0 ? (
          <EmptyState icon={Gauge} title="No thresholds" />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border scrollbar-thin">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2 font-semibold">Threshold</th>
                  <th className="px-3 py-2 font-semibold">Owner</th>
                  <th className="px-3 py-2 font-semibold">Value</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                  <th className="px-3 py-2 font-semibold">Failure behavior</th>
                </tr>
              </thead>
              <tbody>
                {thresholds.map((t) => (
                  <tr key={t.threshold_id} className="border-b border-border/50">
                    <td className="px-3 py-2.5">
                      <div className="font-mono text-[11px] text-foreground">
                        {t.threshold_id}
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">{t.purpose}</div>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-primary">{t.owner}</td>
                    <td className="px-3 py-2.5 font-mono text-xs text-foreground">
                      {String(t.value)}
                      {t.unit && t.unit !== "rule" && (
                        <span className="ml-1 text-[10px] text-muted-foreground">{t.unit}</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <StatusChip tone={THRESHOLD_TONE[t.status] || "muted"} label={t.status} />
                    </td>
                    <td className="px-3 py-2.5 max-w-sm text-xs text-muted-foreground">
                      {t.failure_behavior}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
