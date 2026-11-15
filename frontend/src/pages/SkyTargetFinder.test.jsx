import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import SkyTargetFinder from "./SkyTargetFinder";

const { skyTargets, skyRecommend, skyChart, toast } = vi.hoisted(() => ({
  skyTargets: vi.fn(),
  skyRecommend: vi.fn(),
  skyChart: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("@/api/federationClient", () => ({
  federation: { spaceTrack: { skyTargets, skyRecommend, skyChart } },
}));
vi.mock("@/components/ui/use-toast", () => ({ toast }));

const OBSERVER = { lat_deg: 18.4655, lon_deg: -66.1057, elev_m: 10 };
const AT = "2026-10-20T00:30:00Z";
const VEIL = {
  id: "caldwell:C33",
  kind: "caldwell",
  designation: "C 33",
  long_designation: "Caldwell 33",
  name: "East Veil Nebula",
  display: "C 33 (East Veil Nebula)",
  aliases: ["NGC 6992"],
  object_type: "supernova_remnant",
  magnitude: 7,
  ra_j2000_deg: 314.0795,
  dec_j2000_deg: 31.7428,
  alt_deg: 75.12,
  az_deg: 250.31,
  above_horizon: true,
  visibility: { state: "UP", rise_utc: "2026-10-19T17:00:00Z", set_utc: "2026-10-20T09:12:00Z" },
  filter_hint: { label: "Duo-Band", basis: "heuristic" },
  match: { field: "name", text: "East Veil Nebula" },
};
const MARFAK = {
  ...VEIL,
  id: "star:hip:5542",
  kind: "star",
  designation: "Theta Cassiopeiae",
  long_designation: "Theta Cassiopeiae",
  name: "Marfak",
  display: "Theta Cassiopeiae (Marfak)",
  alt_deg: 38.3,
  filter_hint: null,
  match: { field: "alias", text: "Marfak-East" },
};
const M31 = {
  ...VEIL,
  id: "messier:M31",
  kind: "messier",
  designation: "M 31",
  long_designation: "Messier 31",
  name: "Andromeda Galaxy",
  display: "M 31 (Andromeda Galaxy)",
  alt_deg: 32.4,
  match: undefined,
  recommend: { best_alt_deg: 79.6, best_utc: "2026-10-20T04:10:00Z", score: 0.91 },
};
const NOT_MATERIALIZED = { state: "NOT_MATERIALIZED", object_count: null, propagated: 0, skipped_count: 0, skipped: [] };

function targetsPayload(targets) {
  return { schema_version: "skywatcher.sky-targets/v1", observer: OBSERVER, at_utc: AT, targets, satellites: NOT_MATERIALIZED };
}

function chartPayload(target) {
  return {
    schema_version: "skywatcher.sky-chart/v1",
    observer: OBSERVER,
    at_utc: AT,
    fov_deg: 6,
    radius_deg: 12,
    limiting_magnitude: 7.5,
    target,
    stars: [{ alt: 76, az: 252, mag: 2.48, id: "star:hip:102488", label: "Epsilon Cygni" }],
    lines: [],
    constellation_labels: [],
    dso_markers: [],
    solar_system: [],
    satellites: [],
  };
}

async function search(text) {
  fireEvent.change(screen.getByRole("searchbox", { name: "Search sky targets" }), { target: { value: text } });
  await screen.findByRole("button", { name: "C 33 (East Veil Nebula)" }, { timeout: 2000 });
}

describe("SkyTargetFinder", () => {
  beforeEach(() => {
    window.localStorage.clear();
    skyRecommend.mockResolvedValue({
      schema_version: "skywatcher.sky-recommend/v1",
      observer: OBSERVER,
      at_utc: AT,
      dark_window: { start_utc: "2026-10-19T22:46:41Z", end_utc: "2026-10-20T09:32:04Z", sun_alt_deg: -12 },
      targets: [M31],
    });
    skyTargets.mockImplementation((params) =>
      Promise.resolve(targetsPayload(params.q === "East" ? [VEIL, MARFAK] : params.q ? [VEIL] : [])),
    );
    skyChart.mockImplementation((params) =>
      Promise.resolve(chartPayload(params.target === VEIL.id ? VEIL : M31)),
    );
  });

  afterEach(() => {
    vi.clearAllMocks();
    delete navigator.clipboard;
  });

  it("opens on tonight's recommendations from the default San Juan observer", async () => {
    render(<SkyTargetFinder />);
    expect(await screen.findByRole("button", { name: "M 31 (Andromeda Galaxy)" })).toBeTruthy();
    expect(skyRecommend).toHaveBeenCalledWith({ lat: 18.4655, lon: -66.1057, elev_m: 10, at: undefined });
    expect(screen.getByText(/best ∠ 80° at/)).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Recommend" }).getAttribute("aria-selected")).toBe("true");
  });

  it("searches by name and alias like the telescope app", async () => {
    render(<SkyTargetFinder />);
    await search("East");
    expect(screen.getByRole("button", { name: "Theta Cassiopeiae (Marfak)" })).toBeTruthy();
    expect(screen.getByText("matches Marfak-East")).toBeTruthy();
    expect(skyTargets).toHaveBeenCalledWith(expect.objectContaining({ q: "East", kind: "all", limit: 50 }));
    expect(screen.getByRole("status").textContent).toContain("NOT_MATERIALIZED");
  });

  it("opens the chart for a selected target and copies its coordinates", async () => {
    const writeText = vi.fn().mockResolvedValue();
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<SkyTargetFinder />);
    await search("East");
    fireEvent.click(screen.getByRole("button", { name: "C 33 (East Veil Nebula)" }));
    expect(await screen.findByRole("img", { name: "Sky chart centred on Caldwell 33" })).toBeTruthy();
    expect(skyChart).toHaveBeenCalledWith(expect.objectContaining({ target: "caldwell:C33", fov_deg: 6 }));
    fireEvent.click(screen.getByRole("button", { name: "Copy target coordinates" }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const text = writeText.mock.calls[0][0];
    expect(text).toContain("RA (J2000): 20h 56m 19.1s");
    expect(text).toContain("UTC: 2026-10-20T00:30:00Z");
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: "Coordinates copied" }));
  });

  it("reports a missing clipboard instead of claiming success", async () => {
    render(<SkyTargetFinder />);
    await search("East");
    fireEvent.click(screen.getByRole("button", { name: "Copy coordinates for C 33 (East Veil Nebula)" }));
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({ variant: "destructive", title: "Coordinates not copied" }),
      ),
    );
  });

  it("keeps favorites in local storage and lists them under Favorites", async () => {
    render(<SkyTargetFinder />);
    await search("East");
    const heart = screen.getByRole("button", { name: "Add C 33 (East Veil Nebula) to favorites" });
    fireEvent.click(heart);
    expect(screen.getByRole("button", { name: "Remove C 33 (East Veil Nebula) from favorites" }).getAttribute("aria-pressed")).toBe("true");
    const stored = JSON.parse(window.localStorage.getItem("skywatcher.sky-favorites.v1"));
    expect(stored.items.map((item) => item.id)).toEqual(["caldwell:C33"]);

    fireEvent.click(screen.getByRole("tab", { name: "Favorites" }));
    const list = await screen.findByRole("list");
    expect(await within(list).findByRole("button", { name: "C 33 (East Veil Nebula)" })).toBeTruthy();
    expect(skyTargets).toHaveBeenCalledWith(expect.objectContaining({ q: "C 33", kind: "caldwell" }));
  });

  it("shows an error with a working retry", async () => {
    skyRecommend.mockRejectedValueOnce(new Error("backend offline"));
    render(<SkyTargetFinder />);
    expect(await screen.findByText("Sky data unavailable")).toBeTruthy();
    expect(screen.getByText("backend offline")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("button", { name: "M 31 (Andromeda Galaxy)" })).toBeTruthy();
    expect(skyRecommend).toHaveBeenCalledTimes(2);
  });

  it("validates and applies a new observer location", async () => {
    render(<SkyTargetFinder />);
    await screen.findByRole("button", { name: "M 31 (Andromeda Galaxy)" });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Observer latitude" }), { target: { value: "95" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply location" }));
    expect(screen.getByRole("alert").textContent).toContain("Latitude must be between -90 and 90");
    fireEvent.change(screen.getByRole("spinbutton", { name: "Observer latitude" }), { target: { value: "40.7" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply location" }));
    await waitFor(() => expect(skyRecommend).toHaveBeenLastCalledWith(expect.objectContaining({ lat: 40.7 })));
  });
});
