import { test, expect } from '@playwright/test';
import { installApiFixtures } from './helpers';

const routes = ['/', '/observations', '/aircraft', '/fr24', '/routes', '/infrastructure', '/airports', '/review', '/export', '/readiness', '/calibration'];

test('all pre-existing diagnostic routes remain reachable', async ({ page }) => {
  await installApiFixtures(page);
  for (const route of routes) {
    await page.goto(route);
    await expect(page.getByText('Page not found')).toHaveCount(0);
    await expect(page.locator('main')).toBeVisible();
  }
});
