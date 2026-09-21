import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SpatialFlightRenderer from "./SpatialFlightRenderer";

describe("SpatialFlightRenderer", () => {
  it("loads FR24 CSV and keeps an empty sibling nonfatal", async () => {
    render(<SpatialFlightRenderer />);

    const good = new File(
      [
        "Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction\n" +
          '1,2026-01-01T00:00:00Z,N1,"18.1,-66.1",100,10,90\n',
      ],
      "good.csv",
      { type: "text/csv" },
    );
    const empty = new File(
      ["Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction\n"],
      "empty.csv",
      { type: "text/csv" },
    );

    fireEvent.change(screen.getByLabelText("Load KML or CSV flight files"), {
      target: { files: [good, empty] },
    });

    await waitFor(() => expect(screen.getByText("good.csv")).toBeInTheDocument());
    expect(screen.getByText("empty.csv")).toBeInTheDocument();
    expect(screen.getByText("READY")).toBeInTheDocument();
    expect(screen.getByText("EMPTY_TRACK")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Local flight track preview" })).toBeInTheDocument();
  });

  it("rejects more than twelve files before parsing", async () => {
    render(<SpatialFlightRenderer />);
    const files = Array.from(
      { length: 13 },
      (_, index) => new File(["name,value\na,1\n"], `file-${index}.csv`, { type: "text/csv" }),
    );

    fireEvent.change(screen.getByLabelText("Load KML or CSV flight files"), {
      target: { files },
    });

    expect(await screen.findByText("Select no more than 12 files per batch.")).toBeInTheDocument();
  });
});
