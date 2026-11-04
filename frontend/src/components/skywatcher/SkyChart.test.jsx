import React from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import SkyChart from "./SkyChart";

const CHART = {
  schema_version: "skywatcher.sky-chart/v1",
  observer: { lat_deg: 18.4655, lon_deg: -66.1057, elev_m: 10 },
  at_utc: "2026-10-20T00:30:00Z",
  fov_deg: 6,
  radius_deg: 12,
  limiting_magnitude: 7.5,
  target: {
    id: "caldwell:C33",
    kind: "caldwell",
    designation: "C 33",
    long_designation: "Caldwell 33",
    name: "East Veil Nebula",
    display: "C 33 (East Veil Nebula)",
    ra_j2000_deg: 314.0795,
    dec_j2000_deg: 31.7428,
    alt_deg: 70.64,
    az_deg: 316.69,
    filter_hint: { label: "Duo-Band", basis: "heuristic" },
  },
  stars: [
    { alt: 72.1, az: 318.5, mag: 2.48, id: "star:hip:102488", label: "Epsilon Cygni" },
    { alt: 70.2, az: 315.9, mag: 6.8, id: null, label: null },
  ],
  lines: [{ constellation: "Cyg", points: [[72.1, 318.5], [75.0, 330.0]] }],
  constellation_labels: [{ id: "Cyg", name: "Cygnus", alt: 74, az: 320 }],
  dso_markers: [{ id: "caldwell:C34", designation: "C 34", long_designation: "Caldwell 34", alt: 69.9, az: 312.5 }],
  solar_system: [],
  satellites: [],
};

describe("SkyChart", () => {
  it("draws the FOV box, target label, labelled stars and compass", () => {
    render(<SkyChart chart={CHART} fovDeg={6} onFovChange={vi.fn()} onCopy={vi.fn()} />);
    expect(screen.getByRole("img", { name: "Sky chart centred on Caldwell 33" })).toBeTruthy();
    expect(screen.getByText("Caldwell 33")).toBeTruthy();
    expect(screen.getByText("FOV 6.0°")).toBeTruthy();
    expect(screen.getByText("Epsilon Cygni")).toBeTruthy();
    expect(screen.getByText("C 34")).toBeTruthy();
    for (const letter of ["N", "E", "S", "W"]) expect(screen.getByText(letter)).toBeTruthy();
    expect(screen.getByText("Duo-Band")).toBeTruthy();
    expect(screen.getByText("∠ 71°")).toBeTruthy();
  });

  it("copies the target and changes the field of view", () => {
    const onCopy = vi.fn();
    const onFovChange = vi.fn();
    render(<SkyChart chart={CHART} fovDeg={6} onFovChange={onFovChange} onCopy={onCopy} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy target coordinates" }));
    expect(onCopy).toHaveBeenCalledWith(CHART.target, CHART.at_utc, CHART.observer);
    fireEvent.change(screen.getByRole("combobox", { name: "Field of view" }), { target: { value: "12" } });
    expect(onFovChange).toHaveBeenCalledWith(12);
  });

  it("zooms within bounds", () => {
    render(<SkyChart chart={CHART} fovDeg={6} onFovChange={vi.fn()} onCopy={vi.fn()} />);
    const zoomOut = screen.getByRole("button", { name: "Zoom out" });
    expect(zoomOut.disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(zoomOut.disabled).toBe(false);
  });
});
