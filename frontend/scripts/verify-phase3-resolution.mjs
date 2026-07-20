import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const root = path.resolve(process.cwd());
const reportDir = path.resolve(root, '../reports/console/phase3');
const lockPath = path.join(root, 'package-lock.json');
const referenceLocalLockSha256 = '620bce7f79d7d6499d104ef0d9951a7df50a6184c03e65049f9562398bd0a346';
const expectedGeneratedLockSha256 = null;
const expectedManifestSha256 = null;
const discoveryMode = expectedGeneratedLockSha256 === null || expectedManifestSha256 === null;
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
  lockfile_sha256: referenceLocalLockSha256,
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
const manifestMatches = discoveryMode || manifestSha256 === expectedManifestSha256;
const generatedLockMatches = discoveryMode || lockSha256 === expectedGeneratedLockSha256;
const result = {
  npm_version: process.env.npm_config_user_agent || null,
  mode: discoveryMode ? 'discovery' : 'enforcement',
  package_count: packages.length,
  manifest_sha256: manifestSha256,
  expected_manifest_sha256: expectedManifestSha256,
  generated_lockfile_sha256: lockSha256,
  expected_generated_lockfile_sha256: expectedGeneratedLockSha256,
  reference_local_lockfile_sha256: referenceLocalLockSha256,
  manifest_matches: manifestMatches,
  generated_lock_matches: generatedLockMatches,
  status: discoveryMode ? 'discovery' : (manifestMatches && generatedLockMatches ? 'pass' : 'fail'),
};
fs.mkdirSync(reportDir, { recursive: true });
fs.writeFileSync(path.join(reportDir, 'DEPENDENCY_RESOLUTION_MANIFEST.json'), `${JSON.stringify(manifest, null, 2)}\n`);
fs.writeFileSync(path.join(reportDir, 'DEPENDENCY_RESOLUTION_GATE.json'), `${JSON.stringify(result, null, 2)}\n`);
console.log(JSON.stringify(result, null, 2));
if (!discoveryMode && (!manifestMatches || !generatedLockMatches)) process.exit(1);
