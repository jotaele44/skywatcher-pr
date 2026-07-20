import { test, expect } from '@playwright/test';
import { installApiFixtures } from './helpers';

test('WebGL denial fails closed without crashing the application', async ({ page }) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function getContext(type, ...args) {
      if (['webgl', 'webgl2', 'experimental-webgl'].includes(type)) return null;
      return original.call(this, type, ...args);
    };
  });
  await installApiFixtures(page);
  await page.goto('/console');
  await expect(page.getByTestId('console-runtime-unavailable')).toBeVisible();
  await expect(page.getByText(/WebGL context/i)).toBeVisible();
  await expect(page.locator('.maplibregl-canvas')).toHaveCount(0);
});
