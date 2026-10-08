import { describe, expect, it } from "vitest";
import { MASTER_FLIGHT_LOG_STATUS, parseMasterFlightLogHtml } from "./masterFlightLog";

describe("Master Flight Log corpus adapter", () => {
  it("extracts the embedded seed without promoting open field semantics", () => {
    const html = `<script>window.MFL_SEED = {"format":"master-flight-log-backup","version":1,"exported":"2026-09-23T22:48:05.164Z","flights":{"2025-08":[{"h":"abc123","fid":"3b873caa","cs":"N407PR","n":264,"t0":1754062238,"t1":1754064199,"alt":2100,"spd":134,"dist":119.7,"la0":18.456985,"lo0":-66.106171,"la1":18.18405,"lo1":-67.149124,"pr":100,"gap":119,"gp":[0,0,0],"s":[{"f":"csv","n":"3b873caa.csv","m":1786998790,"k":0}],"km":12,"rt":"SIG>?"}]}};</script>`;
    const result = parseMasterFlightLogHtml(html);

    expect(result.status).toBe(MASTER_FLIGHT_LOG_STATUS.CORPUS_READY);
    expect(result.snapshot.recordCount).toBe(1);
    expect(result.records[0]).toMatchObject({
      corpusUid: "mfl:abc123",
      monthBucket: "2025-08",
      sourceFlightIdRaw: "3b873caa",
      callsignRaw: "N407PR",
      pointCount: 264,
      start: { lat: 18.456985, lon: -66.106171 },
      end: { lat: 18.18405, lon: -67.149124 },
    });
    expect(result.records[0].metrics).toEqual({
      maxAltitudeFt: 2100,
      maxSpeedKt: 134,
      trackDistanceKm: 119.7,
      prAreaPointPct: 100,
      maxGapSeconds: 119,
      gapCounts: {
        over120Seconds: 0,
        over300Seconds: 0,
        over900Seconds: 0,
      },
    });
    expect(result.records[0].kmlEnrichment).toEqual({
      metadataTableIndexRaw: 12,
      routeRaw: "SIG>?",
    });
    expect(result.records[0].raw.km).toBe(12);
  });

  it("fails closed when the seed assignment is absent", () => {
    const result = parseMasterFlightLogHtml("<html></html>");
    expect(result.status).toBe(MASTER_FLIGHT_LOG_STATUS.SEED_NOT_FOUND);
    expect(result.records).toEqual([]);
  });

  it("does not accept a different backup version as canonical", () => {
    const result = parseMasterFlightLogHtml(
      '<script>window.MFL_SEED={"format":"master-flight-log-backup","version":2,"flights":{}};</script>',
    );
    expect(result.status).toBe(MASTER_FLIGHT_LOG_STATUS.UNSUPPORTED_VERSION);
  });
});
