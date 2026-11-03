import React, { useState } from "react";
import { X } from "lucide-react";
import { UNIT_SYSTEMS } from "@/live/aircraftModel";
import { DEFAULT_SETTINGS } from "@/live/liveSettings";

export default function SettingsPanel({ settings, onChange, onSetHome, onReset, onClose, timeZone }) {
  const [ringsDraft, setRingsDraft] = useState(settings.rangeRings.join(", "));
  const unit = UNIT_SYSTEMS[settings.units].distance;
  const applyRings = () => {
    const values = ringsDraft.split(/[,\s]+/).map(Number).filter((n) => Number.isFinite(n) && n > 0);
    onChange({ rangeRings: values.length ? values : DEFAULT_SETTINGS.rangeRings });
  };
  return (
    <div role="dialog" aria-label="Map settings" className="pointer-events-auto absolute right-14 top-12 z-30 w-72 rounded-md border border-white/10 bg-[#283048]/95 p-3 text-[13px] text-slate-100 shadow-xl">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="font-bold">Settings</h2>
        <button type="button" onClick={onClose} aria-label="Close settings" className="rounded p-1 hover:bg-white/10"><X className="h-4 w-4" /></button>
      </div>
      <div className="space-y-3">
        <fieldset>
          <legend className="mb-1 text-slate-300">Units</legend>
          <div className="flex gap-3">
            {Object.keys(UNIT_SYSTEMS).map((key) => (
              <label key={key} className="flex items-center gap-1 capitalize">
                <input type="radio" name="live-units" checked={settings.units === key} onChange={() => onChange({ units: key })} className="accent-indigo-400" />{key}
              </label>
            ))}
          </div>
        </fieldset>
        <div>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={settings.mapDim} onChange={(e) => onChange({ mapDim: e.target.checked })} className="accent-indigo-400" />
            Dim map (B)
          </label>
          <input type="range" min={0} max={0.9} step={0.05} value={settings.mapDimAmount} disabled={!settings.mapDim} onChange={(e) => onChange({ mapDimAmount: Number(e.target.value) })} aria-label="Map dim amount" className="mt-1 w-full accent-indigo-400" />
        </div>
        <div>
          <label className="text-slate-300" htmlFor="live-rings">Range rings ({unit})</label>
          <div className="mt-1 flex gap-1">
            <input id="live-rings" value={ringsDraft} onChange={(e) => setRingsDraft(e.target.value)} className="w-full rounded border border-white/20 bg-slate-900/70 px-1.5 py-0.5" />
            <button type="button" onClick={applyRings} className="rounded border border-white/20 px-2 hover:bg-white/10">Apply</button>
          </div>
        </div>
        <div>
          <label className="text-slate-300" htmlFor="live-refresh">Live refresh interval (s)</label>
          <input id="live-refresh" type="number" min={2} max={60} value={settings.refreshS} onChange={(e) => onChange({ refreshS: Number(e.target.value) })} className="mt-1 w-20 rounded border border-white/20 bg-slate-900/70 px-1.5 py-0.5" />
        </div>
        <div>
          <label className="text-slate-300" htmlFor="live-tz">Local time zone (IANA)</label>
          <input id="live-tz" value={settings.timeZone} placeholder={timeZone} onChange={(e) => onChange({ timeZone: e.target.value })} className="mt-1 w-full rounded border border-white/20 bg-slate-900/70 px-1.5 py-0.5" />
        </div>
        <div className="flex flex-wrap gap-1.5">
          <button type="button" onClick={onSetHome} className="rounded border border-white/20 px-2 py-0.5 hover:bg-white/10">Set home to current view</button>
          <button type="button" onClick={onReset} className="rounded border border-white/20 px-2 py-0.5 hover:bg-white/10">Reset settings</button>
        </div>
      </div>
    </div>
  );
}
