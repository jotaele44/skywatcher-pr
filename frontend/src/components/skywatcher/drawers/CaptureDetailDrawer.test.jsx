import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import CaptureDetailDrawer from "./CaptureDetailDrawer";

const { createReview, toast, updateRecord } = vi.hoisted(() => ({
  createReview: vi.fn(),
  toast: vi.fn(),
  updateRecord: vi.fn(),
}));

vi.mock("@/lib/SkywatcherData", () => ({
  useSkywatcher: () => ({ captures: [], createReview, updateRecord }),
  useResolvers: () => ({
    captureById: () => ({
      id: "capture-row-1",
      capture_id: "CAP-1",
      file_name: "capture.json",
      capture_type: "screenshot",
      ingest_status: "queued",
      manual_review_required: false,
      synthetic_flag: true,
      sha256_hash: "abc123",
      captured_at: "2026-01-01T00:00:00Z",
      linked_observation_count: 0,
      provenance_note: "Test capture",
    }),
    observationsForCapture: () => [],
    routesForCapture: () => [],
  }),
}));

vi.mock("@/components/ui/use-toast", () => ({ toast }));
vi.mock("../CaptureQualityPanel", () => ({ default: () => <div>Capture quality</div> }));

beforeEach(() => {
  vi.clearAllMocks();
});

it("omits unsupported placeholder actions and labels the hash copy control", () => {
  render(<CaptureDetailDrawer id="CAP-1" onClose={vi.fn()} go={{}} />);

  expect(screen.queryByRole("button", { name: "Queue Capture" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Link Observation" })).not.toBeInTheDocument();
  expect(screen.getByText(/does not queue or process captures/i)).toBeVisible();
  expect(screen.getByRole("button", { name: "Copy SHA-256 hash" })).toBeVisible();
});

it("surfaces a failed capture status write without reporting success", async () => {
  updateRecord.mockRejectedValueOnce(new Error("storage unavailable"));
  render(<CaptureDetailDrawer id="CAP-1" onClose={vi.fn()} go={{}} />);

  fireEvent.click(screen.getByRole("button", { name: "Reject Capture" }));

  await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({
    variant: "destructive",
    title: "Diagnostic update failed",
    description: "storage unavailable",
  })));
  expect(toast).not.toHaveBeenCalledWith(expect.objectContaining({ title: "Diagnostic state updated" }));
});

it("reports clipboard unavailability instead of claiming the hash was copied", async () => {
  render(<CaptureDetailDrawer id="CAP-1" onClose={vi.fn()} go={{}} />);

  fireEvent.click(screen.getByRole("button", { name: "Copy SHA-256 hash" }));

  await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({
    variant: "destructive",
    title: "Hash not copied",
  })));
});
