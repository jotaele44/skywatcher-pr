# Open MCT v4.1.0 dependency receipt operator

This procedure generates the external evidence package required before Open MCT can be admitted into Skywatcher PR #168.

## Boundary

- The operator does not modify the certified worktree.
- The operator does not change `admission_status` to `admitted`.
- The operator does not add the `/replay` route.
- A nonzero exit code or any item in `blockers` keeps the dependency unadmitted.
- The ZIP must be uploaded and independently rehashed before ingestion.

## Prerequisites

- macOS or Linux with network access.
- Git.
- Python 3.12 or newer.
- Node 20 LTS. Open MCT v4.1.0 declares Node `>=18.14.2 <23`; Node 20 is the preferred operator runtime.
- npm supplied with Node 20.
- Enough free space for `npm ci`, the production build, SBOM, and packaged `dist/` assets.

## Exact execution

From a terminal:

```bash
set -euo pipefail

ROOT="$HOME/Developer"
SOURCE="$ROOT/skywatcher-pr"
OPERATOR="$ROOT/skywatcher-pr-openmct-operator"
CERTIFIED="$ROOT/skywatcher-pr168-certified-head"
BRANCH="codex/openmct-bounded-reuse-foundation-v0-3"
CERTIFIED_HEAD="7400a4ec0551617bdbfa966ca1907954ccb14b4b"

cd "$SOURCE"
git fetch origin --prune

# Operator worktree contains the script and may advance with operator-only commits.
if [ ! -d "$OPERATOR/.git" ] && [ ! -f "$OPERATOR/.git" ]; then
  git worktree add "$OPERATOR" "origin/$BRANCH"
fi

# Certified input worktree remains pinned to the fully green foundation head.
if [ ! -d "$CERTIFIED/.git" ] && [ ! -f "$CERTIFIED/.git" ]; then
  git worktree add --detach "$CERTIFIED" "$CERTIFIED_HEAD"
fi

cd "$CERTIFIED"
test "$(git rev-parse HEAD)" = "$CERTIFIED_HEAD"
test -z "$(git status --porcelain=v1 --untracked-files=all)"

cd "$OPERATOR"
python3.12 scripts/build_openmct_v4_1_0_receipt.py \
  --repo "$CERTIFIED" \
  --output-dir "$OPERATOR/outputs"
```

The operator may exit with status `2` when the package was generated but admission blockers remain. Do not delete the package in that case; upload it for adjudication with the blocker list intact.

## Expected output

```text
outputs/openmct_v4_1_0_dependency_receipt/
outputs/openmct_v4_1_0_dependency_receipt.zip
```

The ZIP contains:

- `release.json`
- `ARCHIVE_SHA256.txt`
- `source-manifest.json`
- `dist-manifest.json`
- `source_evidence/`
- `sbom.cdx.json`
- `audit.json`
- `license-report.json`
- `external-reference-scan.json`
- `build-receipt.json`
- `minimum_dist/`
- `PACKAGE_MANIFEST.json`
- `PACKAGE_SHA256.txt`
- the downloaded upstream tag archive

## Local verification

```bash
cd "$OPERATOR"
ZIP="outputs/openmct_v4_1_0_dependency_receipt.zip"

shasum -a 256 "$ZIP"
unzip -t "$ZIP"
python3.12 - <<'PY'
import json
from pathlib import Path

root = Path("outputs/openmct_v4_1_0_dependency_receipt")
build = json.loads((root / "build-receipt.json").read_text())
release = json.loads((root / "release.json").read_text())

print("admission_status:", build["admission_status"])
print("blockers:", json.dumps(build["blockers"], indent=2))
print("warnings:", json.dumps(build["warnings"], indent=2))
print("tag_type:", release["tag_type"])
print("exact_commit_sha:", release["exact_commit_sha"])
print("archive_sha256:", release["archive_sha256"])
PY
```

## Admission conditions

The package is only a candidate for ingestion when:

1. `build-receipt.json.admission_status` is `candidate_for_human_adjudication`.
2. `blockers` is empty.
3. The exact tag and peeled commit resolve successfully.
4. The official archive has a recorded SHA-256 and size.
5. `npm ci` and `npm run build:prod` both exit zero.
6. `dist-manifest.json` is nonempty.
7. `sbom.cdx.json` exists and parses.
8. `audit.json` contains no unresolved high or critical findings.
9. `license-report.json` parses and all licenses are adjudicated.
10. Every URL-like string in `external-reference-scan.json` is reviewed; runtime egress is not inferred from an empty or nonempty string scan alone.
11. `PACKAGE_MANIFEST.json`, `PACKAGE_SHA256.txt`, and the uploaded ZIP hash reconcile.

Even when all conditions pass, an ingestion review must independently verify every hash before changing `vendor/openmct/v4.1.0/RELEASE.json` from `not_admitted` to `admitted`.
