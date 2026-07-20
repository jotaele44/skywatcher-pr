import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(process.cwd());
const REPORT_DIR = path.resolve(ROOT, '../reports/console/phase3');
const scanRoots = [
  'src/components/console',
  'src/pages/AirspaceConsole.jsx',
  'src/App.jsx',
  'src/components/skywatcher/Layout.jsx',
  'src/components/skywatcher/Sidebar.jsx',
  'src/lib/SkywatcherData.jsx',
];
const sourceExtensions = new Set(['.js', '.jsx', '.mjs', '.json', '.html']);
const findings = [];

function walk(target) {
  const absolute = path.resolve(ROOT, target);
  if (!fs.existsSync(absolute)) return [];
  const stat = fs.statSync(absolute);
  if (stat.isFile()) return [absolute];
  return fs.readdirSync(absolute).flatMap((entry) => walk(path.relative(ROOT, path.join(absolute, entry))));
}

const checks = [
  { id: 'external_http_url', pattern: /['\"]((?:https?:)?\/\/[^'\"]+)['\"]/g, severity: 'high', filter: (match) => !/^(?:https?:)?\/\/(?:127\.0\.0\.1|localhost)(?::|\/|$)/i.test(match[1]) },
  { id: 'mapbox_protocol', pattern: /['\"](mapbox:\/\/[^'\"]+)['\"]/gi, severity: 'high' },
  { id: 'credential_assignment', pattern: /(?:api[-_]?key|access[-_]?token|client[-_]?secret|password)\s*[:=]\s*['"][^'"]+['"]/gi, severity: 'critical' },
  { id: 'fr24_visual_asset_reference', pattern: /(?:flightradar24\.com|(?:fr24|flightradar24)[^\n'\"]{0,20}\.(?:png|jpe?g|webp|svg|pbf|mvt))/gi, severity: 'high' },
  { id: 'console_location_persistence', pattern: /(?:localStorage|sessionStorage)\.(?:setItem|\w+)\s*\([^\n]*(?:latitude|longitude|geolocation|location)/gi, severity: 'high' },
];

const files = scanRoots.flatMap(walk).filter((file) => sourceExtensions.has(path.extname(file)));
for (const file of files) {
  const text = fs.readFileSync(file, 'utf8');
  for (const check of checks) {
    for (const match of text.matchAll(check.pattern)) {
      if (check.filter && !check.filter(match)) continue;
      findings.push({
        check: check.id,
        severity: check.severity,
        file: path.relative(ROOT, file),
        index: match.index,
        excerpt: match[0].slice(0, 120),
      });
    }
  }
}

const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));
const pin = pkg.dependencies?.['maplibre-gl'];
if (pin !== '5.24.0') {
  findings.push({ check: 'exact_maplibre_pin', severity: 'critical', file: 'package.json', excerpt: String(pin) });
}

const lock = JSON.parse(fs.readFileSync(path.join(ROOT, 'package-lock.json'), 'utf8'));
const lockVersion = lock.packages?.['node_modules/maplibre-gl']?.version;
if (lockVersion !== '5.24.0') {
  findings.push({ check: 'lockfile_maplibre_pin', severity: 'critical', file: 'package-lock.json', excerpt: String(lockVersion) });
}

const report = {
  generated_at_utc: new Date().toISOString(),
  files_scanned: files.length,
  exact_maplibre_version: pin,
  lockfile_maplibre_version: lockVersion,
  blocking_findings: findings,
  status: findings.length ? 'fail' : 'pass',
  controls: {
    no_provider_keys: findings.every((item) => item.check !== 'credential_assignment'),
    no_external_style_urls: findings.every((item) => item.check !== 'external_http_url' && item.check !== 'mapbox_protocol'),
    no_fr24_visual_assets: findings.every((item) => item.check !== 'fr24_visual_asset_reference'),
    no_location_persistence: findings.every((item) => item.check !== 'console_location_persistence'),
  },
};
fs.mkdirSync(REPORT_DIR, { recursive: true });
fs.writeFileSync(path.join(REPORT_DIR, 'SECURITY_SCAN.json'), `${JSON.stringify(report, null, 2)}\n`);
fs.writeFileSync(path.join(REPORT_DIR, 'SECURITY_SCAN.md'), `# Phase 3 Security Scan\n\n- Status: **${report.status.toUpperCase()}**\n- Files scanned: ${report.files_scanned}\n- Exact MapLibre pin: \`${pin}\`\n- Lockfile version: \`${lockVersion}\`\n- Blocking findings: **${findings.length}**\n\n## Controls\n\n\`\`\`json\n${JSON.stringify(report.controls, null, 2)}\n\`\`\`\n`);
console.log(JSON.stringify(report, null, 2));
if (findings.length) process.exit(1);
