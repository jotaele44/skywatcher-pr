import React, { useState, useMemo } from "react";
import { Plane, CheckCircle2, Flag, X, Loader2 } from "lucide-react";
import { useSkywatcher } from "@/lib/SkywatcherData";
import { useDrawers } from "@/components/skywatcher/drawers/DrawerHub";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/use-toast";
import PageHeader from "@/components/skywatcher/PageHeader";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import Panel from "@/components/skywatcher/Panel";
import StatusChip from "@/components/skywatcher/StatusChip";
import ConfidenceBadge from "@/components/skywatcher/ConfidenceBadge";
import SyntheticDataBadge from "@/components/skywatcher/SyntheticDataBadge";
import SourceProvenanceBadge from "@/components/skywatcher/SourceProvenanceBadge";
import PuertoRicoMapShell from "@/components/skywatcher/PuertoRicoMapShell";
import EmptyState from "@/components/skywatcher/EmptyState";
import LoadingState from "@/components/skywatcher/LoadingState";
import { Toolbar, SearchInput, FilterSelect } from "@/components/skywatcher/Toolbar";
import { REVIEW_STATUS } from "@/lib/skywatcher";

const REVIEW_OPTS = [
  { value: "all", label: "All review states" },
  { value: "new", label: "New" }, { value: "triaged", label: "Triaged" },
  { value: "needs_review", label: "Needs Review" }, { value: "verified", label: "Verified" },
  { value: "rejected", label: "Rejected" },
];
const SOURCE_OPTS = [
  { value: "all", label: "All sources" },
  { value: "synthetic_example", label: "Synthetic Example" },
  { value: "fr24_screenshot", label: "FR24 Screenshot" },
  { value: "fr24_track", label: "FR24 Track" },
  { value: "manual_entry", label: "Manual Entry" },
  { value: "registry_match", label: "Registry Match" },
];
const SYNTH_OPTS = [
  { value: "all", label: "Synthetic & live" },
  { value: "synthetic", label: "Synthetic only" },
  { value: "live", label: "Live only" },
];
const CONF_OPTS = [
  { value: "all", label: "All confidence" },
  { value: "high", label: "High (≥75%)" },
  { value: "medium", label: "Medium (50–74%)" },
  { value: "low", label: "Low (<50%)" },
];
const SORT_OPTS = [
  { value: "time", label: "Sort: Newest" },
  { value: "confidence", label: "Sort: Confidence" },
  { value: "distance", label: "Sort: Distance to asset" },
];

