import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

const ROOT = path.resolve(process.cwd());
const REPO_ROOT = path.resolve(ROOT, '..');
const REPORT_DIR = path.resolve(REPO_ROOT, 'reports/console/phase3');
fs.mkdirSync(REPORT_DIR, { recursive: true });

function bytes(file) { return fs.statSync(file).size; }
function gzipBytes(file) { return zlib.gzipSync(fs.readFileSync(file), { level: 9 }).length; }

const manifestPath = path.join(ROOT, 'dist/.vite/manifest.json');
if (!fs.existsSync(manifestPath)) throw new Error('Vite manifest missing; run npm run build first');
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
const consoleEntry = Object.entries(manifest).find(([key]) => key.endsWith('src/pages/AirspaceConsole.jsx'));
if (!consoleEntry) throw new Error('lazy AirspaceConsole chunk missing from Vite manifest');
const [manifestKey, entry] = consoleEntry;
const chunkFiles = new Set();
function collect(item) {
  if (!item || chunkFiles.has(item.file)) return;
  chunkFiles.add(item.file);
  (item.imports || []).forEach((key) => collect(manifest[key]));
}
collect(entry);
const chunkStats = [...chunkFiles].map((file) => {
  const absolute = path.join(ROOT, 'dist', file);
  return { file, bytes: bytes(absolute), gzip_bytes: gzipBytes(absolute) };
});
const consoleGzip = chunkStats.reduce((sum, item) => sum + item.gzip_bytes, 0);
const budget = 600 * 1024;
const performance = {
  generated_at_utc: new Date().toISOString(),
  manifest_key: manifestKey,
  lazy_chunk: entry.file,
  chunk_files: chunkStats,
  aggregate_gzip_bytes: consoleGzip,
  budget_gzip_bytes: budget,
  budget_pass: consoleGzip <= budget,
  lazy_loaded: Boolean(entry.isDynamicEntry),
};
fs.writeFileSync(path.join(REPORT_DIR, 'PERFORMANCE_REPORT.json'), `${JSON.stringify(performance, null, 2)}\n`);
fs.writeFileSync(path.join(REPORT_DIR, 'PERFORMANCE_REPORT.md'), `# Phase 3 Performance Report\n\n- Lazy console entry: \`${entry.file}\`\n- Dynamic entry: **${performance.lazy_loaded}**\n- Aggregate compressed bytes: **${consoleGzip}**\n- Budget: **${budget}**\n- Budget status: **${performance.budget_pass ? 'PASS' : 'FAIL'}**\n\n## Chunks\n\n| File | Bytes | Gzip bytes |\n|---|---:|---:|\n${chunkStats.map((item) => `| \`${item.file}\` | ${item.bytes} | ${item.gzip_bytes} |`).join('\n')}\n`);

const directPackages = [
  'maplibre-gl', '@playwright/test', 'vitest', '@vitest/coverage-v8', 'jsdom',
  '@testing-library/react', '@testing-library/jest-dom', '@testing-library/user-event',
  'axe-core', '@axe-core/playwright',
];
const licenses = directPackages.map((name) => {
  const pkgPath = path.join(ROOT, 'node_modules', name, 'package.json');
  const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
  return {
    name: pkg.name,
    version: pkg.version,
    license: pkg.license || pkg.licenses || 'UNKNOWN',
    repository: typeof pkg.repository === 'string' ? pkg.repository : pkg.repository?.url || null,
    direct_scope: name === 'maplibre-gl' ? 'runtime' : 'development',
  };
});
const unknownLicenses = licenses.filter((item) => item.license === 'UNKNOWN');
const licenseReport = {
  generated_at_utc: new Date().toISOString(),
  dependencies: licenses,
  unknown_license_count: unknownLicenses.length,
  status: unknownLicenses.length ? 'fail' : 'pass',
};
fs.writeFileSync(path.join(REPORT_DIR, 'DEPENDENCY_LICENSE_LEDGER.json'), `${JSON.stringify(licenseReport, null, 2)}\n`);
fs.writeFileSync(path.join(REPORT_DIR, 'DEPENDENCY_LICENSE_LEDGER.md'), `# Phase 3 Dependency License Ledger\n\n| Package | Version | Scope | License |\n|---|---:|---|---|\n${licenses.map((item) => `| \`${item.name}\` | ${item.version} | ${item.direct_scope} | ${String(item.license)} |`).join('\n')}\n\nUnknown licenses: **${unknownLicenses.length}**\n`);

const coveragePath = path.join(ROOT, 'coverage/coverage-summary.json');
const coverage = fs.existsSync(coveragePath) ? JSON.parse(fs.readFileSync(coveragePath, 'utf8')).total : null;
const acceptance = {
  generated_at_utc: new Date().toISOString(),
  exact_maplibre_pin: '5.24.0',
  lazy_console_chunk: performance.lazy_loaded,
  compressed_bundle_budget_pass: performance.budget_pass,
  critical_coverage: coverage,
  direct_dependency_licenses_complete: unknownLicenses.length === 0,
};
fs.writeFileSync(path.join(REPORT_DIR, 'MAP_RUNTIME_ACCEPTANCE_LEDGER.json'), `${JSON.stringify(acceptance, null, 2)}\n`);

if (!performance.lazy_loaded || !performance.budget_pass || unknownLicenses.length) process.exit(1);
console.log(JSON.stringify({ performance, licenseReport, acceptance }, null, 2));
