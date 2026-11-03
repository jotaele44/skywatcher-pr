import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

function findRepositoryRoot(start) {
  let current = start;
  while (current !== path.dirname(current)) {
    if (fs.existsSync(path.join(current, ".federation", "gui-capabilities.json"))) {
      return current;
    }
    current = path.dirname(current);
  }
  throw new Error("Could not locate .federation/gui-capabilities.json");
}

const here = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = findRepositoryRoot(here);
const manifest = JSON.parse(
  fs.readFileSync(
    path.join(repositoryRoot, ".federation", "gui-capabilities.json"),
    "utf8",
  ),
);

const routes = [
  ...new Set(
    manifest.capabilities
      .filter(
        (capability) =>
          capability.status === "active" && capability.classification !== "internal",
      )
      .flatMap((capability) => capability.frontend?.e2e_routes ?? []),
  ),
].sort();

test("manifest exposes at least one active GUI route", () => {
  expect(routes.length).toBeGreaterThan(0);
});

for (const route of routes) {
  test(`GUI route ${route} is rendered and discoverable`, async ({ page }) => {
    const runtimeFailures = [];
    page.on("pageerror", (error) => {
      runtimeFailures.push(`page error: ${error.message}`);
      console.error(`page error: ${error.message}`);
    });
    page.on("response", (response) => {
      if (response.status() >= 500) {
        runtimeFailures.push(`${response.status()} ${response.url()}`);
      }
    });

    if (route !== "/") {
      await page.goto("/", { waitUntil: "domcontentloaded" });
      const link = page.locator(`a[href="${route}"]`).first();
      await expect(
        link,
        `No clickable GUI navigation reaches ${route}`,
      ).toBeVisible();
      await link.click();
      await expect(page).toHaveURL(new RegExp(`${route.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/?$`));
    } else {
      await page.goto(route, { waitUntil: "domcontentloaded" });
    }

    await expect(page.locator("#root")).toBeVisible();
    await page.waitForTimeout(750);
    await expect(page.locator("body")).not.toContainText(
      /(?:something broke while rendering|page\s+not\s+found|route\s+not\s+found|404\s*—?\s*not\s+found)/i,
    );
    expect(runtimeFailures, runtimeFailures.join("\n")).toEqual([]);
  });
}

test("interactive map exposes spatial and track workflows", async ({ page }) => {
  const runtimeFailures = [];
  page.on("pageerror", (error) => runtimeFailures.push(error.message));
  page.on("response", (response) => {
    if (response.status() >= 500) runtimeFailures.push(`${response.status()} ${response.url()}`);
  });

  await page.goto("/", { waitUntil: "domcontentloaded" });

  const toolsToggle = page.getByRole("button", { name: "Tools" }).first();
  await expect(toolsToggle).toBeVisible();
  await toolsToggle.click();
  await page.getByRole("button", { name: "Buffer" }).first().click();
  await expect(page.getByRole("combobox", { name: "Spatial tool target" }).first()).toBeVisible();

  const trackToggle = page.getByRole("button", { name: "Track" }).first();
  await trackToggle.click();
  await expect(page.getByRole("combobox", { name: "Track aircraft" }).first()).toBeVisible();

  expect(runtimeFailures, runtimeFailures.join("\n")).toEqual([]);
});

test("municipio density failure retries into scoped evidence", async ({ page }) => {
  // This regression exercises the local density API, not upstream basemap uptime.
  await page.route(/^https:\/\/[abc]\.tile\.openstreetmap\.org\//, (route) => route.fulfill({
    status: 200, contentType: "image/png",
    body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAQAAAAEACAYAAABccqhmAAABFUlEQVR4nO3BMQEAAADCoPVP7WsIoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAeAMBPAABPO1TCQAAAABJRU5ErkJggg==", "base64"),
  }));
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  let attempts = 0;
  await page.route("**/geo/municipios/observation_density.geojson", async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        headers: { "access-control-allow-origin": "*" },
        body: JSON.stringify({ detail: "test outage" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify({
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: {
              name: "San Juan",
              geoid: "72127",
              observation_count: 2,
              observation_density_norm: 1,
            },
            geometry: {
              type: "Polygon",
              coordinates: [[[-66.2, 18.3], [-66.0, 18.3], [-66.0, 18.5], [-66.2, 18.5], [-66.2, 18.3]]],
            },
          },
        ],
        matched_count: 2,
        unmatched_observations: 1,
        unresolved_by_name: { Outside: 1 },
        total_observations: 3,
        ambiguous_municipio_candidates: {},
        scope: {
          state: "CANDIDATE_NOT_IDENTITY",
          source_field: "municipality",
          target_field: "name",
          matching: "EXACT_RAW_STRING",
          normalization: "NONE",
          identity_effect: "NONE",
          binding_effect: "AGGREGATION_ONLY",
          geometry_effect: "NONE",
        },
      }),
    });
  });

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Municipios", exact: true }).first().click();
  await expect(page.getByText("Municipio density unavailable; no zero-observation inference was made. HTTP 503").first()).toBeVisible();
  expect(consoleErrors).toEqual([
    "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
  ]);
  consoleErrors.length = 0;
  await page.getByRole("button", { name: "Retry municipio density" }).first().click();
  await expect(page.getByText("2 matched · 1 unresolved · 3 total · identity effect NONE · CANDIDATE_NOT_IDENTITY").first()).toBeVisible();
  expect(attempts).toBe(2);
  expect(consoleErrors).toEqual([]);
});

