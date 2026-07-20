import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs';
import path from 'node:path';
import { openConsole, waitForMapReady } from './helpers';

test('console has no serious or critical accessibility violations', async ({ page, browserName }) => {
  await openConsole(page);
  await waitForMapReady(page);
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  const blocking = results.violations.filter((item) => ['serious', 'critical'].includes(item.impact));
  const dir = path.resolve('../reports/console/phase3');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, `ACCESSIBILITY_REPORT_${browserName}.json`), JSON.stringify({
    browser: browserName,
    violations: results.violations,
    blocking_count: blocking.length,
  }, null, 2));
  expect(blocking).toEqual([]);
});
