import { test, expect } from 'playwright/test';

// Explicit failure fixtures exercise chrome without reading mutable sources.
// These tests certify UI behavior only; they do not certify backend data.
test.beforeEach(async ({ page }) => {
 await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname === '/api/auth/me') return route.fulfill({ status: 401, json: { detail: 'Not authenticated' } });
  if (url.pathname.includes('public-settings')) return route.fulfill({json: {public_settings: {requires_auth: false}}});
  if (url.hostname === '127.0.0.1' && url.port === '5419' && !url.pathname.startsWith('/api/')) return route.continue();
  return route.abort('connectionrefused');
 });
});

test('settings outage blocks collections and retry preserves the requested page', async ({ page }) => {
 let available = false;
 let collections = 0;
 await page.route('**/api/apps/public-settings', route => available
  ? route.fulfill({ json: { public_settings: { requires_auth: false } } })
  : route.fulfill({ status: 503, json: { detail: 'Unavailable' } }));
 await page.route('**/api/entities/**', route => { collections++; return route.fulfill({ json: [] }); });
 await page.goto('/review');
 await expect(page.getByRole('alert')).toContainText('Unable to verify application access');
 expect(collections).toBe(0);
 await expect(page).toHaveURL(/\/review$/);
 available = true;
 await page.getByRole('button', { name: 'Retry connection' }).click();
 await expect(page.getByText('Manual Review Queue', { exact: true })).toBeVisible();
 expect(collections).toBeGreaterThan(0);
});

test('malformed settings never imply diagnostic access', async ({ page }) => {
 let collections = 0;
 await page.route('**/api/apps/public-settings', route => route.fulfill({ json: { public_settings: { requires_auth: 'false' } } }));
 await page.route('**/api/entities/**', route => { collections++; return route.fulfill({ json: [] }); });
 await page.goto('/');
 await expect(page.getByRole('alert')).toContainText('Unable to verify application access');
 expect(collections).toBe(0);
});

test('required authentication blocks protected fetches until sign-in succeeds', async ({ page }) => {
 let collections = 0;
 await page.route('**/api/apps/public-settings', route => route.fulfill({ json: { public_settings: { requires_auth: true } } }));
 await page.route('**/api/entities/**', route => { collections++; return route.fulfill({ json: [] }); });
 await page.route('**/api/auth/login', route => route.fulfill({ json: { access_token: 'test-session-token' } }));
 await page.route('**/api/auth/me', route => route.request().headers().authorization === 'Bearer test-session-token' ? route.fulfill({ json: { id: 'fixture-user' } }) : route.fulfill({ status: 401, json: { detail: 'Not authenticated' } }));
 await page.goto('/review');
 await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
 expect(collections).toBe(0);
 await page.getByLabel('Email', { exact: true }).fill('test@example.invalid');
 await page.getByLabel('Password', { exact: true }).fill('test-only-password');
 await page.getByRole('button', { name: 'Log in', exact: true }).click();
 await expect(page.getByText('Manual Review Queue', { exact: true })).toBeVisible();
 expect(collections).toBeGreaterThan(0);
 await expect(page).toHaveURL(/\/review$/);
});

test('backend-required account check failure exposes retry without fetching data', async ({ page }) => {
 let available = false;
 let collections = 0;
 await page.route('**/api/apps/public-settings', route => route.fulfill({ json: { public_settings: { requires_auth: true } } }));
 await page.route('**/api/entities/**', route => { collections++; return route.fulfill({ json: [] }); });
 await page.route('**/api/auth/me', route => available ? route.fulfill({ json: { id: 'fixture-user' } }) : route.fulfill({ status: 503, json: { detail: 'Unavailable' } }));
 await page.goto('/review?access_token=test-session-token');
 await expect(page.getByRole('alert')).toContainText('Unable to verify application access');
 expect(collections).toBe(0);
 available = true;
 await page.getByRole('button', { name: 'Retry connection' }).click();
 await expect(page.getByText('Manual Review Queue', { exact: true })).toBeVisible();
 expect(collections).toBeGreaterThan(0);
});

test('password reset delivery failure retains the address and retries neutrally', async ({ page }) => {
 let available = false;
 await page.route('**/api/apps/public-settings', route => route.fulfill({ json: { public_settings: { requires_auth: true } } }));
 await page.route('**/api/auth/password/reset-request', route => available ? route.fulfill({ json: {} }) : route.fulfill({ status: 503, json: { detail: 'Unavailable' } }));
 await page.goto('/forgot-password');
 await page.getByLabel('Email address').fill('test@example.invalid');
 await page.getByRole('button', { name: 'Send reset link' }).click();
 await expect(page.getByRole('alert')).toContainText('could not be completed');
 await expect(page.getByLabel('Email address')).toHaveValue('test@example.invalid');
 await expect(page.getByText(/If an account exists/)).toHaveCount(0);
 available = true;
 await page.getByRole('button', { name: 'Send reset link' }).click();
 await expect(page.getByText(/If an account exists/)).toBeVisible();
});

