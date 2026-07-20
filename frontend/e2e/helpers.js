import { expect } from '@playwright/test';

export const CAPABILITIES = {
  api_version: '0.3.0',
  capability_count: 24,
  capabilities: [
    { id: 'map_navigation', status: 'available', reason: 'Local MapLibre runtime implemented.' },
    { id: 'geolocation', status: 'available', reason: 'Manual browser geolocation implemented.' },
    { id: 'basemap_controls', status: 'available', reason: 'Offline basemap registry implemented.' },
    { id: 'aircraft_viewport_list', status: 'unavailable_no_artifact', reason: 'No operational state artifact.' },
    { id: 'playback_timeline', status: 'unavailable_no_artifact', reason: 'No track artifact.' },
    { id: 'airport_operations', status: 'unavailable_no_artifact', reason: 'No airport state artifact.' },
  ],
  policy: {
    fr24_scraping: false,
    proprietary_asset_copying: false,
    local_blank_style_available: true,
    external_basemap_configured: false,
    provider_keys_required: false,
    offline_console_startup: true,
  },
};

export const REPOSITORIES = {
  repository_count: 8,
  repositories: [
    { repository: 'aircraft_states', status: 'unavailable_no_artifact', reason: 'No configured artifact.', record_count: 0 },
    { repository: 'track_points', status: 'unavailable_no_artifact', reason: 'No configured artifact.', record_count: 0 },
  ],
};

export async function installApiFixtures(page) {
  await page.route('**/api/console/capabilities', (route) => route.fulfill({ json: CAPABILITIES }));
  await page.route('**/api/console/repositories', (route) => route.fulfill({ json: REPOSITORIES }));
  await page.route('**/api/auth/me', (route) => route.fulfill({ status: 401, json: { detail: 'local diagnostic mode' } }));
  await page.route('**/api/apps/public-settings', (route) => route.fulfill({ json: { id: 'skywatcher-pr', public_settings: { requires_auth: false } } }));
  await page.route('**/api/entities/**', (route) => route.fulfill({ json: [] }));
}

export async function openConsole(page) {
  await installApiFixtures(page);
  await page.goto('/console');
  await expect(page.getByRole('heading', { name: 'Interactive Airspace Console' })).toBeVisible();
  await expect(page.getByTestId('permanent-map-attribution')).toBeVisible();
  await expect(page.getByTestId('airspace-console-shell')).toBeVisible();
}

export async function waitForMapReady(page) {
  await expect.poll(async () => page.evaluate(() => window.__SKYWATCHER_CONSOLE_DIAGNOSTICS__?.runtimeStatus), {
    timeout: 20_000,
  }).toBe('ready');
  await expect(page.locator('.maplibregl-canvas')).toHaveCount(1);
}
