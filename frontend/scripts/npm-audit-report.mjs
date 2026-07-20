import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const root = path.resolve(process.cwd());
const reportDir = path.resolve(root, '../reports/console/phase3');
fs.mkdirSync(reportDir, { recursive: true });

const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const result = spawnSync(
  npmCommand,
  ['audit', '--omit=dev', '--audit-level=high', '--json'],
  { cwd: root, encoding: 'utf8', env: process.env },
);

let payload;
try {
  payload = JSON.parse(result.stdout || '{}');
} catch (error) {
  payload = {
    error: {
      code: 'AUDIT_OUTPUT_PARSE_FAILED',
      summary: error instanceof Error ? error.message : String(error),
    },
    raw_stdout: result.stdout || '',
  };
}

const metadata = payload.metadata || {};
const counts = metadata.vulnerabilities || {};
const high = Number(counts.high || 0);
const critical = Number(counts.critical || 0);
const vulnerabilities = Object.entries(payload.vulnerabilities || {}).map(([name, advisory]) => ({
  name,
  severity: advisory.severity || 'unknown',
  direct: Boolean(advisory.isDirect),
  via: advisory.via || [],
  effects: advisory.effects || [],
  range: advisory.range || null,
  nodes: advisory.nodes || [],
  fix_available: advisory.fixAvailable ?? false,
}));
const blocking = vulnerabilities.filter((item) => ['high', 'critical'].includes(item.severity));
const auditError = payload.error || (result.error ? {
  code: result.error.code || 'AUDIT_EXECUTION_FAILED',
  summary: result.error.message,
} : null);
const status = !auditError && high === 0 && critical === 0 ? 'pass' : 'fail';
const report = {
  generated_at_utc: new Date().toISOString(),
  command: 'npm audit --omit=dev --audit-level=high --json',
  npm_exit_code: result.status,
  status,
  audit_error: auditError,
  metadata,
  vulnerability_counts: counts,
  blocking_count: blocking.length,
  vulnerabilities,
};

fs.writeFileSync(path.join(reportDir, 'NPM_AUDIT_REPORT.json'), `${JSON.stringify(report, null, 2)}\n`);
fs.writeFileSync(
  path.join(reportDir, 'NPM_AUDIT_REPORT.md'),
  `# Phase 3 Production Dependency Audit\n\n- Status: **${status.toUpperCase()}**\n- High: **${high}**\n- Critical: **${critical}**\n- Blocking package entries: **${blocking.length}**\n- npm exit code: **${result.status ?? 'null'}**\n\n## Blocking packages\n\n${blocking.length ? blocking.map((item) => `- \`${item.name}\` — ${item.severity}; direct=${item.direct}; fix=${JSON.stringify(item.fix_available)}`).join('\n') : 'None.'}\n`,
);

console.log(JSON.stringify(report, null, 2));
if (status !== 'pass') process.exit(result.status || 1);
