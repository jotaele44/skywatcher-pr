import { describe, expect, it } from "vitest";
import {
  FLIGHT_INGEST_STATUS,
  parseFlightCsv,
  parseFlightFiles,
  parseFlightKml,
} from "./flightIngestion";

describe("browser flight ingestion contract", () => {
  it("parses native FR24 Position as latitude,longitude", () => {
    const result = parseFlightCsv(
      [
        "Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction",
        '1766761782,2025-12-26T15:09:42Z,N540DB,"18.338324,-65.651604",250,35,333',
      ].join("\n"),
      "fr24.csv",
    );

    expect(result.status).toBe(FLIGHT_INGEST_STATUS.READY);
    expect(result.manifestation).toBe("FR24_POSITION");
    expect(result.points).toHaveLength(1);
    expect(result.points[0]).toMatchObject({
      lat: 18.338324,
      lon: -65.651604,
      altitude: 250,
      speed: 35,
      heading: 333,
      callsign: "N540DB",
    });
  });

  it("discovers an FR24 header after a long preamble", () => {
    const preamble = Array.from({ length: 75 }, (_, index) => `metadata row ${index}`);
    const result = parseFlightCsv(
      [
        ...preamble,
        "Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction",
        '1,2026-01-01T00:00:00Z,N1,"18.1,-66.1",100,20,90',
      ].join("\n"),
    );

    expect(result.status).toBe(FLIGHT_INGEST_STATUS.READY);
    expect(result.diagnostics.headerIndex).toBe(75);
  });

  it("supports semicolon-delimited split coordinates", () => {
    const result = parseFlightCsv(
      "time;latitude;longitude;speed\n2026-01-01T00:00:00Z;18.1;-66.1;120\n",
    );

    expect(result.status).toBe(FLIGHT_INGEST_STATUS.READY);
    expect(result.manifestation).toBe("SPLIT_COORDINATES");
    expect(result.points[0].lon).toBe(-66.1);
  });

  it("preserves derived segment endpoints as a distinct manifestation", () => {
    const result = parseFlightCsv(
      [
        "Mission_ID,Hash,Seg_ID,Start_Lat,Start_Lon,End_Lat,End_Lon,Len_m,Bearing_deg",
        "M1,abc,S1,18.1,-66.1,18.2,-66.2,1000,225",
      ].join("\n"),
    );

    expect(result.status).toBe(FLIGHT_INGEST_STATUS.READY);
    expect(result.manifestation).toBe("DERIVED_SEGMENT_TABLE");
    expect(result.points.map((point) => point.sourceGeometry)).toEqual(["segment_start", "segment_end"]);
  });

  it("classifies header-only FR24 files as empty rather than malformed", () => {
    const result = parseFlightCsv("Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction\n");
    expect(result.status).toBe(FLIGHT_INGEST_STATUS.EMPTY_TRACK);
  });

  it("fails closed when FR24 Position values are out of range", () => {
    const result = parseFlightCsv(
      [
        "Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction",
        '1,2026-01-01T00:00:00Z,N1,"181,-200",100,10,90',
      ].join("\n"),
    );

    expect(result.status).toBe(FLIGHT_INGEST_STATUS.COORDINATE_BINDING_UNRESOLVED);
    expect(result.points).toHaveLength(0);
  });

  it("reports schema absence separately from coordinate failure", () => {
    const result = parseFlightCsv("name,value\na,1\n");
    expect(result.status).toBe(FLIGHT_INGEST_STATUS.SCHEMA_UNRESOLVED);
  });

  it("parses standard KML in longitude,latitude,altitude order", () => {
    const result = parseFlightKml(
      '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><Point>' +
        "<coordinates>-66.100891,18.456472,250</coordinates>" +
        "</Point></Placemark></kml>",
    );

    expect(result.status).toBe(FLIGHT_INGEST_STATUS.READY);
    expect(result.points[0]).toMatchObject({
      lat: 18.456472,
      lon: -66.100891,
      altitude: 250,
    });
  });

  it("accepts LineString-only KML", () => {
    const result = parseFlightKml(
      '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><LineString>' +
        "<coordinates>-66.1,18.1,100 -66.2,18.2,200</coordinates>" +
        "</LineString></Placemark></kml>",
    );

    expect(result.status).toBe(FLIGHT_INGEST_STATUS.READY);
    expect(result.points).toHaveLength(2);
  });

  it("accepts gx:Track while preserving lon lat alt ordering", () => {
    const result = parseFlightKml(
      '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2" ' +
        'xmlns:gx="http://www.google.com/kml/ext/2.2"><Placemark><gx:Track>' +
        "<when>2026-01-01T00:00:00Z</when><gx:coord>-66.1 18.1 100</gx:coord>" +
        "<when>2026-01-01T00:01:00Z</when><gx:coord>-66.2 18.2 200</gx:coord>" +
        "</gx:Track></Placemark></kml>",
    );

    expect(result.status).toBe(FLIGHT_INGEST_STATUS.READY);
    expect(result.points).toHaveLength(2);
    expect(result.points[0].timestamp).toBe("2026-01-01T00:00:00Z");
  });

  it("classifies metadata-only KML as EMPTY_TRACK", () => {
    const result = parseFlightKml(
      '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>' +
        "<name>metadata only</name></Document></kml>",
    );

    expect(result.status).toBe(FLIGHT_INGEST_STATUS.EMPTY_TRACK);
  });

  it("isolates file failures inside one browser upload batch", async () => {
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
    const unsupported = new File(["x"], "readme.txt", { type: "text/plain" });

    const results = await parseFlightFiles([good, empty, unsupported]);

    expect(results.map((result) => result.status)).toEqual([
      FLIGHT_INGEST_STATUS.READY,
      FLIGHT_INGEST_STATUS.EMPTY_TRACK,
      FLIGHT_INGEST_STATUS.UNSUPPORTED_GEOMETRY,
    ]);
  });
});
