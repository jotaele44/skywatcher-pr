import React, { useState, useMemo } from "react";
import { TowerControl, Plane, Route as RouteIcon } from "lucide-react";
import { useSkywatcher, useResolvers } from "@/lib/SkywatcherData";
import { useDrawers } from "@/components/skywatcher/drawers/DrawerHub";
import PageHeader from "@/components/skywatcher/PageHeader";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import Panel from "@/components/skywatcher/Panel";
import SyntheticDataBadge from "@/components/skywatcher/SyntheticDataBadge";
import SourceProvenanceBadge from "@/components/skywatcher/SourceProvenanceBadge";
import PuertoRicoMapShell from "@/components/skywatcher/PuertoRicoMapShell";
import EmptyState from "@/components/skywatcher/EmptyState";
import LoadingState from "@/components/skywatcher/LoadingState";
import { Toolbar, SearchInput } from "@/components/skywatcher/Toolbar";

export default function Airports() {
  const d = useSkywatcher();
  const r = useResolvers();
  const { open } = useDrawers();
  const [q, setQ] = useState("");

  const filtered = useMemo(() => {
    let rows = [...d.airports];
    if (q) { const s = q.toLowerCase(); rows = rows.filter((a) => [a.airport_name, a.faa_code, a.icao_code, a.municipality].filter(Boolean).some((v) => v.toLowerCase().includes(s))); }
    return rows;
  }, [d.airports, q]);

  if (d.loading) return <LoadingState />;

  return (
    <div className="space-y-5">
      <PageHeader title="Puerto Rico Airports" subtitle="Public airport registry references & observation context" icon={TowerControl} />
      <DiagnosticNoticeBanner />

      <PuertoRicoMapShell airports={filtered} observations={d.observations} assets={[]} routes={[]} height={280} title="PR Airport Registry Context" />

      <Panel bodyClassName="space-y-4">
        <Toolbar>
          <SearchInput value={q} onChange={setQ} placeholder="Search airport, FAA, ICAO, municipality…" />
        </Toolbar>

        {filtered.length === 0 ? (
          <EmptyState icon={TowerControl} title="No airports" />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border scrollbar-thin">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2 font-semibold">Airport</th>
                  <th className="px-3 py-2 font-semibold">FAA</th>
                  <th className="px-3 py-2 font-semibold">ICAO</th>
                  <th className="px-3 py-2 font-semibold">Municipality</th>
                  <th className="px-3 py-2 font-semibold">Type</th>
                  <th className="px-3 py-2 font-semibold">Obs</th>
                  <th className="px-3 py-2 font-semibold">Linked Aircraft / Routes</th>
                  <th className="px-3 py-2 font-semibold">Source</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((a) => {
                  const obs = r.observationsForAirport(a.airport_id);
                  const aircraftTails = [...new Set(obs.map((o) => o.tail_number))];
                  const routeCount = obs.reduce((n, o) => n + r.routesForObservation(o.observation_id).length, 0);
                  return (
                    <tr key={a.id} className="border-b border-border/50">
                      <td className="px-3 py-2.5"><div className="font-semibold text-foreground">{a.airport_name}</div><div className="mt-0.5"><SyntheticDataBadge synthetic={a.synthetic_flag} /></div></td>
                      <td className="px-3 py-2.5 font-mono text-xs text-primary">{a.faa_code}</td>
                      <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{a.icao_code}</td>
                      <td className="px-3 py-2.5 text-muted-foreground">{a.municipality}</td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground">{a.airport_type}</td>
                      <td className="px-3 py-2.5 font-mono text-xs text-foreground">{obs.length}</td>
                      <td className="px-3 py-2.5">
                        <div className="flex flex-wrap gap-1.5">
                          {aircraftTails.slice(0, 3).map((t) => {
                            const ac = r.aircraftByTail(t);
                            return ac ? (
                              <button key={t} onClick={() => open.aircraft(ac.aircraft_id)} className="inline-flex items-center gap-1 rounded border border-border bg-secondary/60 px-1.5 py-0.5 font-mono text-[10px] text-foreground/80 hover:text-primary"><Plane className="h-2.5 w-2.5" />{t}</button>
                            ) : null;
                          })}
                          {routeCount > 0 && <span className="inline-flex items-center gap-1 rounded border border-border bg-secondary/60 px-1.5 py-0.5 text-[10px] text-muted-foreground"><RouteIcon className="h-2.5 w-2.5" />{routeCount}</span>}
                          {aircraftTails.length === 0 && <span className="text-[10px] text-muted-foreground">—</span>}
                        </div>
                      </td>
                      <td className="px-3 py-2.5"><SourceProvenanceBadge source="registry_match" /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}