import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import AnalysisLenses from "./AnalysisLenses";

// The page's contract is that it renders whatever the registry endpoint returns, with
// no lens vocabulary of its own. These tests feed it a payload that is deliberately not
// the committed one, so anything hardcoded would show up as a mismatch.
const REGISTRY = {
  available: true,
  stages: ["satellite_image_processing", "flight_data_collection"],
  owners: ["SATIM", "FPIM"],
  lenses: [
    {
      lens_id: "satim.invented_lens",
      name: "Invented Lens",
      owner: "SATIM",
      stage: "satellite_image_processing",
      status: "active",
      objective: "An objective that exists only in this test.",
      required_parameters: [
        { parameter_id: "roi_target", description: "Target ROI", degraded_behavior: "" },
      ],
      optional_parameters: [
        {
          parameter_id: "control_roi",
          description: "Control ROI",
          degraded_behavior: "no local baseline is available",
        },
      ],
      emits: ["A", "B"],
    },
  ],
  objectives: [
    {
      profile_id: "invented_profile",
      name: "Invented Profile",
      version: "9.9.9",
      status: "experimental",
      required_lenses: ["satim.invented_lens"],
      optional_lenses: [],
    },
  ],
  thresholds: [
    {
      threshold_id: "TEST-PROHIBITED-RULE",
      owner: "CORRIM",
      value: "some rule",
      unit: "rule",
      purpose: "Never execute",
      status: "PROHIBITED",
      failure_behavior: "Must not run.",
    },
  ],
};

function mockFetch(payload, { ok = true } = {}) {
  return vi.fn(() => Promise.resolve({ ok, json: () => Promise.resolve(payload) }));
}

describe("AnalysisLenses", () => {
  beforeEach(() => {
    global.fetch = mockFetch(REGISTRY);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders lenses supplied by the backend rather than a built-in list", async () => {
    render(<AnalysisLenses />);
    expect(await screen.findByText("Invented Lens")).toBeTruthy();
    // Appears twice by design: once as the lens row, once as a required-lens chip on
    // the objective profile that names it.
    expect(screen.getAllByText("satim.invented_lens")).toHaveLength(2);
    expect(screen.getByText("An objective that exists only in this test.")).toBeTruthy();
  });

  it("fetches the registry endpoint", async () => {
    render(<AnalysisLenses />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(String(global.fetch.mock.calls[0][0])).toContain("/analysis/registry");
  });

  it("shows required and optional parameters distinctly", async () => {
    render(<AnalysisLenses />);
    expect(await screen.findByText("roi_target")).toBeTruthy();

    // The optional chip's tooltip is what the parameter's absence costs.
    const optional = screen.getByText("control_roi");
    expect(optional.getAttribute("title")).toBe("no local baseline is available");
  });

  it("surfaces objective profiles and their required lenses", async () => {
    render(<AnalysisLenses />);
    expect(await screen.findByText("Invented Profile")).toBeTruthy();
    expect(screen.getByText("invented_profile · v9.9.9")).toBeTruthy();
  });

  it("shows a threshold's governance status, not just its value", async () => {
    render(<AnalysisLenses />);
    expect(await screen.findByText("TEST-PROHIBITED-RULE")).toBeTruthy();
    expect(screen.getByText("PROHIBITED")).toBeTruthy();
  });

  it("reports an unavailable registry instead of rendering an empty page", async () => {
    global.fetch = mockFetch({
      available: false,
      lenses: [],
      objectives: [],
      thresholds: [],
    });
    render(<AnalysisLenses />);
    expect(await screen.findByText("Lens registry unavailable")).toBeTruthy();
  });

  it("survives a failed fetch without crashing", async () => {
    global.fetch = vi.fn(() => Promise.reject(new Error("network down")));
    render(<AnalysisLenses />);
    // Falls through to the empty states rather than throwing past the error boundary.
    expect(await screen.findByText("Analysis Lenses")).toBeTruthy();
  });
});
