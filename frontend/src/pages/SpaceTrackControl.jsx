import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Database,
  RefreshCw,
  Satellite,
  ShieldCheck,
} from "lucide-react";

import PageHeader from "@/components/skywatcher/PageHeader";
import Panel from "@/components/skywatcher/Panel";
import { federation } from "@/api/federationClient";

const STATE_TONE = {
  PASS: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  BLOCKED: "border-red-500/30 bg-red-500/10 text-red-300",
  FAIL: "border-red-500/30 bg-red-500/10 text-red-300",
  OPEN: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  PROVISIONAL: "border-amber-500/30 bg-amber-500/10 text-amber-300",
};

function StateBadge({ value }) {
  const tone = STATE_TONE[value] || "border-border bg-secondary text-muted-foreground";
  return (
    <span className={`inline-flex rounded border px-2 py-0.5 font-mono text-[10px] font-semibold ${tone}`}>
      {value || "UNKNOWN"}
    </span>
  );
}

function Metric({ label, value, detail }) {
  return (
    <div className="rounded-lg border border-border bg-secondary/20 p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-lg font-bold text-foreground">{value}</p>
      {detail ? <p className="mt-1 text-[11px] text-muted-foreground">{detail}</p> : null}
    </div>
  );
}

export default function SpaceTrackControl() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setStatus(await federation.spaceTrack.status());
    } catch (err) {
      setError(err?.message || "Unable to read the local Space-Track status.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const objects = status?.materializations?.space_objects;
  const reentry = status?.materializations?.reentry_events;
  const runtimeGates = status?.runtime?.gates || [];
  const sources = status?.sources || [];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Space-Track Source Control"
        subtitle="Read-only local orbital evidence, provenance, and certification state"
        icon={Satellite}
      />

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-secondary/20 p-4">
        <div>
          <p className="text-sm font-semibold text-foreground">Execution boundary</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Browser upstream calls are disabled. Operator writes are hard-disabled. This surface reads frozen local evidence only.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-border bg-secondary px-3 py-2 text-xs font-semibold text-foreground transition hover:bg-secondary/80 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Reload local status
        </button>
      </div>

      {error ? (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
          <div className="flex items-center gap-2 font-semibold">
            <AlertTriangle className="h-4 w-4" />
            Local status unavailable
          </div>
          <p className="mt-1 text-xs">{error}</p>
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric
          label="Static contract"
          value={status?.static_contract?.state || (loading ? "LOADING" : "UNKNOWN")}
          detail="Schema, cadence, controller, idempotency, and distribution gates"
        />
        <Metric
          label="Runtime certification"
          value={status?.runtime?.state || (loading ? "LOADING" : "UNKNOWN")}
          detail="Requires frozen authenticated source manifestations"
        />
        <Metric
          label="Space objects"
          value={objects?.object_count ?? 0}
          detail={objects?.available ? `${objects.contradiction_count} contradiction(s)` : "Not materialized"}
        />
        <Metric
          label="Reentry events"
          value={reentry?.event_count ?? 0}
          detail={reentry?.available ? `${reentry.contradiction_count} contradiction(s)` : "Not materialized"}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Certification gates" icon={ShieldCheck} bodyClassName="p-0">
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-background">
                <tr className="border-b border-border text-[10px] uppercase tracking-wide text-muted-foreground">
                  <th className="px-4 py-2">Gate</th>
                  <th className="px-4 py-2">State</th>
                  <th className="px-4 py-2">Detail</th>
                </tr>
              </thead>
              <tbody>
                {runtimeGates.map((gate) => (
                  <tr key={gate.gate} className="border-b border-border/50 align-top">
                    <td className="px-4 py-2.5 font-mono text-[11px] text-foreground">{gate.gate}</td>
                    <td className="px-4 py-2.5"><StateBadge value={gate.state} /></td>
                    <td className="px-4 py-2.5 text-muted-foreground">{gate.detail}</td>
                  </tr>
                ))}
                {!loading && runtimeGates.length === 0 ? (
                  <tr><td colSpan={3} className="px-4 py-6 text-center text-muted-foreground">No runtime gates available.</td></tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel title="Local evidence posture" icon={Database}>
          <div className="space-y-3 text-xs">
            <div className="flex items-center justify-between border-b border-border/60 pb-2">
              <span className="text-muted-foreground">Local store</span>
              <StateBadge value={status?.execution?.local_store_present ? "PASS" : "BLOCKED"} />
            </div>
            <div className="flex items-center justify-between border-b border-border/60 pb-2">
              <span className="text-muted-foreground">Browser → Space-Track</span>
              <span className="font-mono text-[11px] text-emerald-300">
                {status?.execution?.browser_upstream_calls === false ? "DISABLED" : "UNKNOWN"}
              </span>
            </div>
            <div className="flex items-center justify-between border-b border-border/60 pb-2">
              <span className="text-muted-foreground">Operator writes</span>
              <span className="font-mono text-[11px] text-emerald-300">
                {status?.execution?.operator_writes || "UNKNOWN"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Embedded credentials</span>
              <span className="font-mono text-[11px] text-emerald-300">
                {status?.execution?.credentials_embedded === false ? "NONE" : "UNKNOWN"}
              </span>
            </div>
          </div>
        </Panel>
      </div>

      <Panel title="Source contracts" icon={Satellite} bodyClassName="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] text-left text-xs">
            <thead>
              <tr className="border-b border-border text-[10px] uppercase tracking-wide text-muted-foreground">
                <th className="px-4 py-2">Source</th>
                <th className="px-4 py-2">Priority</th>
                <th className="px-4 py-2">Role</th>
                <th className="px-4 py-2">Batches</th>
                <th className="px-4 py-2">Schema</th>
                <th className="px-4 py-2">Watermark</th>
                <th className="px-4 py-2">Distribution</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => (
                <tr key={source.source_id} className="border-b border-border/50 align-top">
                  <td className="px-4 py-2.5 font-mono font-semibold text-foreground">{source.source_id}</td>
                  <td className="px-4 py-2.5 text-muted-foreground">{source.priority}</td>
                  <td className="max-w-[300px] px-4 py-2.5 text-muted-foreground">{source.role}</td>
                  <td className="px-4 py-2.5 font-mono text-foreground">{source.batch_count}</td>
                  <td className="px-4 py-2.5 font-mono text-[11px] text-muted-foreground">{source.schema_state}</td>
                  <td className="px-4 py-2.5 font-mono text-[10px] text-muted-foreground">
                    {source.watermark ? `${source.watermark.predicate} = ${source.watermark.value}` : "—"}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-[10px] text-muted-foreground">{source.distribution_class}</td>
                </tr>
              ))}
              {!loading && sources.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-6 text-center text-muted-foreground">No source contracts available.</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