test("Space-Track distinguishes unavailable counts from materialized zero and retries safely", async ({ page }) => {
  let mode = "unavailable";
  await page.route("**/api/space-track/status", async (route) => {
    if (mode === "failure") {
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "fixture outage" }) });
      return;
    }
    const available = mode === "empty";
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      static_contract: { state: "PASS" }, runtime: { state: "BLOCKED", gates: [] }, sources: [],
      execution: { local_store_present: available, browser_upstream_calls: false, operator_writes: "HARD_DISABLED", credentials_embedded: false },
      materializations: {
        space_objects: { available, object_count: available ? 0 : null, contradiction_count: available ? 0 : null },
        reentry_events: { available, event_count: available ? 0 : null, contradiction_count: available ? 0 : null },
      },
    }) });
  });
  await page.goto("/space-track");
  const objects = page.getByText("Space objects", { exact: true }).locator("..");
  const reentry = page.getByText("Reentry events", { exact: true }).locator("..");
  await expect(objects.getByText("UNKNOWN", { exact: true })).toBeVisible();
  await expect(reentry.getByText("UNKNOWN", { exact: true })).toBeVisible();
  mode = "empty";
  await page.getByRole("button", { name: "Reload local status" }).click();
  await expect(objects.getByText("0", { exact: true })).toBeVisible();
  await expect(reentry.getByText("0", { exact: true })).toBeVisible();
  mode = "failure";
  await page.getByRole("button", { name: "Reload local status" }).click();
  await expect(page.getByText("Local status unavailable", { exact: true })).toBeVisible();
  await expect(objects.getByText("UNKNOWN", { exact: true })).toBeVisible();
  mode = "empty";
  await page.getByRole("button", { name: "Reload local status" }).click();
  await expect(objects.getByText("0", { exact: true })).toBeVisible();
});

test("FR24 capture edits report persistence failures and omit unsupported actions", async ({ page }) => {
  let writeAttempts = 0;
  await page.route("**/entities/FR24Captures**", async (route) => {
    if (route.request().method() === "PATCH") {
      writeAttempts += 1;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        headers: {
          "access-control-allow-origin": "http://127.0.0.1:5173",
          "access-control-allow-credentials": "true",
        },
        body: JSON.stringify({ message: "diagnostic store unavailable" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: {
        "access-control-allow-origin": "http://127.0.0.1:5173",
        "access-control-allow-credentials": "true",
      },
      body: JSON.stringify([{
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
        provenance_note: "E2E capture",
      }]),
    });
  });

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("link", { name: "FR24 Intake", exact: true }).click();
  await page.getByText("capture.json", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "capture.json", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Queue Capture" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Link Observation" })).toHaveCount(0);

  await page.getByRole("button", { name: "Reject Capture", exact: true }).click();
  await expect(page.getByText("Diagnostic update failed", { exact: true })).toBeVisible();
  await expect(page.getByRole("table").getByText("Queued", { exact: true })).toBeVisible();
  await expect(page.locator(".fixed.inset-0.z-50").getByText("Queued", { exact: true })).toBeVisible();
  await expect(page.getByText("Diagnostic state updated", { exact: true })).toHaveCount(0);
  expect(writeAttempts).toBe(1);
});

