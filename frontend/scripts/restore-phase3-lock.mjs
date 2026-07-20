import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import zlib from 'node:zlib';

const root = path.resolve(process.cwd());
const archive = path.join(root, 'package-lock.phase3.json.gz');
const destination = path.join(root, 'package-lock.json');
const expectedSha256 = '620bce7f79d7d6499d104ef0d9951a7df50a6184c03e65049f9562398bd0a346';

if (!fs.existsSync(archive)) throw new Error(`Phase 3 lock archive missing: ${archive}`);
const content = zlib.gunzipSync(fs.readFileSync(archive));
const actual = crypto.createHash('sha256').update(content).digest('hex');
if (actual !== expectedSha256) {
  throw new Error(`Phase 3 lock SHA-256 mismatch: expected ${expectedSha256}, got ${actual}`);
}
JSON.parse(content.toString('utf8'));
fs.writeFileSync(destination, content);
console.log(`restored package-lock.json (${content.length} bytes, sha256=${actual})`);
