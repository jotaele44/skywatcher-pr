import React from "react";
import { ChevronLeft, ChevronRight, Expand, Layers, Minus, Play, Plus, Settings, Shrink } from "lucide-react";

// Letter buttons with the same keys and meanings as the adsb.lol map.
export const TOP_BUTTONS = Object.freeze([
  { id: "U", title: "(U) Only show military aircraft" },
  { id: "H", title: "(H)ome / reset map" },
  { id: "T", title: "All (T)racks" },
]);

export const SIDE_BUTTONS = Object.freeze([
  { id: "L", title: "Toggle (L)abels" },
  { id: "O", title: "Toggle label extensi(O)ns" },
  { id: "K", title: "Toggle trac(K) labels" },
  { spacer: true },
  { id: "M", title: "Toggle (M)ulti-select" },
  { spacer: true },
  { id: "P", title: "(P)ersistence mode" },
  { id: "I", title: "(I)solate: only show selected aircraft" },
  { spacer: true },
  { id: "R", title: "Follow a (R)andom aircraft" },
  { id: "F", title: "(F)ollow selected aircraft" },
]);

const base = "flex h-9 w-9 items-center justify-center rounded-md border text-sm font-bold shadow-md transition select-none";
const tone = (active) => (active
  ? "border-white/70 bg-white/85 text-slate-900"
  : "border-white/15 bg-slate-700/75 text-slate-100 hover:bg-slate-600/85");

export function MapButton({ label, title, active = false, onClick, children, className = "" }) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      aria-pressed={active}
      onClick={onClick}
      className={`${base} ${tone(active)} ${className}`}
    >
      {children || <span className="font-mono">{label}</span>}
    </button>
  );
}

export function TopButtons({ active, onPress, replayOpen, onReplay, layersOpen, onLayers }) {
  return (
    <div className="pointer-events-auto absolute right-14 top-2 z-20 flex items-center gap-2">
      {TOP_BUTTONS.map((button) => (
        <MapButton key={button.id} label={button.id} title={button.title} active={Boolean(active[button.id])} onClick={() => onPress(button.id)} />
      ))}
      <MapButton title="Repla(Y): show the replay bar" active={replayOpen} onClick={onReplay}>
        <Play className="h-4 w-4" />
      </MapButton>
      <MapButton title="Map layers" active={layersOpen} onClick={onLayers} className="ml-2">
        <Layers className="h-4 w-4" />
      </MapButton>
    </div>
  );
}

export function SideButtons({ active, onPress, sidebarOpen, onSidebar, fullscreen, onFullscreen, settingsOpen, onSettings, onZoom }) {
  return (
    // One column, so the zoom buttons can never overlap the letter buttons on
    // short screens (e.g. a phone with the replay bar open).
    <div className="pointer-events-none absolute bottom-14 right-2 top-2 z-20 flex flex-col items-center gap-1.5">
      <div className="pointer-events-auto flex flex-col items-center gap-1.5">
        <MapButton title={sidebarOpen ? "Collapse aircraft sidebar" : "Expand aircraft sidebar"} active={sidebarOpen} onClick={onSidebar}>
          {sidebarOpen ? <ChevronRight className="h-5 w-5" /> : <ChevronLeft className="h-5 w-5" />}
        </MapButton>
        <MapButton title={fullscreen ? "Exit fullscreen" : "Fullscreen"} active={fullscreen} onClick={onFullscreen}>
          {fullscreen ? <Shrink className="h-4 w-4" /> : <Expand className="h-4 w-4" />}
        </MapButton>
        <MapButton title="Settings" active={settingsOpen} onClick={onSettings}>
          <Settings className="h-4 w-4" />
        </MapButton>
        {SIDE_BUTTONS.map((button, index) => (button.spacer
          ? <div key={`spacer-${index}`} className="h-1.5" aria-hidden="true" />
          : <MapButton key={button.id} label={button.id} title={button.title} active={Boolean(active[button.id])} onClick={() => onPress(button.id)} />
        ))}
      </div>
      <div className="pointer-events-auto mt-auto flex flex-col gap-1.5 pt-1.5">
        <button type="button" aria-label="Zoom in" title="Zoom in" onClick={() => onZoom(1)} className="flex h-9 w-9 items-center justify-center rounded-full border border-white/20 bg-indigo-900/80 text-white shadow-md hover:bg-indigo-800">
          <Plus className="h-5 w-5" />
        </button>
        <button type="button" aria-label="Zoom out" title="Zoom out" onClick={() => onZoom(-1)} className="flex h-9 w-9 items-center justify-center rounded-full border border-white/20 bg-indigo-900/80 text-white shadow-md hover:bg-indigo-800">
          <Minus className="h-5 w-5" />
        </button>
      </div>
    </div>
  );
}
