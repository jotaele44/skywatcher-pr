#!/usr/bin/env bash
# RLSM screenshot pipeline — the single command.
#
#   ./run-rlsm.sh                 # everything: OCR -> pins -> icons -> exports
#   ./run-rlsm.sh --status        # what is done, what is pending
#   ./run-rlsm.sh --dry-run       # show the stage plan, change nothing
#   ./run-rlsm.sh --limit 200     # smoke test over 200 images first
#   ./run-rlsm.sh --from icons    # resume from a stage
#   ./run-rlsm.sh --help          # all options
#
# Resumable and idempotent throughout: Ctrl-C and re-run is always safe.
# Point data/FR24_baseline at your corpus first (symlink is fine) — preflight
# tells you exactly what to do if it is missing.
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "run-rlsm.sh: '$PY' not found. Set PYTHON=/path/to/python3 and retry." >&2
    exit 1
fi

# One thread per tesseract process; the pool provides the parallelism.
export OMP_THREAD_LIMIT="${OMP_THREAD_LIMIT:-1}"

exec "$PY" -m fr24.rlsm_pipeline "$@"
