import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SkywatcherDataProvider, useSkywatcher } from "./SkywatcherData";

const { update } = vi.hoisted(() => ({ update: vi.fn() }));

vi.mock("@/api/federationClient", () => ({
  federation: {
    entities: new Proxy({}, {
      get: (_target, entity) => ({
        list: () => entity === "FR24Captures"
          ? Promise.resolve([{ id: "capture-1", ingest_status: "queued" }])
          : Promise.resolve([]),
        update,
      }),
    }),
  },
}));

function CaptureStatus() {
  const data = useSkywatcher();
  return (
    <>
      <p>{data.captures[0]?.ingest_status ?? "loading"}</p>
      <button onClick={() => data.updateRecord("captures", "capture-1", { ingest_status: "rejected" }).catch(() => {})}>
        Reject capture
      </button>
    </>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("does not apply a local diagnostic edit when its persisted write fails", async () => {
  update.mockRejectedValueOnce(new Error("storage unavailable"));

  render(
    <SkywatcherDataProvider>
      <CaptureStatus />
    </SkywatcherDataProvider>,
  );

  await screen.findByText("queued");
  fireEvent.click(screen.getByRole("button", { name: "Reject capture" }));

  await waitFor(() => expect(update).toHaveBeenCalledWith("capture-1", { ingest_status: "rejected" }));
  expect(screen.getByText("queued")).toBeVisible();
});
