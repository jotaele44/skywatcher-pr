import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const fixture = vi.hoisted(() => ({
  loading: false,
  airports: [],
  spatialObservations: [
    {
      id: "rlsm-aircraft-1",
      source_type: "fr24_screenshot",
      registration: "N123AB",
      callsign: "TEST1",
      source_filename: "frame.png",
      latitude: 18.21,
      longitude: -66.49,
      pixel_x: 400.5,
      pixel_y: 700.25,
      icon_rotation_deg: 42,
      position_method: "multi_anchor_affine",
      position_error_m: 120,
    },
  ],
  spatialFrames: [
    {
      id: "rlsm-frame-1",
      screenshot_id: 1,
      filename: "frame.png",
      marker_status: "selected",
      candidate_count: 1,
      georef_status: "located",
      georef_method: "multi_anchor_affine",
      anchor_count: 3,
      zoom_rung: 0,
      zoom_support: 3,
      estimated_error_m: 120,
    },
  ],
  zoomRungs: [
    {
      id: "rung-0",
      viewport_profile: "1170x2532:0,0,1170,1519",
      zoom_rung: 0,
      scale_m_per_px: 98.5,
      support_count: 3,
      dispersion_log2: 0.01,
      eligible_for_transfer: true,
    },
  ],
}));

vi.mock("@/lib/SkywatcherData", () => ({
  useSkywatcher: () => fixture,
}));

vi.mock("@/components/skywatcher/PuertoRicoMapShell", () => ({
  default: ({ observations }) => (
    <div data-testid="spatial-map">{observations.length} positions</div>
  ),
}));

import SpatialTruth from "@/pages/SpatialTruth";

describe("SpatialTruth", () => {
  afterEach(() => {
    fixture.spatialFrames = fixture.spatialFrames.slice(0, 1);
  });

  it("renders the end-to-end spatial evidence path", () => {
    render(<SpatialTruth />);

    expect(screen.getByRole("heading", { name: "Aircraft Spatial Truth" })).toBeTruthy();
    expect(screen.getAllByText("100.0%", { exact: true })).toHaveLength(2);
    expect(screen.getByTestId("spatial-map").textContent).toContain("1 positions");
    expect(screen.getByText("TEST1")).toBeTruthy();
    expect(screen.getAllByText("multi_anchor_affine").length).toBeGreaterThan(0);
    expect(screen.getByText("eligible")).toBeTruthy();
    expect(screen.getByText("OCR deferred")).toBeTruthy();
  });

  it("opens the scale-bar review gate only above fifteen percent", () => {
    fixture.spatialFrames = [
      ...fixture.spatialFrames,
      {
        ...fixture.spatialFrames[0],
        id: "rlsm-frame-2",
        screenshot_id: 2,
        filename: "unresolved.png",
        georef_status: "unclassified",
        georef_method: "unclassified",
        anchor_count: 1,
      },
    ];

    render(<SpatialTruth />);

    expect(screen.getByText("Threshold exceeded")).toBeTruthy();
    expect(screen.getByText(/1 of 2 otherwise-recoverable frames/)).toBeTruthy();
  });
});
