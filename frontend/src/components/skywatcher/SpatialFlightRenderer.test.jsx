import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import SpatialFlightRenderer, { flightResultsToRoutes } from "./SpatialFlightRenderer";
import { FLIGHT_INGEST_STATUS } from "@/lib/skywatcher";

describe("SpatialFlightRenderer", () => {
  it("turns only READY results into route segments", () => {
    const routes = flightResultsToRoutes([
      {
        status: FLIGHT_INGEST_STATUS.READY,
        source: "flight.csv",
        manifestation: "FR24_POSITION",
        points: [
          { lat: 18.1, lon: -66.1 },
          { lat: 18.2, lon: -66.2 },
          { lat: 18.3, lon: -66.3 },
        ],
      },
      {
        status: FLIGHT_INGEST_STATUS.EMPTY_TRACK,
        source: "empty.csv",
        points: [],
      },
    ]);

    expect(routes).toHaveLength(2);
    expect(routes[0]).toMatchObject({
      start_lat: 18.1,
      start_lon: -66.1,
      end_lat: 18.2,
      end_lon: -66.2,
    });
  });

  it("loads FR24 Position CSV without requiring split latitude/longitude columns", async () => {
    const onResults = vi.fn();
    render(<SpatialFlightRenderer onResults={onResults} />);

    const file = new File(
      [
        "Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction\n" +
          '1,2026-01-01T00:00:00Z,N1,"18.1,-66.1",100,10,90\n',
      ],
      "flight.csv",
      { type: "text/csv" },
    );

    fireEvent.change(screen.getByLabelText("Load KML or CSV flight files"), {
      target: { files: [file] },
    });

    await waitFor(() => expect(onResults).toHaveBeenCalled());
    expect(await screen.findByText("flight.csv")).toBeInTheDocument();
    expect(screen.getByText("FR24_POSITION · 1 accepted points")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("keeps empty and valid files independent in the same upload", async () => {
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

    expect(await screen.findByText("good.csv")).toBeInTheDocument();
    expect(screen.getByText("empty.csv")).toBeInTheDocument();
    expect(screen.getByText("Empty track")).toBeInTheDocument();
  });

  it("reports schema failure rather than the obsolete 40-row header error", async () => {
    render(<SpatialFlightRenderer />);

    const file = new File(["name,value\na,1\n"], "not-track.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("Load KML or CSV flight files"), {
      target: { files: [file] },
    });

    expect(await screen.findByText("not-track.csv")).toBeInTheDocument();
    expect(screen.getByText("Schema unresolved")).toBeInTheDocument();
    expect(screen.queryByText(/first 40 rows/i)).not.toBeInTheDocument();
  });

  it("fails the whole selection closed when more than 12 files are chosen", async () => {
    render(<SpatialFlightRenderer />);

    const files = Array.from(
      { length: 13 },
      (_, index) => new File(["name,value\na,1\n"], `f${index}.csv`, { type: "text/csv" }),
    );
    fireEvent.change(screen.getByLabelText("Load KML or CSV flight files"), {
      target: { files },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Select at most 12 files per batch");
    expect(screen.queryByText("f0.csv")).not.toBeInTheDocument();
  });
});