test('clipboard rejection stays visible and a successful retry is confirmed', async ({ page }) => {
 await page.addInitScript(() => {
  let attempts = 0;
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
   writeText: async () => { if (++attempts === 1) throw new Error('Denied'); },
  } });
 });
 await page.route('**/api/entities/**', route => route.fulfill({ json: [] }));
 await page.goto('/export');
 const copy = page.getByRole('button', { name: 'Copy', exact: true }).first();
 await copy.click();
 await expect(page.getByRole('alert')).toContainText('Copy failed');
 await expect(page.getByRole('button', { name: 'Copied', exact: true })).toHaveCount(0);
 await copy.click();
 await expect(page.getByRole('button', { name: 'Copied', exact: true })).toBeVisible();
});

test('an authenticated cookie session can load a protected page without a stored token', async ({ page }) => {
 await page.route('**/api/apps/public-settings', route => route.fulfill({ json: { public_settings: { requires_auth: true } } }));
 await page.route('**/api/auth/me', route => route.fulfill({ json: { id: 'cookie-session-user' } }));
 await page.route('**/api/entities/**', route => route.fulfill({ json: [] }));
 await page.goto('/review');
 await expect(page.getByText('Manual Review Queue', { exact: true })).toBeVisible();
 await expect(page).toHaveURL(/\/review$/);
});

for (const destination of ['https://example.invalid/steal', 'http://[invalid', '/login', 'http://127.0.0.1:5419//example.invalid/steal']) {
 test(`successful login safely handles redirect ${destination}`, async ({ page }) => {
  let signedIn = false;
  await page.route('**/api/apps/public-settings', route => route.fulfill({ json: { public_settings: { requires_auth: true } } }));
  await page.route('**/api/auth/me', route => signedIn ? route.fulfill({ json: { id: 'cookie-session-user' } }) : route.fulfill({ status: 401, json: {} }));
  await page.route('**/api/auth/login', route => { signedIn = true; return route.fulfill({ json: {} }); });
  await page.route('**/api/entities/**', route => route.fulfill({ json: [] }));
  await page.goto(`/login?redirect=${encodeURIComponent(destination)}`);
  await page.getByLabel('Email', { exact: true }).fill('test@example.invalid');
  await page.getByLabel('Password', { exact: true }).fill('test-only-password');
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page.locator('.zip-surface')).toBeVisible({ timeout: 15000 });
  await expect(page).toHaveURL('http://127.0.0.1:5419/');
 });
}

