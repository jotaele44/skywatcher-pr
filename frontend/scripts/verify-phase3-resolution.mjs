import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const root = path.resolve(process.cwd());
const lockPath = path.join(root, 'package-lock.json');
const expectedManifestSha256 = '1266401f8603af4b5fe3b6839808fbf55b5357aa4cd12f182f40fa359138f439';
const expectedLockSha256 = '620bce7f79d7d6499d104ef0d9951a7df50a6184c03e65049f9562398bd0a346';
const lockBytes = fs.readFileSync(lockPath);
const lock = JSON.parse(lockBytes.toString('utf8'));
const packages = Object.entries(lock.packages || {})
  .filter(([packagePath]) => Boolean(packagePath))
  .sort(([left], [right]) => left.localeCompare(right))
  .map(([packagePath, metadata]) => ({
    path: packagePath,
    version: metadata.version ?? null,
    integrity: metadata.integrity ?? null,
    resolved: metadata.resolved ?? null,
    dev: Boolean(metadata.dev),
    optional: Boolean(metadata.optional),
  }));
const manifest = {
  schema_version: 'skywatcher_phase3_dependency_resolution_v1',
  lockfile_sha256: expectedLockSha256,
  package_count: packages.length,
  packages,
};
function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stable(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}
const stableBytes = Buffer.from(`${stable(manifest)}\n`);
const manifestSha256 = crypto.createHash('sha256').update(stableBytes).digest('hex');
const lockSha256 = crypto.createHash('sha256').update(lockBytes).digest('hex');
const result = {
  package_count: packages.length,
  manifest_sha256: manifestSha256,
  expected_manifest_sha256: expectedManifestSha256,
  lockfile_sha256: lockSha256,
  certified_lockfile_sha256: expectedLockSha256,
  status: manifestSha256 === expectedManifestSha256 ? 'pass' : 'fail',
};
fs.mkdirSync(path.resolve(root, '../reports/console/phase3'), { recursive: true });
fs.writeFileSync(path.resolve(root, '../reports/console/phase3/DEPENDENCY_RESOLUTION_GATE.json'), `${JSON.stringify(result, null, 2)}\n`);
console.log(JSON.stringify(result, null, 2));
if (manifestSha256 !== expectedManifestSha256) process.exit(1);
