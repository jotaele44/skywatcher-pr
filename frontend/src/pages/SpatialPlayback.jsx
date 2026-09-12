import React, { useMemo, useState } from "react";
import { ExternalLink, Play, Waves } from "lucide-react";
import PageHeader from "@/components/skywatcher/PageHeader";
import Panel from "@/components/skywatcher/Panel";
import PuertoRicoMapShell from "@/components/skywatcher/PuertoRicoMapShell";
import StatusChip from "@/components/skywatcher/StatusChip";
import { C6062_SOURCE, C6062_SPATIAL_FIXTURE } from "@/data/c6062SpatialFixture";

export default function SpatialPlayback() {
  const [index, setIndex] = useState(0);
  const item = C6062_SPATIAL_FIXTURE[index];
  const observations = useMemo(() => C6062_SPATIAL_FIXTURE.map((row) => ({ id: row.observationId, latitude: row.lat, longitude: row.lon, callsign: "C6062", position_error_m: 7000 })), []);
  const spiderwebBase = import.meta.env.VITE_SPIDERWEB_URL || "https://github.com/jotaele44/spiderweb-pr";
  const handoff = `${spiderwebBase.replace(/\/$/, "")}/spatial-workbench?subject_id=${encodeURIComponent(item.observationId)}&analysis_id=${encodeURIComponent(item.analysisId)}&result_hash=${item.resultHash}`;

  return <div className="space-y-5">
    <PageHeader title="Land / Ocean Playback" subtitle="Aircraft playback with Spiderweb-authoritative surface context" icon={Waves} />
    <PuertoRicoMapShell observations={observations} routes={[]} airports={[]} assets={[]} height={300} title="C6062 real-observation fixture" />
    <Panel title="Playback" icon={Play}>
      <label htmlFor="spatial-playback-step" className="text-xs font-semibold text-muted-foreground">Observation {index + 1} of {C6062_SPATIAL_FIXTURE.length}</label>
      <input id="spatial-playback-step" aria-label="Playback observation" className="mt-3 w-full accent-cyan-400" type="range" min="0" max={C6062_SPATIAL_FIXTURE.length - 1} value={index} onChange={(event) => setIndex(Number(event.target.value))} />
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="UTC" value={item.time} />
        <Metric label="Aircraft altitude" value={`${item.altitudeFt.toLocaleString()} ft`} />
        <Metric label="Seafloor elevation" value={`${item.depthM.toFixed(1)} m`} />
        <Metric label="Position uncertainty" value="7,000 m" />
      </div>
    </Panel>
    <div className="grid gap-5 lg:grid-cols-2">
      <Panel title="Spiderweb context">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="text-muted-foreground">Surface</dt><dd>Ocean depth</dd>
          <dt className="text-muted-foreground">Spatial state</dt><dd><StatusChip tone="ready" label="FULLY_WITHIN" /></dd>
          <dt className="text-muted-foreground">Measurement</dt><dd>{C6062_SOURCE.measurementClass}</dd>
          <dt className="text-muted-foreground">Resolution</dt><dd>{C6062_SOURCE.resolution}</dd>
          <dt className="text-muted-foreground">Vertical datum</dt><dd>{C6062_SOURCE.verticalDatum}</dd>
          <dt className="text-muted-foreground">Feature identity</dt><dd>UNRESOLVED</dd>
        </dl>
        <a className="mt-4 inline-flex items-center gap-2 rounded-md border border-primary/30 px-3 py-2 text-sm text-primary hover:bg-primary/10" href={handoff}>Open in Spiderweb <ExternalLink className="h-4 w-4" /></a>
      </Panel>
      <Panel title="Timeline and sensor gate">
        <ol className="space-y-3 text-sm">
          <li><span className="font-mono text-xs text-primary">{item.time}</span><p>OVER_OCEAN_DEPTH — derived spatial event</p></li>
          <li><StatusChip tone="warn" label="SENSOR FOOTPRINT UNRESOLVED" /><p className="mt-1 text-xs text-muted-foreground">Sensor azimuth, elevation and field of view are absent. No footprint or intersection was synthesized.</p></li>
        </ol>
      </Panel>
    </div>
    <Panel title="Frozen provenance">
      <p className="break-all font-mono text-xs text-muted-foreground">source: {C6062_SOURCE.manifestationId}</p>
      <p className="mt-1 break-all font-mono text-xs text-muted-foreground">raster SHA-256: {C6062_SOURCE.rasterSha256}</p>
      <p className="mt-1 break-all font-mono text-xs text-muted-foreground">result SHA-256: {item.resultHash}</p>
    </Panel>
  </div>;
}

function Metric({ label, value }) {
  return <div className="rounded-lg border border-border bg-secondary/30 p-3"><p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p><p className="mt-1 font-mono text-sm text-foreground">{value}</p></div>;
}
