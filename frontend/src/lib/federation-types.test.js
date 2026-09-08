// @vitest-environment node
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, it } from 'vitest';
import * as runtime from '@pr-federation/react';

it('binds local declarations to the exact shared runtime source and public exports', () => {
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const source = readFileSync(`${root}node_modules/@pr-federation/react/src/index.jsx`);
  const declarations = readFileSync(`${root}src/types/federation-react.d.ts`, 'utf8');
  const expected = declarations.match(/Upstream source SHA256: ([a-f0-9]{64})/)[1];
  expect(createHash('sha256').update(source).digest('hex')).toBe(expected);
  expect(Object.keys(runtime).sort()).toEqual([
    'FederationThemeProvider', 'useFederationTheme', 'FederationButton', 'FederationPanel',
    'FEDERATION_STATUS_ROLES', 'federationStatusRole', 'federationTone',
    'FederationStatusBadge', 'FederationEmptyState', 'FederationStatCard',
  ].sort());
});
