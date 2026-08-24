import React from "react";
import { Crosshair, LocateFixed, MapPinned, Scale, ShieldCheck } from "lucide-react";
import { useSkywatcher } from "@/lib/SkywatcherData";
import EmptyState from "@/components/skywatcher/EmptyState";
import LoadingState from "@/components/skywatcher/LoadingState";
import MetricCard from "@/components/skywatcher/MetricCard";
import PageHeader from "@/components/skywatcher/PageHeader";
import Panel from "@/components/skywatcher/Panel";
import PuertoRicoMapShell from "@/components/skywatcher/PuertoRicoMapShell";
import StatusChip from "@/components/skywatcher/StatusChip";

const markerTone = (status) => {
  if (status === "selected") return "ready";
  if (status?.startsWith("ambiguous")) return "warn";
  if (status === "unreadable") return "blocked";
  return "muted";
};

const georefTone = (status) => {
  if (status === "located") return "ready";
  if (status === "unclassified") return "warn";
  if (status?.startsWith("rejected")) return "blocked";
  return "muted";
};

const percent = (numerator, denominator) =>
  denominator ? `${((numerator / denominator) * 100).toFixed(1)}%` : "—";

const fixed = (value, digits = 1) =>
  Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";

export default function SpatialTruth() {
  const data = useSkywatcher();
  if (data.loading) return <LoadingState />;

  const observations = data.spatialObservations;
  const mapObservations = observations.slice(0, 1000);
  const frames = data.spatialFrames;
  const accounted = frames.filter((row) => row.marker_status).length;
  const locatedFrames = frames.filter((row) => row.georef_status === "located").length;
  const eligibleRungs = data.zoomRungs.filter((row) => row.eligible_for_transfer);
  const recoverable = frames.filter(
    (row) => row.marker_status === "selected" && Number(row.anchor_count || 0) >= 1,
  );
  const unresolvedRecoverable = recoverable.filter(
    (row) => row.georef_status !== "located",
  ).length;
  const unresolvedRate = recoverable.length
    ? unresolvedRecoverable / recoverable.length
    : 0;
  const scaleBarReviewDue = unresolvedRate > 0.15;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Aircraft Spatial Truth"
        subtitle="Fail-closed marker binding, persisted georeferences, relative zoom evidence, and bounded aircraft coordinates"
        icon={Crosshair}
        actions={null}
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Marker accounting"
          value={percent(accounted, frames.length)}
          sub={`${accounted} of ${frames.length} aircraft frames have a terminal decision`}
          icon={ShieldCheck}
          accent={accounted === frames.length && frames.length ? "ready" : "warn"}
        />
        <MetricCard
          label="Located aircraft"
          value={observations.length}
          sub="Projected positions with estimated error ≤500 m"
          icon={MapPinned}
          accent="ready"
        />
        <MetricCard
          label="Located frames"
          value={percent(locatedFrames, frames.length)}
          sub={`${locatedFrames} accepted screenshot transforms`}
          icon={LocateFixed}
          accent="primary"
        />
        <MetricCard
          label="Transferable zoom rungs"
          value={eligibleRungs.length}
          sub={`${data.zoomRungs.length} corroborated relative rungs total`}
          icon={Scale}
          accent="info"
        />
      </div>

      <Panel
        title="Deferred scale-bar decision"
        icon={Scale}
        action={
          <StatusChip
            tone={scaleBarReviewDue ? "warn" : "ready"}
            label={scaleBarReviewDue ? "Threshold exceeded" : "OCR deferred"}
            icon={null}
          />
        }
      >
        <p className="text-sm text-muted-foreground">
          {unresolvedRecoverable} of {recoverable.length} otherwise-recoverable frames remain
          unresolved ({percent(unresolvedRecoverable, recoverable.length)}). Dedicated scale-bar
          OCR is considered only when this rate exceeds 15%.
        </p>
      </Panel>

      <PuertoRicoMapShell
        observations={mapObservations}
        airports={data.airports}
        height={290}
        title={
          observations.length > mapObservations.length
            ? "Bounded-error RLSM aircraft positions (latest 1,000)"
            : "Bounded-error RLSM aircraft positions"
        }
        diagnostic={false}
      />

      <Panel title="Located aircraft observations" icon={MapPinned} action={null}>
        {observations.length === 0 ? (
          <EmptyState
            icon={MapPinned}
            title="No bounded aircraft positions yet"
            message="Run the aircraft_markers and georeference stages against the local RLSM corpus."
          />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2 font-semibold">Aircraft</th>
                  <th className="px-3 py-2 font-semibold">Source pixel</th>
                  <th className="px-3 py-2 font-semibold">Glyph rotation</th>
                  <th className="px-3 py-2 font-semibold">Coordinate</th>
                  <th className="px-3 py-2 font-semibold">Method</th>
                  <th className="px-3 py-2 font-semibold">Error</th>
                </tr>
              </thead>
              <tbody>
                {observations.slice(0, 100).map((row) => (
                  <tr key={row.id} className="border-b border-border/50">
                    <td className="px-3 py-2.5">
                      <p className="font-mono font-semibold text-foreground">
                        {row.callsign || row.registration || "Unknown"}
                      </p>
                      <p className="text-[10px] text-muted-foreground">{row.source_filename}</p>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">
                      {fixed(row.pixel_x)}, {fixed(row.pixel_y)}
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">
                      {row.icon_rotation_deg == null ? "unresolved" : `${fixed(row.icon_rotation_deg)}°`}
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-foreground">
                      {fixed(row.latitude, 5)}, {fixed(row.longitude, 5)}
                    </td>
                    <td className="px-3 py-2.5">
                      <StatusChip tone="ready" label={row.position_method} icon={null} />
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-foreground">
                      {fixed(row.position_error_m, 0)} m
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel
        title="Frame accounting and georeference evidence"
        icon={ShieldCheck}
        action={null}
      >
        {frames.length === 0 ? (
          <EmptyState
            icon={ShieldCheck}
            title="No spatial frame accounting yet"
            message="Every aircraft screenshot receives a terminal marker and georeference status when the stages run."
          />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2 font-semibold">Screenshot</th>
                  <th className="px-3 py-2 font-semibold">Marker</th>
                  <th className="px-3 py-2 font-semibold">Candidates</th>
                  <th className="px-3 py-2 font-semibold">Georeference</th>
                  <th className="px-3 py-2 font-semibold">Anchors</th>
                  <th className="px-3 py-2 font-semibold">Zoom</th>
                  <th className="px-3 py-2 font-semibold">Error</th>
                </tr>
              </thead>
              <tbody>
                {frames.slice(0, 100).map((row) => (
                  <tr key={row.id} className="border-b border-border/50">
                    <td className="px-3 py-2.5">
                      <p className="max-w-64 truncate font-mono text-xs text-foreground">{row.filename}</p>
                      <p className="text-[10px] text-muted-foreground">#{row.screenshot_id}</p>
                    </td>
                    <td className="px-3 py-2.5">
                      <StatusChip
                        tone={markerTone(row.marker_status)}
                        label={row.marker_status || "not run"}
                        icon={null}
                      />
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">
                      {row.candidate_count ?? "—"}
                    </td>
                    <td className="px-3 py-2.5">
                      <StatusChip
                        tone={georefTone(row.georef_status)}
                        label={row.georef_method || row.georef_status || "not run"}
                        icon={null}
                      />
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">
                      {row.anchor_count ?? "—"}
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">
                      {row.zoom_rung == null ? "—" : `rung ${row.zoom_rung} / n=${row.zoom_support}`}
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">
                      {row.estimated_error_m == null ? "—" : `${fixed(row.estimated_error_m, 0)} m`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Corroborated relative zoom ladder" icon={Scale} action={null}>
        {data.zoomRungs.length === 0 ? (
          <EmptyState
            icon={Scale}
            title="No corroborated zoom rungs yet"
            message="Rungs are learned only from accepted multi-anchor affine fits."
          />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2 font-semibold">Viewport</th>
                  <th className="px-3 py-2 font-semibold">Relative rung</th>
                  <th className="px-3 py-2 font-semibold">Scale</th>
                  <th className="px-3 py-2 font-semibold">Support</th>
                  <th className="px-3 py-2 font-semibold">Dispersion</th>
                  <th className="px-3 py-2 font-semibold">Transfer</th>
                </tr>
              </thead>
              <tbody>
                {data.zoomRungs.map((row) => (
                  <tr key={row.id} className="border-b border-border/50">
                    <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{row.viewport_profile}</td>
                    <td className="px-3 py-2.5 font-mono text-xs text-foreground">{row.zoom_rung}</td>
                    <td className="px-3 py-2.5 font-mono text-xs text-foreground">{fixed(row.scale_m_per_px, 2)} m/px</td>
                    <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{row.support_count}</td>
                    <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{fixed(row.dispersion_log2, 4)} log₂</td>
                    <td className="px-3 py-2.5">
                      <StatusChip
                        tone={row.eligible_for_transfer ? "ready" : "muted"}
                        label={row.eligible_for_transfer ? "eligible" : "evidence only"}
                        icon={null}
                      />
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
