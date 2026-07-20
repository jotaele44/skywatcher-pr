import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const root = path.resolve(process.cwd());
const reportDir = path.resolve(root, '../reports/console/phase3');
fs.mkdirSync(reportDir, { recursive: true });

const tsc = path.resolve(root, 'node_modules/typescript/bin/tsc');
const result = spawnSync(process.execPath, [tsc, '-p', './jsconfig.json'], {
  cwd: root,
  encoding: 'utf8',
  env: process.env,
});
const output = `${result.stdout || ''}${result.stderr || ''}`;
fs.writeFileSync(path.join(reportDir, 'TYPECHECK_REPORT.txt'), output || 'TypeScript check passed with no diagnostics.\n');
if (output) process.stdout.write(output);
process.exit(result.status ?? 1);
