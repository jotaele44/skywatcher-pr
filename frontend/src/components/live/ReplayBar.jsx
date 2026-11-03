import React from "react";
import {
  SPEED_SLIDER, localClock, localDate, sliderFromSpeed, speedFromSlider, timeZoneAbbreviation, utcClock, utcParts,
} from "@/live/replayModel";

// Three rows, as on the adsb.lol replay bar:
//   UTC Date | date        | UTC clock / local clock | Speed
//   Play     | date picker | hour slider             | speed slider
//   local date             | minute slider           | loading / error
export default function ReplayBar({ replay, timeZone, onPlayPause, onDate, onHour, onMinute, onSpeed, onClose }) {
  const ts = replay.ts;
  const parts = utcParts(ts);
  const zone = timeZoneAbbreviation(ts, timeZone);
  return (
    <div role="region" aria-label="Replay controls" className="z-30 shrink-0 border-t border-white/10 bg-[#283048]/95 px-2 py-1.5 text-[12px] text-slate-100 shadow-2xl sm:px-3 sm:text-[13px]">
      <div className="grid grid-cols-[4.25rem_7.5rem_minmax(0,1fr)_4rem] items-center gap-x-2 gap-y-1.5">
        <div className="leading-tight text-slate-300">UTC<br />Date:</div>
        <div className="font-mono">{parts.date}</div>
        <div className="font-mono leading-tight" aria-live="polite">
          UTC: {utcClock(ts)} /<br className="sm:hidden" /> {zone}: {localClock(ts, timeZone)}
        </div>
        <div className="leading-tight text-slate-300">Speed:<br /><span className="font-mono text-slate-100">{replay.speed}x</span></div>

        <button type="button" onClick={onPlayPause} className="rounded-full bg-slate-200 px-2 py-1 font-medium text-slate-900 hover:bg-white" aria-label={replay.playing ? "Pause replay" : "Play replay"}>
          {replay.playing ? "Pause" : "Play"}
        </button>
        <input type="date" value={parts.date} max={new Date().toISOString().slice(0, 10)} onChange={(e) => onDate(e.target.value)} aria-label="Replay date (UTC)" className="w-full min-w-0 rounded border border-white/20 bg-slate-300 px-1 py-0.5 text-[12px] text-slate-700" />
        <input type="range" min={0} max={23} step={1} value={parts.hours} onChange={(e) => onHour(Number(e.target.value))} aria-label="Replay hour (UTC)" className="w-full min-w-0 accent-indigo-400" />
        <input type="range" min={SPEED_SLIDER.min} max={SPEED_SLIDER.max} step={SPEED_SLIDER.step} value={sliderFromSpeed(replay.speed)} onChange={(e) => onSpeed(speedFromSlider(e.target.value))} aria-label="Replay speed" className="w-full min-w-0 accent-indigo-400" />

        <div className="col-span-2 leading-tight text-slate-300">{zone} Date:<br /><span className="font-mono text-slate-100">{localDate(ts, timeZone)}</span></div>
        <input type="range" min={0} max={59} step={1} value={parts.minutes} onChange={(e) => onMinute(Number(e.target.value))} aria-label="Replay minute (UTC)" className="w-full min-w-0 accent-indigo-400" />
        <div className="text-[11px] leading-tight">
          {replay.loading && <span>Loading …</span>}
          {!replay.loading && replay.error && <span className="text-amber-300">{replay.error}</span>}
          {!replay.loading && !replay.error && (
            <button type="button" onClick={onClose} className="rounded border border-white/20 px-1.5 py-0.5 text-slate-300 hover:bg-white/10" aria-label="Close replay and return to live">Live</button>
          )}
        </div>
      </div>
    </div>
  );
}
