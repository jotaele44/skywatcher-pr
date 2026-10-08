import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import Observations from "./Observations";

const { updateRecord, toast, observations } = vi.hoisted(() => ({
  updateRecord: vi.fn(),
  toast: vi.fn(),
  observations: [
    {
      id: "observation-1",
      observation_id: "OBS-1",
      callsign: "TEST1",
      tail_number: "N1",
      observed_at: "2026-01-01T00:00:00Z",
      confidence_score: 0.8,
    },
    {
      id: "observation-2",
      observation_id: "OBS-2",
      callsign: "TEST2",
      tail_number: "N2",
      observed_at: "2026-01-02T00:00:00Z",
      confidence_score: 0.6,
    },
  ],
}));

vi.mock("@/lib/SkywatcherData", () => ({
  useSkywatcher: () => ({ observations, loading: false, airports: [], assets: [], updateRecord }),
}));
vi.mock("@/components/skywatcher/drawers/DrawerHub", () => ({
  useDrawers: () => ({ open: { observation: vi.fn() } }),
}));
vi.mock("@/components/ui/use-toast", () => ({ useToast: () => ({ toast }) }));
vi.mock("@/components/ui/checkbox", () => ({
  Checkbox: ({ checked, onCheckedChange, ...props }) => (
    <input
      type="checkbox"
      checked={checked}
      onChange={onCheckedChange}
      {...props}
    />
  ),
}));
vi.mock("@/components/skywatcher/PuertoRicoMapShell", () => ({ default: () => null }));

beforeEach(() => {
  vi.clearAllMocks();
});

it("keeps only failed observations selected after a partial bulk update", async () => {
  updateRecord
    .mockResolvedValueOnce(undefined)
    .mockRejectedValueOnce(new Error("storage unavailable"));
  render(<Observations />);

  const selections = screen.getAllByRole("checkbox", { name: "Select observation" });
  fireEvent.click(selections[0]);
  fireEvent.click(selections[1]);
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));

  await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({
    variant: "destructive",
    title: "Bulk update incomplete",
    description: "1 updated; 1 failed. Failed observations remain selected for retry.",
  })));
  expect(screen.getByText("1 selected")).toBeVisible();
  expect(screen.getAllByRole("checkbox", { name: "Select observation" }).map((checkbox) => checkbox.checked))
    .toEqual([false, true]);
});
