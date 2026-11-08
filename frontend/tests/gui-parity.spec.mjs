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

test("Sky Target Finder searches, charts and copies coordinates like the telescope app", async ({ page }) => {
  const headers = {
    "access-control-allow-origin": "http://127.0.0.1:5173",
    "access-control-allow-credentials": "true",
  };
  const observer = { lat_deg: 18.4655, lon_deg: -66.1057, elev_m: 10 };
  const at = "2026-10-20T00:30:00Z";
  const satellites = { state: "NOT_MATERIALIZED", object_count: null, propagated: 0, skipped_count: 0, skipped: [] };
  const base = {
    aliases: [],
    constellation: "Cyg",
    magnitude: 7,
    size_arcmin: null,
    above_horizon: true,
    visibility: { state: "UP", rise_utc: "2026-10-19T17:00:00Z", set_utc: "2026-10-20T09:12:00Z", transit_utc: null, transit_alt_deg: null },
    filter_hint: null,
    satellite: null,
  };
  const veil = {
    ...base,
    id: "caldwell:C33",
    kind: "caldwell",
    designation: "C 33",
    long_designation: "Caldwell 33",
    name: "East Veil Nebula",
    display: "C 33 (East Veil Nebula)",
    object_type: "supernova_remnant",
    ra_j2000_deg: 314.0795,
    dec_j2000_deg: 31.7428,
    alt_deg: 75.12,
    az_deg: 250.31,
    filter_hint: { label: "Duo-Band", basis: "heuristic" },
    match: { field: "name", text: "East Veil Nebula" },
  };
  const marfak = {
    ...base,
    id: "star:hip:5542",
    kind: "star",
    designation: "Theta Cassiopeiae",
    long_designation: "Theta Cassiopeiae",
    name: "Marfak",
    display: "Theta Cassiopeiae (Marfak)",
    object_type: "star",
    ra_j2000_deg: 17.7757,
    dec_j2000_deg: 55.1499,
    alt_deg: 38.31,
    az_deg: 20.5,
    match: { field: "alias", text: "Marfak-East" },
  };
  const m31 = {
    ...base,
    id: "messier:M31",
    kind: "messier",
    designation: "M 31",
    long_designation: "Messier 31",
    name: "Andromeda Galaxy",
    display: "M 31 (Andromeda Galaxy)",
    object_type: "galaxy",
    ra_j2000_deg: 10.6751,
    dec_j2000_deg: 41.2667,
    alt_deg: 32.4,
    az_deg: 60.1,
    recommend: { best_alt_deg: 79.6, best_utc: "2026-10-20T04:10:00Z", score: 0.91 },
  };
  const json = (body) => ({ status: 200, contentType: "application/json", headers, body: JSON.stringify(body) });

  await page.addInitScript(() => {
    window.__copied = [];
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async (text) => { window.__copied.push(text); } },
    });
  });
  await page.route(/\/api\/space-track\/sky\/recommend(\?|$)/, (route) =>
    route.fulfill(json({
      schema_version: "skywatcher.sky-recommend/v1",
      observer,
      at_utc: at,
      dark_window: { start_utc: "2026-10-19T22:46:41Z", end_utc: "2026-10-20T09:32:04Z", sun_alt_deg: -12 },
      targets: [m31],
    })));
  await page.route(/\/api\/space-track\/sky\/targets(\?|$)/, (route) => {
    const q = new URL(route.request().url()).searchParams.get("q") || "";
    route.fulfill(json({
      schema_version: "skywatcher.sky-targets/v1",
      observer,
      at_utc: at,
      query: q,
      kind: "all",
      count: q === "East" ? 2 : 0,
      targets: q === "East" ? [veil, marfak] : [],
      satellites,
      catalog: { schema_version: "skywatcher.sky-catalog/v1", data_license: "CC-BY-SA-4.0" },
    }));
  });
  await page.route(/\/api\/space-track\/sky\/chart(\?|$)/, (route) =>
    route.fulfill(json({
      schema_version: "skywatcher.sky-chart/v1",
      observer,
      at_utc: at,
      fov_deg: 6,
      radius_deg: 12,
      limiting_magnitude: 7.5,
      target: veil,
      stars: [{ alt: 76.2, az: 252.4, mag: 2.48, id: "star:hip:102488", label: "Epsilon Cygni" }],
      lines: [],
      constellation_labels: [],
      dso_markers: [],
      solar_system: [],
      satellites: [],
    })));

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("link", { name: "Sky Target Finder", exact: true }).click();
  await expect(page).toHaveURL(/\/space-track\/sky\/?$/);
  await expect(page.locator('a[href="/space-track/sky"]')).toHaveAttribute("aria-current", "page");
  await expect(page.locator('a[href="/space-track"]')).not.toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("button", { name: "M 31 (Andromeda Galaxy)", exact: true })).toBeVisible();

  await page.getByRole("searchbox", { name: "Search sky targets" }).fill("East");
  await expect(page.getByRole("button", { name: "C 33 (East Veil Nebula)", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Theta Cassiopeiae (Marfak)", exact: true })).toBeVisible();
  await expect(page.getByText("matches Marfak-East", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "C 33 (East Veil Nebula)", exact: true }).click();
  const chart = page.getByRole("img", { name: "Sky chart centred on Caldwell 33" });
  await expect(chart).toBeVisible();
  await expect(chart.getByText("Caldwell 33", { exact: true })).toBeVisible();
  await expect(chart.getByText("FOV 6.0°", { exact: true })).toBeVisible();
  await expect(chart.getByText("Epsilon Cygni", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Copy target coordinates", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.__copied.length)).toBe(1);
  const copied = await page.evaluate(() => window.__copied[0]);
  expect(copied).toContain("C 33 (East Veil Nebula)");
  expect(copied).toContain("RA (J2000): 20h 56m 19.1s  Dec (J2000): +31° 44′ 34″");
  expect(copied).toContain("UTC: 2026-10-20T00:30:00Z");
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

test("Sky Cameras lists public cameras, switches to links only, and queues contributions for review", async ({ page }) => {
  const headers = {
    "access-control-allow-origin": "http://127.0.0.1:5173",
    "access-control-allow-credentials": "true",
  };
  const json = (body, status = 200) => ({ status, contentType: "application/json", headers, body: JSON.stringify(body) });
  // Keep third-party players offline in CI; the iframe element is what we assert on.
  await page.route(/youtube-nocookie\.com|player\.vimeo\.com/, (route) => route.abort());

  let submitted = null;
  const pending = {
    id: "0123456789abcdef0123456789abcdef",
    kind: "camera_link",
    title: "Playa Jobos",
    url: "https://example.org/jobos",
    categories: ["beach"],
    municipality: "Isabela",
    license: "display-only",
    contributor: null,
    contact: null,
    description: null,
    status: "pending",
    media_url: null,
    file_name: null,
  };
  await page.route(/\/api\/sky-cameras\/submissions(\?|$)/, (route) => {
    if (route.request().method() === "POST") {
      submitted = route.request().postDataBuffer()?.toString("latin1") ?? "";
      return route.fulfill(json({ id: pending.id, status: "pending", message: "Thanks! Your submission is in the review queue and will appear once a reviewer approves it." }, 201));
    }
    return route.fulfill(json({ status: "pending", count: 1, submissions: [pending] }));
  });
  let decision = null;
  await page.route(/\/api\/sky-cameras\/submissions\/[0-9a-f]+\/decision$/, (route) => {
    decision = route.request().postDataJSON();
    return route.fulfill(json({ ...pending, status: decision.decision }));
  });

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("link", { name: "Sky Cameras", exact: true }).click();
  await expect(page).toHaveURL(/\/sky-cameras\/?$/);
  await expect(page.locator('a[href="/sky-cameras"]')).toHaveAttribute("aria-current", "page");

  // Real catalog from the backend: an embeddable stream gets a player, a link-out camera does not.
  const sonesta = page.getByRole("article", { name: "Isla Verde Beach — Royal Sonesta San Juan", exact: true });
  await expect(sonesta.locator("iframe")).toHaveAttribute("src", /^https:\/\/www\.youtube-nocookie\.com\/embed\//);
  const condado = page.getByRole("article", { name: "Condado Lagoon", exact: true });
  await expect(condado.locator("iframe")).toHaveCount(0);
  await expect(condado.getByRole("link", { name: /Open live stream/ })).toHaveAttribute("href", /skylinewebcams\.com/);
  await expect(page.getByRole("region", { name: "Coverage" })).toContainText("/78");

  await page.getByRole("button", { name: "Players on" }).click();
  await expect(page.locator("iframe")).toHaveCount(0);
  await page.getByRole("button", { name: "Links only" }).click();

  await page.getByRole("group", { name: "Category" }).getByRole("button", { name: "Lagoon" }).click();
  await expect(condado).toBeVisible();
  await expect(sonesta).toHaveCount(0);

  await page.getByRole("button", { name: "Contribute" }).click();
  const form = page.getByRole("form", { name: "Contribute" });
  await form.getByLabel("Title").fill("Playa Jobos");
  await form.getByLabel(/Camera page link/).fill("https://example.org/jobos");
  await form.getByLabel("Beach", { exact: true }).check();
  await form.getByLabel(/already shown to the public/).check();
  await form.getByLabel(/no identifiable people/).check();
  await form.getByRole("button", { name: "Send for review" }).click();
  await expect(form.getByRole("status")).toContainText("review queue");
  expect(submitted).toContain("camera_link");
  expect(submitted).toContain("https://example.org/jobos");

  await page.getByRole("button", { name: "Review queue" }).click();
  const queue = page.getByRole("region", { name: "Review queue" });
  await expect(queue.getByText("Playa Jobos", { exact: true })).toBeVisible();
  await queue.getByRole("button", { name: "Approve" }).click();
  await expect.poll(() => decision?.decision).toBe("approved");
});
