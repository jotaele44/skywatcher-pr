// End-to-end test of Skywatcher's Launch Pad, the screen the desktop app opens
// on before the backend starts.
//
// The page is the runtime's real render of desktop/config.py, and every call it
// makes goes to the runtime's real DesktopBridge, served by
// tests/support/launchpad_harness.py. Only the native window is replaced: a
// window.pywebview.api shim forwards each call over HTTP. After Launch, the
// session is applied the way the desktop launcher applies it and the real
// backend answers under /app, behind the runtime's Guest guard.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const GUEST_REFUSAL = /Guest sessions are read-only/;
// An unknown entity type: a create only adds a row to the in-memory session
// overlay, so nothing is written to disk.
const CREATE = "/app/api/entities/launchpad_e2e_probe";

async function openLaunchPad(page) {
  await page.addInitScript(() => {
    const call = async (method, args) => {
      const response = await fetch(`/bridge/${method}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(args),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || body.detail || response.statusText);
      return body;
    };
    // pywebview exposes the bridge methods as promise-returning functions.
    window.pywebview = { api: new Proxy({}, { get: (_, method) => (...args) => call(method, args) }) };
  });
  await page.goto("/");
  await page.evaluate(() => window.dispatchEvent(new Event("pywebviewready")));
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator("#rows .row")).toHaveCount(4);
}

async function sessionWithMode(request, mode) {
  await expect.poll(async () => (await (await request.get("/session")).json()).mode).toBe(mode);
  return (await request.get("/session")).json();
}

async function blockingViolations(page) {
  const axe = await new AxeBuilder({ page }).analyze();
  return axe.violations.filter(({ impact }) => impact === "critical" || impact === "serious");
}

test("shows Skywatcher's own readiness, start pages and entry modes", async ({ page }) => {
  await openLaunchPad(page);
  for (const label of ["Workspace", "Reference data", "Flight archive", "Sky camera submissions"]) {
    await expect(page.locator("#rows")).toContainText(label);
  }
  const starts = await page.locator("#start option").evaluateAll((options) => options.map((o) => o.value));
  expect(starts).toEqual([
    "/", "/console", "/observations", "/aircraft", "/fr24", "/routes", "/infrastructure",
    "/airports", "/review", "/export", "/readiness", "/calibration", "/analysis",
    "/spatial-truth", "/flight-archive", "/space-track", "/space-track/sky", "/sky-cameras",
  ]);
  await expect(page.getByRole("radio", { name: /Guest/ })).toBeVisible();
  await expect(page.getByRole("radio", { name: /Operator/ })).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth),
  ).toBe(false);
});

test("has no serious accessibility violation with every option active", async ({ page }) => {
  await openLaunchPad(page);
  await page.getByRole("radio", { name: /Operator/ }).check();
  const blocking = await blockingViolations(page);
  expect(blocking, JSON.stringify(blocking, null, 2)).toEqual([]);
});

test("in Guest, the only violation is the runtime's dimmed locked options", async ({ page }) => {
  // Known defect in the pinned shared runtime, not in this repository: it dims
  // an Operator-only option in Guest with `.option.locked { opacity: .55 }`,
  // which takes its help text to about 2.4:1. Fixed in the hub's prii_desktop
  // (thehub-pr#435); tighten this test to zero violations when the
  // requirements-desktop.txt pin moves past that fix. Anything else fails it.
  await openLaunchPad(page);
  await page.getByRole("radio", { name: /Guest/ }).check();
  const blocking = await blockingViolations(page);
  expect(blocking.map(({ id }) => id)).toEqual(["color-contrast"]);
  const insideLockedOption = await Promise.all(
    blocking[0].nodes.map(({ target }) =>
      page.locator(target.join(" ")).evaluate((node) => Boolean(node.closest(".option.locked"))),
    ),
  );
  expect(insideLockedOption.length).toBeGreaterThan(0);
  expect(insideLockedOption.every(Boolean)).toBe(true);
});

test("Guest opens on the chosen page, may search, and is refused writes", async ({ page, request }) => {
  await openLaunchPad(page);
  await page.getByRole("radio", { name: /Guest/ }).check();
  await expect(page.locator("#option-camera_submissions_per_hour")).toBeDisabled();
  await page.getByLabel("Starting page").selectOption("/console");
  await page.getByRole("button", { name: "Launch", exact: true }).click();

  const session = await sessionWithMode(request, "guest");
  expect(session.start_route).toBe("/console");
  expect((await request.get("/app/health")).status()).toBe(200);

  // The two read-only POSTs the declaration allows reach their handlers.
  const query = await request.post("/app/api/query", { data: {} });
  expect(query.status()).toBe(400);
  expect((await query.json()).detail).toBe("Missing 'prompt'");
  const filter = await request.post("/app/api/entities/launchpad_e2e_probe/filter", { data: {} });
  expect(filter.status()).toBe(200);

  const write = await request.post(CREATE, { data: { name: "probe" } });
  expect(write.status()).toBe(403);
  expect((await write.json()).detail).toMatch(GUEST_REFUSAL);
});

test("Operator options reach the backend and writes get through", async ({ page, request }) => {
  await openLaunchPad(page);
  await page.getByRole("radio", { name: /Operator/ }).check();
  await expect(page.locator("#option-camera_submissions_per_hour")).toBeEnabled();
  await page.locator("#option-camera_submissions_per_hour").selectOption("60");
  await page.getByLabel("Starting page").selectOption("/sky-cameras");
  await page.getByRole("button", { name: "Launch", exact: true }).click();

  const session = await sessionWithMode(request, "operator");
  expect(session.start_route).toBe("/sky-cameras");
  expect(session.env.SKYWATCHER_SKY_CAMERAS_SUBMISSIONS_PER_HOUR).toBe("60");

  const write = await request.post(CREATE, { data: { name: "probe" } });
  expect(write.status()).toBe(200);
  expect((await write.json())._session_only).toBe(true);
});
