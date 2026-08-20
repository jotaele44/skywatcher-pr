#!/usr/bin/env bash
set -euo pipefail

TARGET_SHA="1d578df2a0b75e28059376bfd35b530b6aaf278b"
BRANCH="feature/skywatcher-airspace-evidence-skill"
PATCH_PATH="${1:-/mnt/data/skywatcher-airspace-evidence-skill-final.patch}"
REPORT_DIR="${2:-reports/skywatcher_skill_closeout}"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
command -v git >/dev/null || fail "git is required"
command -v python >/dev/null || fail "python is required"
[ -d .git ] || fail "run from the skywatcher-pr repository root"
[ -f "$PATCH_PATH" ] || fail "patch not found: $PATCH_PATH"

actual_sha="$(git rev-parse HEAD)"
[ "$actual_sha" = "$TARGET_SHA" ] || fail "HEAD=$actual_sha; expected $TARGET_SHA"

if [ "$(git branch --show-current)" != "$BRANCH" ]; then
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git switch "$BRANCH"
  else
    git switch -c "$BRANCH"
  fi
fi

[ -z "$(git status --porcelain)" ] || fail "working tree must be clean before patch application"
git apply --check --whitespace=error-all "$PATCH_PATH"
git apply --whitespace=error-all "$PATCH_PATH"

mkdir -p "$REPORT_DIR"

python scripts/build_skywatcher_skill_inventory.py \
  --strict \
  --repository-commit "$TARGET_SHA" \
  > "$REPORT_DIR/inventory.log" 2>&1

python -m pytest -q > "$REPORT_DIR/pytest-full.log" 2>&1
python -m pytest -q tests/test_module_boundaries.py > "$REPORT_DIR/pytest-module-boundaries.log" 2>&1
python -m fr24.satim_engine --help > "$REPORT_DIR/satim-repo-native-help.txt" 2>&1

if command -v satim >/dev/null 2>&1; then
  satim --help > "$REPORT_DIR/satim-standalone-help.txt" 2>&1
else
  python -m pip install -e 'tools/satim_engine[dev]' > "$REPORT_DIR/satim-install.log" 2>&1
  satim --help > "$REPORT_DIR/satim-standalone-help.txt" 2>&1
fi

if command -v ruff >/dev/null 2>&1; then
  ruff check skills/skywatcher-airspace-evidence scripts/build_skywatcher_skill_inventory.py tests/test_skywatcher_skill_packet.py \
    > "$REPORT_DIR/ruff.log" 2>&1
else
  printf 'ruff unavailable\n' > "$REPORT_DIR/ruff.log"
fi

for version in 3.10 3.11 3.12; do
  py="python${version}"
  if command -v "$py" >/dev/null 2>&1; then
    "$py" -m pytest -q > "$REPORT_DIR/pytest-python-${version}.log" 2>&1
  else
    printf '%s unavailable\n' "$py" > "$REPORT_DIR/pytest-python-${version}.log"
  fi
done

git diff --check > "$REPORT_DIR/git-diff-check.log" 2>&1
git diff --stat > "$REPORT_DIR/final-diff-stat.txt"
git status --short > "$REPORT_DIR/git-status.txt"

printf 'Closeout complete. No commit, push, or PR performed.\n'
printf 'Reports: %s\n' "$REPORT_DIR"
