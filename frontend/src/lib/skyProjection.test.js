import { describe, expect, it } from "vitest";
import {
  compassVectors,
  describeVisibility,
  formatAltitudeBadge,
  formatCoordinateClipboard,
  formatDecDms,
  formatRaHms,
  fovRectangle,
  gnomonic,
  inverseGnomonic,
} from "./skyProjection";

describe("gnomonic projection in the horizon frame", () => {
  it("puts the centre at the origin", () => {
    const p = gnomonic(70, 250, 70, 250);
    expect(p.visible).toBe(true);
    expect(p.x).toBeCloseTo(0, 10);
    expect(p.y).toBeCloseTo(0, 10);
  });

  it("maps higher altitude to up and larger azimuth to the right", () => {
    expect(gnomonic(71, 250, 70, 250).y).toBeCloseTo(1, 2);
    const right = gnomonic(0, 181, 0, 180);
    expect(right.x).toBeCloseTo(1, 2);
    expect(Math.abs(right.y)).toBeLessThan(1e-9);
  });

  it("refuses points 90 degrees or more from the centre", () => {
    expect(gnomonic(0, 0, 0, 180).visible).toBe(false);
  });

  it("round-trips through the inverse", () => {
    const p = gnomonic(64.2, 318.7, 66, 320);
    const back = inverseGnomonic(p.x, p.y, 66, 320);
    expect(back.alt).toBeCloseTo(64.2, 9);
    expect(back.az).toBeCloseTo(318.7, 9);
  });
});

describe("compass directions", () => {
  it("facing south: east left, west right, south down, north up", () => {
    const v = compassVectors(45, 180);
    expect(v.E.x).toBeLessThan(0);
    expect(v.W.x).toBeGreaterThan(0);
    expect(v.S.y).toBeLessThan(0);
    expect(v.N.y).toBeGreaterThan(0);
    expect(v.Z.y).toBeGreaterThan(0);
  });

  it("facing north: west left, east right", () => {
    const v = compassVectors(30, 0);
    expect(v.W.x).toBeLessThan(0);
    expect(v.E.x).toBeGreaterThan(0);
    expect(v.N.y).toBeLessThan(0);
  });
});

describe("formatting", () => {
  it("formats RA with carry at 59.95 seconds", () => {
    expect(formatRaHms(314.0795)).toBe("20h 56m 19.1s");
    // Exactly 3m 59.95s rounds up into the next minute instead of printing 60.0 s ...
    expect(formatRaHms(239.95 / 240)).toBe("00h 04m 00.0s");
    // ... while anything short of the half-tenth stays in the current minute.
    expect(formatRaHms(0.99979166)).toBe("00h 03m 59.9s");
  });

  it("formats signed declination", () => {
    expect(formatDecDms(31.7428)).toBe("+31° 44′ 34″");
    expect(formatDecDms(-16.71612)).toBe("-16° 42′ 58″");
  });

  it("formats the altitude badge and FOV rectangle", () => {
    expect(formatAltitudeBadge(75.12)).toBe("∠ 75°");
    const rect = fovRectangle(6);
    expect(rect.width).toBeGreaterThan(rect.height);
    expect(rect.width).toBeCloseTo(6.0, 1);
  });

  it("builds the exact clipboard block from the contract", () => {
    const target = {
      display: "C 33 (East Veil Nebula)",
      ra_j2000_deg: 314.0795,
      dec_j2000_deg: 31.7428,
      alt_deg: 75.12,
      az_deg: 250.31,
    };
    expect(
      formatCoordinateClipboard(target, "2026-10-20T00:30:00Z", {
        lat_deg: 18.4655,
        lon_deg: -66.1057,
        elev_m: 10,
      }),
    ).toBe(
      [
        "C 33 (East Veil Nebula)",
        "RA (J2000): 20h 56m 19.1s  Dec (J2000): +31° 44′ 34″",
        "Alt: 75.1°  Az: 250.3°",
        "Observer: 18.4655, -66.1057 · 10 m",
        "UTC: 2026-10-20T00:30:00Z",
      ].join("\n"),
    );
  });

  it("describes visibility as altitude when up and as a window when down", () => {
    expect(describeVisibility({ above_horizon: true, alt_deg: 21.4, visibility: { state: "UP" } }).text).toBe(
      "∠ 21°",
    );
    const down = describeVisibility(
      {
        above_horizon: false,
        alt_deg: -10,
        visibility: { state: "DOWN", rise_utc: "2026-10-19T23:59:00Z", set_utc: "2026-10-20T13:12:00Z" },
      },
      { timeZone: "America/Puerto_Rico" },
    );
    expect(down.text).toBe("7:59 PM–9:12 AM");
    expect(describeVisibility({ above_horizon: false, visibility: { state: "NEVER_UP" } }).text).toBe(
      "Never rises",
    );
  });
});
