import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import ObservationDetailDrawer from "./ObservationDetailDrawer";
import ReviewDetailDrawer from "./ReviewDetailDrawer";
import RouteDetailDrawer from "./RouteDetailDrawer";

const { updateRecord, toast, observation, route, review } = vi.hoisted(() => ({
  updateRecord: vi.fn(),
  toast: vi.fn(),
  observation: {
    id: "observation-row-1",
    observation_id: "OBS-1",
    callsign: "TEST1",
    tail_number: "N1",
    aircraft_type: "Test",
    review_status: "new",
  },
  route: {
    id: "route-row-1",
    route_segment_id: "ROUTE-1",
    inferred_route_name: "Test route",
    route_cluster_id: "cluster-1",
    review_status: "new",
  },
  review: {
    id: "review-row-1",
    review_id: "REVIEW-1",
    reason: "Test review",
    item_type: "observation",
    item_id: "OBS-1",
    review_status: "open",
    notes: "Existing notes",
  },
}));

vi.mock("@/lib/SkywatcherData", () => ({
  useSkywatcher: () => ({ observations: [observation], routes: [route], reviews: [review], updateRecord }),
  useResolvers: () => ({
    routeById: () => route,
    captureById: () => null,
    observationById: () => null,
    aircraftByTail: () => null,
    routesForObservation: () => [],
    linksForObservation: () => [],
    reviewItemTarget: () => ({ rec: null }),
  }),
}));
vi.mock("@/components/ui/use-toast", () => ({ toast }));
vi.mock("../RouteSegmentPanel", () => ({ default: () => null }));
vi.mock("../InfrastructureLinkPanel", () => ({ default: () => null }));

beforeEach(() => {
  vi.clearAllMocks();
});

it.each([
  ["observation", <ObservationDetailDrawer id="observation-row-1" onClose={vi.fn()} go={{}} />, "Verify"],
  ["route", <RouteDetailDrawer id="ROUTE-1" onClose={vi.fn()} go={{}} />, "Verify"],
])("%s status changes report persistence failures", async (_kind, drawer, action) => {
  updateRecord.mockRejectedValueOnce(new Error("status storage unavailable"));
  render(drawer);

  fireEvent.click(screen.getByRole("button", { name: action }));

  await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({
    variant: "destructive",
    title: "Review status was not updated",
    description: "status storage unavailable",
  })));
  expect(toast).not.toHaveBeenCalledWith(expect.objectContaining({ title: "Diagnostic state updated" }));
});

it("reports review status and notes failures instead of claiming either write succeeded", async () => {
  updateRecord
    .mockRejectedValueOnce(new Error("status storage unavailable"))
    .mockRejectedValueOnce(new Error("notes storage unavailable"));
  render(<ReviewDetailDrawer id="REVIEW-1" onClose={vi.fn()} go={{}} />);

  fireEvent.click(screen.getByRole("button", { name: "Start Review" }));
  await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({
    variant: "destructive",
    title: "Review status was not updated",
    description: "status storage unavailable",
  })));

  fireEvent.click(screen.getByRole("button", { name: "Save Notes" }));
  await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({
    variant: "destructive",
    title: "Notes were not saved",
    description: "notes storage unavailable",
  })));
  expect(toast).not.toHaveBeenCalledWith(expect.objectContaining({ title: "Notes saved" }));
});
