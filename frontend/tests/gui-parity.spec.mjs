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
