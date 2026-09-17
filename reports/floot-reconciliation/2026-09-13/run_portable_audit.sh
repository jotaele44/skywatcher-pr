#!/usr/bin/env bash
# AUDIT_ONLY: Linux execution is never iOS acceptance.
set -euo pipefail
[[ "$(uname -s)" == Linux ]] || { echo 'Linux audit harness only' >&2; exit 2; }
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
SOURCE="$ROOT/ios/SkywatcherMobile/Sources/Core/MobilePersistenceStore.swift"
TESTS="$ROOT/ios/SkywatcherMobile/Tests/LocalPersistenceSafetyTests.swift"
OUTPUT="${1:?Supply a new output log path}"
[[ ! -e "$OUTPUT" ]] || { echo 'Refusing to overwrite evidence' >&2; exit 2; }
for cmd in swiftc python3; do command -v "$cmd" >/dev/null; done
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/modules/SQLite3" "$WORK/modules/COpenSSL" "$WORK/bin" "$WORK/runner"
printf 'module SQLite3 [system] { header "/usr/include/sqlite3.h" link "sqlite3" export * }\n' > "$WORK/modules/SQLite3/module.modulemap"
printf 'module COpenSSL [system] { header "/usr/include/openssl/sha.h" link "crypto" export * }\n' > "$WORK/modules/COpenSSL/module.modulemap"
python3 - "$SOURCE" "$TESTS" "$WORK/runner/main.swift" <<'PY'
import hashlib,pathlib,re,sys
expected=['5965e9a4d77dc6491c4f11a8c2e3aedd52b7e0a326b58133008145bfbf3aa706','381c6ad286edbb97c23fdf9689233c8abf1094a1f21175e7f880f4ceba1d4c77']
for path,digest in zip(sys.argv[1:3],expected):
    if hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()!=digest:
        raise SystemExit('Frozen input mismatch: '+path)
names=re.findall(r'    func (test\w+)\(',pathlib.Path(sys.argv[2]).read_text())
if len(names)!=20 or len(set(names))!=20:
    raise SystemExit('Test denominator mismatch')
body='import XCTest\nextension LocalPersistenceSafetyTests { static var allTests = [\n'
body+=''.join('("'+n+'", '+n+'),\n' for n in names)
body+='] }\nXCTMain([testCase(LocalPersistenceSafetyTests.allTests)])\n'
pathlib.Path(sys.argv[3]).write_text(body)
PY
swiftc -warnings-as-errors -I "$WORK/modules" -emit-library -emit-module -module-name CryptoKit "$HERE/CryptoKitAuditShim.swift" -o "$WORK/bin/libCryptoKit.so" -emit-module-path "$WORK/bin/CryptoKit.swiftmodule"
swiftc -warnings-as-errors -I "$WORK/modules" -I "$WORK/bin" -L "$WORK/bin" -lCryptoKit -enable-testing -emit-library -emit-module -module-name SkywatcherMobile "$SOURCE" -o "$WORK/bin/libSkywatcherMobile.so" -emit-module-path "$WORK/bin/SkywatcherMobile.swiftmodule"
swiftc -warnings-as-errors -I "$WORK/modules" -I "$WORK/bin" -L "$WORK/bin" -lCryptoKit -lSkywatcherMobile "$TESTS" "$WORK/runner/main.swift" -o "$WORK/bin/safety_tests"
(set -o noclobber; LD_LIBRARY_PATH="$WORK/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$WORK/bin/safety_tests" > "$OUTPUT" 2>&1)
python3 - "$OUTPUT" <<'PY'
import pathlib,re,sys
text=pathlib.Path(sys.argv[1]).read_text()
names=re.findall(r"Test Case 'LocalPersistenceSafetyTests\.(test\w+)' passed",text)
if len(names)!=20 or len(set(names))!=20 or 'Executed 20 tests, with 0 failures' not in text:
    raise SystemExit('Execution evidence does not close at 20/20')
print('AUDIT_ONLY: 20/20 portable XCTest checks passed; iOS acceptance remains OPEN.')
PY
