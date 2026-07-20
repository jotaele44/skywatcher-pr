import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { openConsole, waitForMapReady } from './helpers';

test('25 route cycles leave map and observer ledgers balanced', async ({ page, browserName }) => {
  test.skip(browserName !== 'chromium', 'memory stability is measured on the Chromium reference runtime');
  await openConsole(page);
  await waitForMapReady(page);
  const session = await page.context().newCDPSession(page);
  await session.send('HeapProfiler.enable');
  await session.send('HeapProfiler.collectGarbage');
  const before = await page.evaluate(() => performance.memory?.usedJSHeapSize ?? 0);

  for (let cycle = 0; cycle < 25; cycle += 1) {
    await page.getByRole('link', { name: 'Airspace Observations' }).click();
    await expect(page.locator('main')).toBeVisible();
    await expect(page.locator('.maplibregl-canvas')).toHaveCount(0);
    await page.getByRole('link', { name: 'Interactive Console' }).click();
    await waitForMapReady(page);
  }

  await page.getByRole('link', { name: 'Airspace Observations' }).click();
  await expect(page.locator('.maplibregl-canvas')).toHaveCount(0);
  await session.send('HeapProfiler.collectGarbage');
  const after = await page.evaluate(() => performance.memory?.usedJSHeapSize ?? 0);
  const diagnostics = await page.evaluate(() => window.__SKYWATCHER_CONSOLE_DIAGNOSTICS__);
  const report = {
    cycles: 25,
    heap_before_bytes: before,
    heap_after_bytes: after,
    heap_growth_bytes: Math.max(0, after - before),
    diagnostics,
    remaining_canvases: await page.locator('.maplibregl-canvas').count(),
  };
  const dir = path.resolve('../reports/console/phase3');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'MEMORY_STABILITY_REPORT.json'), JSON.stringify(report, null, 2));

  expect(report.remaining_canvases).toBe(0);
  expect(diagnostics.mapsCreated).toBe(diagnostics.mapsRemoved);
  expect(diagnostics.observersCreated).toBe(diagnostics.observersDisconnected);
  if (before && after) expect(report.heap_growth_bytes).toBeLessThan(20 * 1024 * 1024);
});
