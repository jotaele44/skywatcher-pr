import { test, expect } from '@playwright/test';
import { openConsole, waitForMapReady } from './helpers';

test('console operates from the local desktop-server origin and exposes a native probe contract', async ({ page }) => {
  await openConsole(page);
  await waitForMapReady(page);
  const result = await page.evaluate(() => ({
    protocol: location.protocol,
    host: location.hostname,
    route: location.pathname,
    webgl: window.__SKYWATCHER_CONSOLE_DIAGNOSTICS__?.webglSupported,
    runtime: window.__SKYWATCHER_CONSOLE_DIAGNOSTICS__?.runtimeStatus,
  }));
  expect(result.protocol).toBe('http:');
  expect(['127.0.0.1', 'localhost']).toContain(result.host);
  expect(result.route).toBe('/console');
  expect(result.webgl).toBe(true);
  expect(result.runtime).toBe('ready');
});
