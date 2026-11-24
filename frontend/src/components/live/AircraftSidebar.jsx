import React, { useMemo, useState } from "react";
import { X } from "lucide-react";
import {
  altitudeColor, callsignOf, formatAltitude, formatDistanceNm, formatSpeed, sortAircraft,
} from "@/live/aircraftModel";

const COLUMNS = [
  { id: "flight", label: "Callsign" },
  { id: "type", label: "Type" },
  { id: "squawk", label: "Sqk" },
  { id: "altitude", label: "Alt" },
  { id: "speed", label: "Spd" },
  { id: "distance", label: "Dist" },
  { id: "track", label: "Hdg" },
];

function Row({ label, value }) {
  return (
    <div className="flex justify-between gap-2 border-b border-white/5 py-0.5">
      <dt className="text-slate-400">{label}</dt>
      <dd className="text-right font-mono">{value ?? "n/a"}</dd>
    </div>
  );
}

function SelectedDetails({ ac, details, units, onClear, onFollow, following, onIsolate, isolating }) {
  const time = ac.updated_ms ? new Date(ac.updated_ms).toISOString().slice(11, 19) : null;
  return (
    <section aria-label="Selected aircraft" className="border-b border-white/10 p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-lg font-bold leading-tight">{callsignOf(ac)}</p>
          <p className="text-[11px] text-slate-400">
            {[ac.registration, ac.type, ac.military ? "military" : null].filter(Boolean).join(" · ") || ac.hex}
          </p>
          {ac.description && <p className="text-[11px] text-slate-400">{ac.description}</p>}
        </div>
        <button type="button" onClick={onClear} aria-label="Clear selection" className="rounded p-1 hover:bg-white/10"><X className="h-4 w-4" /></button>
      </div>
      <dl className="mt-2 text-[12px]">
        <Row label="Hex" value={ac.hex?.toUpperCase()} />
        <Row label="Squawk" value={ac.squawk} />
        <Row label="Altitude" value={formatAltitude(ac.alt_baro, units)} />
        <Row label="Geom. altitude" value={formatAltitude(ac.alt_geom, units)} />
        <Row label="Ground speed" value={formatSpeed(ac.gs, units)} />
        <Row label="Vertical rate" value={typeof ac.baro_rate === "number" ? `${ac.baro_rate} ft/min` : null} />
        <Row label="Track" value={typeof ac.track === "number" ? `${Math.round(ac.track)}°` : null} />
        <Row label="Position" value={ac.lat !== null ? `${ac.lat.toFixed(4)}, ${ac.lon.toFixed(4)}` : null} />
        <Row label="Source" value={ac.source_type} />
        <Row label="Operator" value={ac.operator} />
        <Row label="Route" value={details?.route || (details?.routeStatus === "loading" ? "loading…" : null)} />
        <Row label="Trace" value={details?.traceStatus} />
        <Row label="Last position (UTC)" value={time} />
        {ac.stale && <Row label="State" value="stale (not in latest feed)" />}
      </dl>
      <div className="mt-2 flex gap-1.5 text-[12px]">
        <button type="button" onClick={onFollow} aria-pressed={following} className={`rounded border px-2 py-0.5 ${following ? "border-white bg-white text-slate-900" : "border-white/20 hover:bg-white/10"}`}>Follow</button>
        <button type="button" onClick={onIsolate} aria-pressed={isolating} className={`rounded border px-2 py-0.5 ${isolating ? "border-white bg-white text-slate-900" : "border-white/20 hover:bg-white/10"}`}>Isolate</button>
      </div>
    </section>
  );
}

