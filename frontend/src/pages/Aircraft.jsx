import React, { useState, useMemo } from "react";
import { IdCard, LayoutGrid, List } from "lucide-react";
import { useSkywatcher, useResolvers } from "@/lib/SkywatcherData";
import { useDrawers } from "@/components/skywatcher/drawers/DrawerHub";
import PageHeader from "@/components/skywatcher/PageHeader";
import AircraftFleetSummary from "@/components/skywatcher/AircraftFleetSummary";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import Panel from "@/components/skywatcher/Panel";
import AircraftProfileCard from "@/components/skywatcher/AircraftProfileCard";
import ConfidenceBadge from "@/components/skywatcher/ConfidenceBadge";
import SyntheticDataBadge from "@/components/skywatcher/SyntheticDataBadge";
import EmptyState from "@/components/skywatcher/EmptyState";
import LoadingState from "@/components/skywatcher/LoadingState";
import { Toolbar, SearchInput, FilterSelect } from "@/components/skywatcher/Toolbar";

export default function Aircraft() {
  const d = useSkywatcher();
  const { open } = useDrawers();
  const { linksForAircraftTail } = useResolvers();
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("all");
  const [view, setView] = useState("cards");

  const categories = useMemo(() => {
    const set = new Set(d.aircraft.map((a) => a.operator_category).filter(Boolean));
    return [{ value: "all", label: "All operator categories" }, ...[...set].map((c) => ({ value: c, label: c }))];
  }, [d.aircraft]);

  const filtered = useMemo(() => {
    let rows = [...d.aircraft];
    if (q) {
      const s = q.toLowerCase();
      rows = rows.filter((a) => [a.callsign, a.tail_number, a.operator_name, a.mission_category].filter(Boolean).some((v) => v.toLowerCase().includes(s)));
    }
    if (cat !== "all") rows = rows.filter((a) => a.operator_category === cat);
    return rows.sort((a, b) => new Date(b.last_seen_at) - new Date(a.last_seen_at));
  }, [d.aircraft, q, cat]);

  if (d.loading) return <LoadingState />;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Aircraft Profiles"
        subtitle="Registry-derived diagnostic aircraft profiles & observation history"
        icon={IdCard}
        actions={
          <div className="flex items-center gap-1 rounded-lg border border-border bg-card p-1">
            <button onClick={() => setView("cards")} className={`flex items-center gap-1 rounded px-2.5 py-1 text-xs font-semibold ${view === "cards" ? "bg-primary/15 text-primary" : "text-muted-foreground"}`}><LayoutGrid className="h-3.5 w-3.5" /> Cards</button>
            <button onClick={() => setView("table")} className={`flex items-center gap-1 rounded px-2.5 py-1 text-xs font-semibold ${view === "table" ? "bg-primary/15 text-primary" : "text-muted-foreground"}`}><List className="h-3.5 w-3.5" /> Table</button>
          </div>
        }
      />
      <DiagnosticNoticeBanner />

      <AircraftFleetSummary aircraft={d.aircraft} linksForAircraftTail={linksForAircraftTail} />

      <Panel bodyClassName="space-y-4">
        <Toolbar>
          <SearchInput value={q} onChange={setQ} placeholder="Search callsign or tail number…" />
          <FilterSelect value={cat} onChange={setCat} options={categories} label="Operator category" />
        </Toolbar>

        {filtered.length === 0 ? (
          <EmptyState icon={IdCard} title="No aircraft profiles" />
        ) : view === "cards" ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((a) => <AircraftProfileCard key={a.id} aircraft={a} onOpen={() => open.aircraft(a.aircraft_id)} />)}
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border scrollbar-thin">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2 font-semibold">Callsign / Tail</th>
                  <th className="px-3 py-2 font-semibold">Type</th>
                  <th className="px-3 py-2 font-semibold">Operator Cat</th>
                  <th className="px-3 py-2 font-semibold">Mission</th>
                  <th className="px-3 py-2 font-semibold">Last Seen</th>
                  <th className="px-3 py-2 font-semibold">Obs</th>
                  <th className="px-3 py-2 font-semibold">Conf</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((a) => (
                  <tr key={a.id} onClick={() => open.aircraft(a.aircraft_id)} className="cursor-pointer border-b border-border/50 transition hover:bg-secondary/40">
                    <td className="px-3 py-2.5"><div className="font-mono font-semibold text-foreground">{a.callsign}</div><div className="mt-0.5"><SyntheticDataBadge synthetic={a.synthetic_flag} /></div></td>
                    <td className="px-3 py-2.5 text-muted-foreground">{a.aircraft_type}</td>
                    <td className="px-3 py-2.5 text-muted-foreground">{a.operator_category}</td>
                    <td className="px-3 py-2.5"><span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] text-primary">{a.mission_category}</span></td>
                    <td className="px-3 py-2.5 text-xs text-muted-foreground">{a.last_seen_at ? new Date(a.last_seen_at).toLocaleDateString() : "—"}</td>
                    <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{a.observation_count}</td>
                    <td className="px-3 py-2.5"><ConfidenceBadge score={a.profile_confidence} showBar={false} /></td>
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