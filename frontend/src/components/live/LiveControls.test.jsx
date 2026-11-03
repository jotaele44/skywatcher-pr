import React from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { SIDE_BUTTONS, SideButtons, TOP_BUTTONS, TopButtons } from "./MapButtons";
import LayerMenu from "./LayerMenu";
import ReplayBar from "./ReplayBar";
import AircraftSidebar from "./AircraftSidebar";
import { DEFAULT_SETTINGS } from "@/live/liveSettings";
import { normalizeAircraft } from "@/live/aircraftModel";

describe("map buttons", () => {
  it("exposes every button from the recording with its adsb.lol meaning", () => {
    const onPress = vi.fn();
    const onReplay = vi.fn();
    render(<TopButtons active={{ T: true }} onPress={onPress} replayOpen={false} onReplay={onReplay} layersOpen={false} onLayers={() => {}} />);
    expect(TOP_BUTTONS.map((b) => b.id)).toEqual(["U", "H", "T"]);
    fireEvent.click(screen.getByRole("button", { name: /only show military/i }));
    expect(onPress).toHaveBeenCalledWith("U");
    expect(screen.getByRole("button", { name: /All \(T\)racks/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: /Repla\(Y\)/ }));
    expect(onReplay).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Map layers" })).toBeInTheDocument();
  });

  it("renders the right-hand column L O K M P I R F plus sidebar, fullscreen, settings and zoom", () => {
    const onPress = vi.fn();
    const onZoom = vi.fn();
    render(<SideButtons active={{}} onPress={onPress} sidebarOpen={false} onSidebar={() => {}} fullscreen={false} onFullscreen={() => {}} settingsOpen={false} onSettings={() => {}} onZoom={onZoom} />);
    expect(SIDE_BUTTONS.filter((b) => !b.spacer).map((b) => b.id)).toEqual(["L", "O", "K", "M", "P", "I", "R", "F"]);
    for (const name of [/Expand aircraft sidebar/, /^Fullscreen$/, /^Settings$/, /\(L\)abels/, /\(F\)ollow/]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("button", { name: /\(I\)solate/ }));
    expect(onPress).toHaveBeenCalledWith("I");
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(onZoom.mock.calls).toEqual([[1], [-1]]);
  });
});

describe("layer menu", () => {
  it("switches base layers, toggles overlays and gates openAIP on its key", () => {
    const onChange = vi.fn();
    render(<LayerMenu settings={{ ...DEFAULT_SETTINGS }} onChange={onChange} onClose={() => {}} openaipConfigured={false} />);
    expect(screen.getByRole("radio", { name: /ESRI\.com Satellite/ })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: /OpenStreetMap DE/ }));
    expect(onChange).toHaveBeenCalledWith({ baseLayer: "osm_de" });
    fireEvent.click(screen.getByRole("checkbox", { name: /NOAA Infrared Sat/ }));
    expect(onChange).toHaveBeenCalledWith({ overlays: ["noaa_sat"] });
    expect(screen.getByRole("checkbox", { name: /openAIP TMS/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Range rings/ }));
    expect(onChange).toHaveBeenLastCalledWith({ features: { ...DEFAULT_SETTINGS.features, rangeRings: false } });
    for (const title of ["DWD RADOLAN", "UK AWACS Orbits", "US ARTCC Boundaries", "RainViewer Radar", "ESRI.com Geography Labels"]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
    fireEvent.change(screen.getByRole("textbox", { name: "Custom tile URL template" }), { target: { value: "https://t.example/{z}/{x}/{y}.png" } });
    fireEvent.click(screen.getByRole("button", { name: "Use custom tiles" }));
    expect(onChange).toHaveBeenLastCalledWith({ customTemplate: "https://t.example/{z}/{x}/{y}.png", baseLayer: "custom_tiles" });
  });
});

describe("replay bar", () => {
  it("shows UTC/AST clocks and drives play, date, hour, minute and speed", () => {
    const handlers = { onPlayPause: vi.fn(), onDate: vi.fn(), onHour: vi.fn(), onMinute: vi.fn(), onSpeed: vi.fn(), onClose: vi.fn() };
    const replay = { ts: Date.parse("2026-11-03T16:01:00Z"), playing: true, speed: 30, loading: true, error: null };
    render(<ReplayBar replay={replay} timeZone="America/Puerto_Rico" {...handlers} />);
    expect(screen.getByText(/UTC: 16:01:00 \/ AST: 12:01:00/)).toBeInTheDocument();
    expect(screen.getByText("AST Date:", { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/Loading/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pause replay" }));
    expect(handlers.onPlayPause).toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Replay date (UTC)"), { target: { value: "2026-11-02" } });
    expect(handlers.onDate).toHaveBeenCalledWith("2026-11-02");
    fireEvent.change(screen.getByLabelText("Replay hour (UTC)"), { target: { value: "9" } });
    expect(handlers.onHour).toHaveBeenCalledWith(9);
    fireEvent.change(screen.getByLabelText("Replay minute (UTC)"), { target: { value: "32" } });
    expect(handlers.onMinute).toHaveBeenCalledWith(32);
    fireEvent.change(screen.getByLabelText("Replay speed"), { target: { value: "10" } });
    expect(handlers.onSpeed).toHaveBeenCalledWith(1000);
  });
});

describe("aircraft sidebar", () => {
  it("lists aircraft, selects rows and shows the selected aircraft details", () => {
    const onSelect = vi.fn();
    const ac = { ...normalizeAircraft({ hex: "a37f12", flight: "AAL1512", t: "B738", alt_baro: 36000, gs: 430, lat: 18.4, lon: -66.1, squawk: "3037" }), distance_nm: 12 };
    render(<AircraftSidebar aircraft={[ac]} selected={new Set(["a37f12"])} details={{ a37f12: { route: "SJU - MIA", traceStatus: "92 points" } }} units="nautical" onSelect={onSelect} onClear={() => {}} following={false} onFollow={() => {}} isolating={false} onIsolate={() => {}} feed={{ status: "available" }} mode="live" />);
    expect(screen.getByText("Live aircraft in view: 1")).toBeInTheDocument();
    expect(screen.getByText("SJU - MIA")).toBeInTheDocument();
    expect(screen.getByText("92 points")).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("AAL1512")[1]);
    expect(onSelect).toHaveBeenCalledWith("a37f12", { additive: false });
  });

  it("explains an unavailable feed instead of showing an empty table", () => {
    render(<AircraftSidebar aircraft={[]} selected={new Set()} details={{}} units="nautical" onSelect={() => {}} onClear={() => {}} feed={{ status: "upstream_unavailable", reason: "timeout" }} mode="live" />);
    expect(screen.getByText("Feed unavailable: timeout")).toBeInTheDocument();
  });
});