export default function AircraftSidebar({ aircraft, selected, details, units, onSelect, onClear, following, onFollow, isolating, onIsolate, feed, mode }) {
  const [sort, setSort] = useState({ column: "distance", direction: "asc" });
  const rows = useMemo(() => sortAircraft(aircraft, sort.column, sort.direction), [aircraft, sort]);
  const selectedAircraft = aircraft.filter((ac) => selected.has(ac.hex));
  const toggleSort = (column) => setSort((current) => ({
    column,
    direction: current.column === column && current.direction === "asc" ? "desc" : "asc",
  }));

  return (
    <aside aria-label="Aircraft list" className="flex h-full w-full flex-col bg-[#1b2130] text-slate-100 md:w-[380px] md:border-l md:border-white/10">
      <header className="border-b border-white/10 px-3 py-2">
        <p className="text-sm font-bold">{mode === "replay" ? "Replay" : "Live"} aircraft in view: {aircraft.length}</p>
        <p className="text-[11px] text-slate-400">
          Data: adsb.lol contributors (ODbL 1.0){feed?.fetchedAt ? ` · updated ${feed.fetchedAt.slice(11, 19)}Z` : ""}
        </p>
      </header>
      {selectedAircraft.map((ac) => (
        <SelectedDetails
          key={ac.hex}
          ac={ac}
          details={details[ac.hex]}
          units={units}
          onClear={onClear}
          onFollow={onFollow}
          following={following}
          onIsolate={onIsolate}
          isolating={isolating}
        />
      )).slice(0, 1)}
      {selectedAircraft.length > 1 && <p className="border-b border-white/10 px-3 py-1 text-[11px] text-slate-400">{selectedAircraft.length} aircraft selected</p>}
      <div className="min-h-0 flex-1 overflow-auto scrollbar-thin">
        <table className="w-full text-[12px]">
          <thead className="sticky top-0 bg-[#283048] text-left">
            <tr>
              {COLUMNS.map((column) => (
                <th key={column.id} className="px-1.5 py-1 font-semibold">
                  <button type="button" onClick={() => toggleSort(column.id)} className="hover:underline" aria-label={`Sort by ${column.label}`}>
                    {column.label}{sort.column === column.id ? (sort.direction === "asc" ? " ▲" : " ▼") : ""}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((ac) => (
              <tr
                key={ac.hex}
                onClick={(event) => onSelect(ac.hex, { additive: event.ctrlKey || event.metaKey })}
                className={`cursor-pointer border-b border-white/5 ${selected.has(ac.hex) ? "bg-indigo-500/30" : "hover:bg-white/5"} ${ac.stale ? "opacity-60" : ""}`}
              >
                <td className="px-1.5 py-0.5 font-mono">
                  <span className="mr-1 inline-block h-2 w-2 rounded-full align-middle" style={{ background: altitudeColor(ac.alt_baro) }} />
                  {callsignOf(ac)}
                </td>
                <td className="px-1.5 py-0.5">{ac.type || ""}</td>
                <td className={`px-1.5 py-0.5 font-mono ${["7500", "7600", "7700"].includes(ac.squawk) ? "text-red-400" : ""}`}>{ac.squawk || ""}</td>
                <td className="px-1.5 py-0.5 text-right font-mono">{ac.alt_baro === "ground" ? "GND" : typeof ac.alt_baro === "number" ? formatAltitude(ac.alt_baro, units).replace(/ (ft|m)$/, "") : ""}</td>
                <td className="px-1.5 py-0.5 text-right font-mono">{typeof ac.gs === "number" ? formatSpeed(ac.gs, units).split(" ")[0] : ""}</td>
                <td className="px-1.5 py-0.5 text-right font-mono">{typeof ac.distance_nm === "number" ? formatDistanceNm(ac.distance_nm, units).split(" ")[0] : ""}</td>
                <td className="px-1.5 py-0.5 text-right font-mono">{typeof ac.track === "number" ? Math.round(ac.track) : ""}</td>
              </tr>
            ))}
            {!rows.length && (
              <tr><td colSpan={COLUMNS.length} className="px-3 py-4 text-center text-slate-400">{feed?.status === "upstream_unavailable" ? `Feed unavailable: ${feed.reason}` : "No aircraft in view."}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </aside>
  );
}
