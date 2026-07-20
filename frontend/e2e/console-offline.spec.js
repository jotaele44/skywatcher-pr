import { test, expect } from '@playwright/test';
import { openConsole, waitForMapReady } from './helpers';

test('blank console issues zero external network requests', async ({ page }) => {
  const external = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (!['127.0.0.1', 'localhost'].includes(url.hostname) && !['blob:', 'data:'].includes(url.protocol)) {
      external.push(request.url());
    }
  });
  await openConsole(page);
  await waitForMapReady(page);
  await page.waitForTimeout(750);
  expect(external).toEqual([]);
});