test("live airspace map exposes the adsb.lol-equivalent controls, layers, replay and aircraft list", async ({ page }) => {
  const runtimeFailures = [];
  page.on("pageerror", (error) => runtimeFailures.push(`page error: ${error.message}`));
  page.on("response", (response) => {
    if (response.status() >= 500) runtimeFailures.push(`${response.status()} ${response.url()}`);
  });
  // Upstream tile, glyph and GeoJSON hosts are not under test; the live feed
  // endpoints are stubbed so the workflow does not depend on adsb.lol uptime.
  await page.route(/^https:\/\//, (route) => route.fulfill({ status: 204 }));
  const json = (route, body) => route.fulfill({
    status: 200,
    contentType: "application/json",
    headers: {
      "access-control-allow-origin": route.request().headers().origin || "*",
      "access-control-allow-credentials": "true",
    },
    body: JSON.stringify(body),
  });
  const source = { provider: "adsb.lol", license: "ODbL-1.0", attribution: "adsb.lol contributors (ODbL 1.0)", persisted: false };
  await page.route(/\/api\/console\/live\/aircraft\?/, (route) => json(route, {
    feed: "adsblol.aircraft", status: "available", reason: null, fetched_at_utc: "2026-11-03T16:32:00Z",
    coverage: { mode: "point_radius", complete: true }, count: 2, source,
    aircraft: [
      { hex: "a37f12", flight: "AAL1512 ", t: "B738", r: "N123AA", alt_baro: 36000, gs: 430, track: 90, lat: 18.3, lon: -66.3, squawk: "3037" },
      { hex: "ae04ef", flight: "PAT079 ", t: "B190", dbFlags: 1, alt_baro: 9000, gs: 250, track: 180, lat: 18.1, lon: -66.6, squawk: "2307" },
    ],
  }));
  await page.route("**/api/console/live/trace/**", (route) => json(route, {
    feed: "adsblol.trace", status: "available", hex: "a37f12", source,
    points: [{ t: 1793723000, lat: 18.2, lon: -66.4, alt_baro: 30000 }, { t: 1793723060, lat: 18.3, lon: -66.3, alt_baro: 36000 }],
  }));
  await page.route("**/api/console/live/routes", (route) => json(route, {
    feed: "adsblol.routes", status: "available", source, routes: [{ callsign: "AAL1512", route: "SJU - MIA", cities: "San Juan - Miami" }],
  }));
  await page.route(/\/api\/console\/live\/replay\?/, (route) => json(route, {
    feed: "adsblol.replay", status: "available", clamped_to_latest: true, ts_utc: "2026-11-03T16:01:00Z", source,
    fields: ["hex", "lat", "lon", "alt_baro", "gs", "source_type", "flight", "squawk"],
    frames: [
      { t: 1793721660, interval_s: 10, aircraft: [["a37f12", 18.30, -66.30, 36000, 430, "adsb_icao", "AAL1512", "3037"]] },
      { t: 1793721670, interval_s: 10, aircraft: [["a37f12", 18.31, -66.29, 36000, 430, "adsb_icao", "AAL1512", "3037"]] },
    ],
  }));

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.locator('a[href="/live"]').first().click();
  await expect(page).toHaveURL(/\/live\/?$/);

  for (const name of [/Only show military/i, /\(H\)ome/, /All \(T\)racks/, /Repla\(Y\)/, /^Map layers$/,
    /aircraft sidebar/, /^Fullscreen$/, /^Settings$/, /\(L\)abels/, /extensi\(O\)ns/, /trac\(K\) labels/,
    /\(M\)ulti-select/, /\(P\)ersistence/, /\(I\)solate/, /\(R\)andom/, /\(F\)ollow selected/, /^Zoom in$/, /^Zoom out$/]) {
    await expect(page.getByRole("button", { name }).first()).toBeVisible();
  }

  await page.getByRole("button", { name: /Expand aircraft sidebar/ }).click();
  const list = page.getByRole("complementary", { name: "Aircraft list" });
  await expect(list.getByText("Live aircraft in view: 2")).toBeVisible();
  await list.getByText("AAL1512").first().click();
  await expect(list.getByText("SJU - MIA (San Juan - Miami)")).toBeVisible();
  await expect(list.getByText("2 points")).toBeVisible();

  await page.getByRole("button", { name: /Collapse aircraft sidebar/ }).click();
  await page.getByRole("button", { name: /^Map layers$/ }).click();
  const layers = page.getByRole("dialog", { name: "Map layers" });
  await expect(layers.getByRole("radio", { name: /ESRI\.com Satellite/ })).toBeChecked();
  await layers.getByRole("radio", { name: /OpenStreetMap DE/ }).check();
  await layers.getByRole("checkbox", { name: /NOAA Infrared Sat/ }).check();
  await layers.getByRole("checkbox", { name: /NOAA Radar/ }).check();
  await expect(layers.getByText("UK AWACS Orbits")).toBeVisible();
  await page.getByRole("button", { name: "Close layer menu" }).click();

  await page.getByRole("button", { name: /Repla\(Y\)/ }).click();
  const replay = page.getByRole("region", { name: "Replay controls" });
  await expect(replay).toBeVisible();
  await expect(replay.getByText(/UTC: 16:01:\d\d/)).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: /REPLAY/ })).toBeVisible();
  await replay.getByRole("button", { name: "Pause replay" }).click();
  await replay.getByRole("button", { name: /return to live/ }).click();
  await expect(replay).toBeHidden();

  expect(runtimeFailures, runtimeFailures.join("\n")).toEqual([]);
});