export default function Observations() {
  const d = useSkywatcher();
  const { open } = useDrawers();
  const { toast } = useToast();
  const [q, setQ] = useState("");
  const [review, setReview] = useState("all");
  const [source, setSource] = useState("all");
  const [synth, setSynth] = useState("all");
  const [conf, setConf] = useState("all");
  const [sort, setSort] = useState("time");
  const [selected, setSelected] = useState(() => new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  const filtered = useMemo(() => {
    let rows = [...d.observations];
    if (q) {
      const s = q.toLowerCase();
      rows = rows.filter((o) =>
        [o.callsign, o.tail_number, o.operator_name, o.nearest_airport_name, o.nearest_asset_name, o.mission_inference]
          .filter(Boolean).some((v) => v.toLowerCase().includes(s)));
    }
    if (review !== "all") rows = rows.filter((o) => o.review_status === review);
    if (source !== "all") rows = rows.filter((o) => o.source_type === source);
    if (synth === "synthetic") rows = rows.filter((o) => o.synthetic_flag);
    if (synth === "live") rows = rows.filter((o) => !o.synthetic_flag);
    if (conf === "high") rows = rows.filter((o) => (o.confidence_score ?? 0) >= 0.75);
    if (conf === "medium") rows = rows.filter((o) => (o.confidence_score ?? 0) >= 0.5 && (o.confidence_score ?? 0) < 0.75);
    if (conf === "low") rows = rows.filter((o) => (o.confidence_score ?? 0) < 0.5);

    if (sort === "time") rows.sort((a, b) => new Date(b.observed_at) - new Date(a.observed_at));
    if (sort === "confidence") rows.sort((a, b) => (b.confidence_score ?? 0) - (a.confidence_score ?? 0));
    if (sort === "distance") rows.sort((a, b) => (a.distance_nm ?? 999) - (b.distance_nm ?? 999));
    return rows;
  }, [d.observations, q, review, source, synth, conf, sort]);

  const filteredIds = filtered.map((o) => o.id);
  const allSelected = filteredIds.length > 0 && filteredIds.every((id) => selected.has(id));
  const someSelected = selected.size > 0;

  const toggleRow = (id) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const toggleAll = () =>
    setSelected((prev) => {
      if (filteredIds.every((id) => prev.has(id))) {
        const next = new Set(prev);
        filteredIds.forEach((id) => next.delete(id));
        return next;
      }
      return new Set([...prev, ...filteredIds]);
    });

  const applyBulk = async (status, verb) => {
    const ids = [...selected];
    if (!ids.length) return;
    setBulkBusy(true);
    for (const id of ids) {
      await d.updateRecord("observations", id, { review_status: status });
    }
    setBulkBusy(false);
    setSelected(new Set());
    toast({ title: `${ids.length} observation${ids.length > 1 ? "s" : ""} ${verb}`, description: "Diagnostic review status updated." });
  };

  if (d.loading) return <LoadingState />;

  return (
    <div className="space-y-5">
      <PageHeader title="Airspace Observations" subtitle="FR24-derived & registry observations across Puerto Rico airspace" icon={Plane} />
      <DiagnosticNoticeBanner />

      <PuertoRicoMapShell observations={filtered} airports={d.airports} assets={d.assets} height={260} title="Filtered Observation Context" />

      <Panel bodyClassName="space-y-4">
        <Toolbar>
          <SearchInput value={q} onChange={setQ} placeholder="Search callsign, tail, operator, airport, asset…" />
          <FilterSelect value={review} onChange={setReview} options={REVIEW_OPTS} label="Review status" />
          <FilterSelect value={source} onChange={setSource} options={SOURCE_OPTS} label="Source type" />
          <FilterSelect value={synth} onChange={setSynth} options={SYNTH_OPTS} label="Synthetic flag" />
          <FilterSelect value={conf} onChange={setConf} options={CONF_OPTS} label="Confidence" />
          <FilterSelect value={sort} onChange={setSort} options={SORT_OPTS} label="Sort" />
        </Toolbar>

        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{filtered.length} of {d.observations.length} observations</span>
          <SyntheticDataBadge />
        </div>

        {someSelected && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-primary/30 bg-primary/10 px-3 py-2">
            <span className="text-sm font-semibold text-primary">{selected.size} selected</span>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <Button size="sm" disabled={bulkBusy} onClick={() => applyBulk("verified", "approved")}
                className="h-8 bg-[hsl(142_70%_40%)] text-white hover:bg-[hsl(142_70%_34%)]">
                {bulkBusy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />}
                Approve
              </Button>
              <Button size="sm" variant="outline" disabled={bulkBusy} onClick={() => applyBulk("needs_review", "flagged")}
                className="h-8 border-[hsl(38_100%_50%/0.5)] text-[hsl(38_100%_64%)] hover:bg-[hsl(38_100%_50%/0.12)]">
                {bulkBusy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Flag className="mr-1.5 h-3.5 w-3.5" />}
                Flag for review
              </Button>
              <Button size="sm" variant="ghost" disabled={bulkBusy} onClick={() => setSelected(new Set())} className="h-8 text-muted-foreground">
                <X className="mr-1.5 h-3.5 w-3.5" /> Clear
              </Button>
            </div>
          </div>
        )}

        {filtered.length === 0 ? (
          <EmptyState icon={Plane} title="No matching observations" message="Adjust filters or search to surface diagnostic observations." />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border scrollbar-thin">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                  <th className="w-10 px-3 py-2">
                    <Checkbox checked={allSelected} onCheckedChange={toggleAll} aria-label="Select all" />
                  </th>
                  <th className="px-3 py-2 font-semibold">Callsign / Tail</th>
                  <th className="px-3 py-2 font-semibold">Aircraft</th>
                  <th className="px-3 py-2 font-semibold">Mission</th>
                  <th className="px-3 py-2 font-semibold">Nearest Asset</th>
                  <th className="px-3 py-2 font-semibold">Dist</th>
                  <th className="px-3 py-2 font-semibold">Source</th>
                  <th className="px-3 py-2 font-semibold">Conf</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((o) => {
                  const rs = REVIEW_STATUS[o.review_status] || REVIEW_STATUS.new;
                  return (
                    <tr key={o.id} onClick={() => open.observation(o.observation_id)}
                      className={`cursor-pointer border-b border-border/50 transition hover:bg-secondary/40 ${selected.has(o.id) ? "bg-primary/5" : ""}`}>
                      <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                        <Checkbox checked={selected.has(o.id)} onCheckedChange={() => toggleRow(o.id)} aria-label="Select observation" />
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="font-mono font-semibold text-foreground">{o.callsign}</div>
                        <div className="font-mono text-[10px] text-muted-foreground">{o.tail_number}</div>
                      </td>
                      <td className="px-3 py-2.5 text-muted-foreground">{o.aircraft_type}</td>
                      <td className="px-3 py-2.5"><span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] text-primary">{o.mission_inference}</span></td>
                      <td className="px-3 py-2.5 text-muted-foreground">{o.nearest_asset_name || o.nearest_airport_name}</td>
                      <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{o.distance_nm} nm</td>
                      <td className="px-3 py-2.5"><SourceProvenanceBadge source={o.source_type} /></td>
                      <td className="px-3 py-2.5"><ConfidenceBadge score={o.confidence_score} showBar={false} /></td>
                      <td className="px-3 py-2.5"><div className="flex flex-col items-start gap-1"><StatusChip tone={rs.tone} label={rs.label} /><SyntheticDataBadge synthetic={o.synthetic_flag} /></div></td>
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