for (const kind of ['access', 'write']) {
 test(`clear ${kind} token is one-shot and a replacement survives reload`, async ({ page }) => {
  const authorizations = [];
  await page.route('**/api/apps/public-settings', route => route.fulfill({ json: { public_settings: { requires_auth: kind === 'access' } } }));
  await page.route('**/api/auth/me', route => route.request().headers().authorization === 'Bearer replacement-token' ? route.fulfill({ json: { id: 'fixture-user' } }) : route.fulfill({ status: 401, json: {} }));
  await page.route('**/api/entities/**', route => {
   authorizations.push(route.request().headers().authorization);
   return route.fulfill({ json: [] });
  });
  await page.goto(`/review?clear_${kind}_token=true&${kind}_token=replacement-token`);
  await expect(page.getByText('Manual Review Queue', { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/review$/);
  authorizations.length = 0;
  await page.reload();
  await expect(page.getByText('Manual Review Queue', { exact: true })).toBeVisible();
  expect(authorizations.length).toBeGreaterThan(0);
  expect(authorizations.every(value => value === 'Bearer replacement-token')).toBe(true);
 });
}
for (const width of [390, 1440]) {
 test(`archive design renders and stays within ${width}px viewport`, async ({ page }) => {
  await page.setViewportSize({width, height: 900});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.locator('.zip-surface')).toBeVisible();
  await expect.poll(() => page.locator('#root').innerText()).not.toBe('');
  await page.evaluate(() => document.fonts.ready);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  expect(errors).toEqual([]);
  const css = await page.locator('.zip-surface').evaluate(el => getComputedStyle(el).getPropertyValue('--zip-background'));
  expect(css.trim()).not.toBe('');
 });
}
test('all workflows remain discoverable on phones', async ({page}) => {
 await page.setViewportSize({width:390,height:900});await page.goto('/');
 await page.locator('.zip-mobile-menu > summary').click();
 const menu=page.locator('.zip-mobile-menu'); await expect(menu).toHaveAttribute('open','');
 const links=menu.locator('a');expect(await links.count()).toBeGreaterThan(10);
 await links.nth(2).click();await expect(page.locator('.zip-surface')).toBeVisible();
});


test('failed collections are explicit and recover through visible retry', async ({ page }) => {
 await page.goto('/review');
 await expect(page.getByRole('alert').filter({ hasText: 'Data is incomplete' })).toBeVisible();
 await page.route('**/api/entities/**', route => route.fulfill({ json: [] }));
 await page.getByRole('button', { name: 'Retry data', exact: true }).click();
 await expect(page.getByRole('alert').filter({ hasText: 'Data is incomplete' })).toHaveCount(0);
 await expect(page.getByText('Manual Review Queue', { exact: true })).toBeVisible();
});

test('review notes do not claim success on rejection and retry preserves the draft', async ({ page }) => {
 const review = { id: 'review-test-1', review_id: 'REV-TEST-1', review_status: 'open', reason: 'Review failure fixture', item_type: 'capture', item_id: 'capture-test-1', severity: 'medium', notes: 'Original notes' };
 let rejectWrite = true;
 await page.route('**/api/entities/**', async route => {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (request.method() === 'PATCH') {
   if (rejectWrite) return route.fulfill({ status: 403, json: { detail: 'Write denied for regression test' } });
   return route.fulfill({ json: { ...review, ...request.postDataJSON() } });
  }
  return route.fulfill({ json: path.endsWith('/ManualReviewItems') ? [review] : [] });
 });
 await page.goto('/review');
 await page.getByText('Review failure fixture', { exact: true }).click();
 await page.getByRole('textbox', { name: 'Review notes' }).fill('Keep this draft');
 await page.getByRole('button', { name: 'Save Notes', exact: true }).click();
 await expect(page.getByRole('alert').filter({ hasText: 'Write denied for regression test' })).toBeVisible();
 await expect(page.getByText('Notes saved for this server session', { exact: true })).toHaveCount(0);
 await expect(page.getByRole('textbox', { name: 'Review notes' })).toHaveValue('Keep this draft');
 rejectWrite = false;
 await page.getByRole('button', { name: 'Save Notes', exact: true }).click();
 await expect(page.getByText('Notes saved for this server session', { exact: true })).toBeVisible();
});

test('partial bulk review retains only unfinished selections and safely retries', async ({ page }) => {
 const rows = [1, 2].map(number => ({
  id: `bulk-${number}`, observation_id: `OBS-${number}`, callsign: `FIXTURE-${number}`,
  tail_number: `TEST-${number}`, observed_at: '2026-09-08T12:00:00Z',
  review_status: 'new', source_type: 'fr24_screenshot', confidence_score: 0.5,
  synthetic_flag: true,
 }));
 const attempts = [];
 let failSecond = true;
 await page.route('**/api/entities/**', async route => {
  const request = route.request(); const path = new URL(request.url()).pathname;
  if (request.method() === 'PATCH') {
   const id = path.split('/').pop(); attempts.push(id);
   if (id === 'bulk-2' && failSecond) return route.fulfill({ status: 503, json: { detail: 'Temporary write failure' } });
   return route.fulfill({ json: { ...rows.find(row => row.id === id), ...request.postDataJSON() } });
  }
  return route.fulfill({ json: path.endsWith('/AirspaceObservations') ? rows : [] });
 });
 await page.goto('/observations');
 await page.getByRole('checkbox', { name: 'Select all', exact: true }).click();
 await page.getByRole('button', { name: 'Approve', exact: true }).click();
 await expect(page.getByText('Bulk review incomplete', { exact: true })).toBeVisible();
 await expect(page.getByText('1 selected', { exact: true })).toBeVisible();
 await expect(page.getByRole('button', { name: 'Approve', exact: true })).toBeEnabled();
 expect(attempts).toEqual(['bulk-1', 'bulk-2']);
 failSecond = false;
 await page.getByRole('button', { name: 'Approve', exact: true }).click();
 await expect(page.getByText('1 observation approved', { exact: true })).toBeVisible();
 await expect(page.getByRole('button', { name: 'Approve', exact: true })).toHaveCount(0);
 expect(attempts).toEqual(['bulk-1', 'bulk-2', 'bulk-2']);
});
