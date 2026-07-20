import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import baseline from './visual-baseline.json' with { type: 'json' };
import { openConsole, waitForMapReady } from './helpers';

test('console shell satisfies the committed visual geometry baseline', async ({ page, browserName }) => {
  test.skip(browserName !== 'chromium', 'single reference renderer avoids cross-engine font rasterization noise');
  await page.setViewportSize(baseline.viewport);
  await openConsole(page);
  await waitForMapReady(page);

  const shell = page.getByTestId('airspace-console-shell');
  const map = page.getByTestId('airspace-map-region');
  const toolbar = page.getByRole('banner', { name: 'Interactive console toolbar' });
  const attribution = page.getByTestId('permanent-map-attribution');
  const [shellBox, mapBox, toolbarBox, attributionBox, dimensions] = await Promise.all([
    shell.boundingBox(), map.boundingBox(), toolbar.boundingBox(), attribution.boundingBox(),
    page.evaluate(() => ({
      innerWidth: window.innerWidth,
      innerHeight: window.innerHeight,
      scrollWidth: document.documentElement.scrollWidth,
      scrollHeight: document.documentElement.scrollHeight,
    })),
  ]);
  expect(shellBox.width).toBeGreaterThanOrEqual(baseline.shell.minWidth);
  expect(shellBox.height).toBeGreaterThanOrEqual(baseline.shell.minHeight);
  expect(mapBox.width).toBeGreaterThanOrEqual(baseline.map.minWidth);
  expect(mapBox.height).toBeGreaterThanOrEqual(baseline.map.minHeight);
  expect(toolbarBox.height).toBeGreaterThanOrEqual(baseline.toolbar.minHeight);
  expect(toolbarBox.height).toBeLessThanOrEqual(baseline.toolbar.maxHeight);
  expect(attributionBox.height).toBeGreaterThanOrEqual(baseline.attribution.minHeight);
  expect(attributionBox.height).toBeLessThanOrEqual(baseline.attribution.maxHeight);
  expect(dimensions.scrollWidth - dimensions.innerWidth).toBeLessThanOrEqual(baseline.maxPageOverflowPixels);
  expect(dimensions.scrollHeight - dimensions.innerHeight).toBeLessThanOrEqual(baseline.maxPageOverflowPixels);

  const screenshot = await page.screenshot({ animations: 'disabled', fullPage: true });
  const report = {
    browser: browserName,
    baseline,
    geometry: { shell: shellBox, map: mapBox, toolbar: toolbarBox, attribution: attributionBox, dimensions },
    screenshot_sha256: crypto.createHash('sha256').update(screenshot).digest('hex'),
    status: 'pass',
  };
  const dir = path.resolve('../reports/console/phase3');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'VISUAL_REGRESSION_REPORT.json'), JSON.stringify(report, null, 2));
  fs.writeFileSync(path.join(dir, 'VISUAL_REGRESSION_SCREENSHOT.png'), screenshot);
});


test('mobile console keeps attribution and map workspace visible without horizontal overflow', async ({ page, browserName }) => {
  test.skip(browserName !== 'chromium', 'mobile visual geometry uses the Chromium reference runtime');
  await page.setViewportSize({ width: 390, height: 844 });
  await openConsole(page);
  await waitForMapReady(page);
  await expect(page.getByTestId('permanent-map-attribution')).toBeVisible();
  const mapBox = await page.getByTestId('airspace-map-region').boundingBox();
  expect(mapBox.height).toBeGreaterThan(200);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
});
