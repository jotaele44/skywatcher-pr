import { describe, expect, it } from "vitest";
import {
  SPEED_SLIDER, clampReplayTime, composeReplayTime, frameIndexAt, frameToAircraft, latestReplayStart, localClock,
  localDate, sliderFromSpeed, speedFromSlider, timeZoneAbbreviation, utcClock,
} from "./replayModel";

const NOW = Date.parse("2026-11-03T16:32:44Z");

describe("replay model", () => {
  it("lands one minute into the newest complete half hour, as in the recording (16:01 UTC)", () => {
    expect(new Date(latestReplayStart(NOW)).toISOString()).toBe("2026-11-03T16:00:00.000Z");
    const clamped = clampReplayTime(NOW, NOW);
    expect(clamped.clamped).toBe(true);
    expect(new Date(clamped.ts).toISOString()).toBe("2026-11-03T16:01:00.000Z");
    const past = Date.parse("2026-11-03T09:32:00Z");
    expect(clampReplayTime(past, NOW)).toEqual({ ts: past, clamped: false });
  });

  it("shows UTC and Puerto Rico (AST) clocks like the replay bar", () => {
    const ts = Date.parse("2026-11-03T09:32:00Z");
    expect(utcClock(ts)).toBe("09:32:00");
    expect(localClock(ts, "America/Puerto_Rico")).toBe("05:32:00");
    expect(timeZoneAbbreviation(ts, "America/Puerto_Rico")).toBe("AST");
    expect(localDate(Date.parse("2026-11-03T02:00:00Z"), "America/Puerto_Rico")).toBe("2026-11-02");
  });

  it("maps the cubic speed slider between 1x and 1000x", () => {
    expect(speedFromSlider(SPEED_SLIDER.min)).toBe(1);
    expect(speedFromSlider(SPEED_SLIDER.max)).toBe(1000);
    expect(speedFromSlider(sliderFromSpeed(30))).toBe(30);
  });

  it("composes UTC instants from the date and sliders", () => {
    expect(new Date(composeReplayTime("2026-11-03", 9, 32)).toISOString()).toBe("2026-11-03T09:32:00.000Z");
    expect(composeReplayTime("bad", 1, 1)).toBeNaN();
  });

  it("finds frames and derives headings from consecutive positions", () => {
    const frames = [{ t: 100, aircraft: [] }, { t: 110, aircraft: [] }, { t: 120, aircraft: [] }];
    expect(frameIndexAt(frames, 115_000)).toBe(1);
    expect(frameIndexAt(frames, 50_000)).toBe(-1);
    const fields = ["hex", "lat", "lon", "alt_baro", "gs", "source_type", "flight", "squawk"];
    const prev = new Map([["a37f12", { lat: 18.0, lon: -66.0, track: null }]]);
    const [ac] = frameToAircraft({ aircraft: [["a37f12", 18.1, -66.0, 3000, 200, "adsb_icao", "AAL1", "1200"]] }, fields, prev);
    expect(ac).toMatchObject({ hex: "a37f12", flight: "AAL1", squawk: "1200", alt_baro: 3000, type: "adsb_icao" });
    expect(ac.track).toBeCloseTo(0, 3);
  });
});
