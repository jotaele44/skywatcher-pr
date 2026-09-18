import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/skywatcher/PuertoRicoMapShell", () => ({ default: ({ observations }) => <div data-testid="map">{observations.length} observations</div> }));
import SpatialPlayback from "@/pages/SpatialPlayback";

describe("SpatialPlayback", () => {
  it("renders real Spiderweb context and fails sensor geometry closed", () => {
    render(<SpatialPlayback />);
    expect(screen.getByRole("heading", { name: "Land / Ocean Playback" })).toBeTruthy();
    expect(screen.getByTestId("map").textContent).toContain("3 observations");
    expect(screen.getByText("-580.1 m")).toBeTruthy();
    expect(screen.getByText("SENSOR FOOTPRINT UNRESOLVED")).toBeTruthy();
    expect(screen.getByText(/No footprint or intersection was synthesized/)).toBeTruthy();
  });
  it("plays across frozen observations without losing provenance", () => {
    render(<SpatialPlayback />);
    fireEvent.change(screen.getByLabelText("Playback observation"), { target: { value: "1" } });
    expect(screen.getByText("-725.9 m")).toBeTruthy();
    expect(screen.getByText(/d708d9400a260a5a/)).toBeTruthy();
  });
});
