import { test, expect } from '@playwright/test';
import { openConsole, waitForMapReady } from './helpers';

test('console route initializes the offline runtime and permanent attribution', async ({ page }) => {
  await openConsole(page);
  await waitForMapReady(page);
  await expect(page.getByText('OFFLINE BLANK STYLE · NO PROVIDER KEY')).toBeVisible();
  await expect(page.getByText('External requests blocked')).toBeVisible();
  await expect(page.getByRole('button', { name: /reset view/i })).toBeEnabled();
});

test('geolocation is not requested before explicit activation', async ({ page }) => {
  await page.addInitScript(() => {
    window.__GEOLOCATION_CALLS__ = 0;
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: {
        getCurrentPosition(success) {
          window.__GEOLOCATION_CALLS__ += 1;
          success({ coords: { longitude: -66.05, latitude: 18.42, accuracy: 5 } });
        },
      },
    });
  });
  await openConsole(page);
  await waitForMapReady(page);
  await expect.poll(() => page.evaluate(() => window.__GEOLOCATION_CALLS__)).toBe(0);
  await page.getByRole('button', { name: /current location/i }).click();
  await expect.poll(() => page.evaluate(() => window.__GEOLOCATION_CALLS__)).toBe(1);
  const persisted = await page.evaluate(() => ({ ...localStorage, ...sessionStorage }));
  expect(JSON.stringify(persisted)).not.toContain('-66.05');
  expect(JSON.stringify(persisted)).not.toContain('18.42');
});
