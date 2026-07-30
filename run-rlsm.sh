#!/usr/bin/env bash
# Skywatcher screenshot-intelligence pipeline — the single command.
#
#   ./run-rlsm.sh                         # extract, audit, and report
#   ./run-rlsm.sh --certify               # fail unless every certification gate passes
#   ./run-rlsm.sh --gold-sample PATH      # annotated 300-frame JSONL/JSON
#   ./run-rlsm.sh --status                # extraction and certification status
#   ./run-rlsm.sh --dry-run               # show the stage plan; change nothing
#   ./run-rlsm.sh --limit 200             # bounded smoke run
#   ./run-rlsm.sh --from tracks           # resume at track extraction
#   ./run-rlsm.sh --refresh-derived       # rebuild derived rows; raw OCR is preserved
#   ./run-rlsm.sh --help                  # all options
#
# The certified OCR and track runners preserve per-frame failures. Certification
# never treats missing gold annotations, unsupported geolocation, incomplete
# receipts, or unprocessed corpus rows as a pass.
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "run-rlsm.sh: '$PY' not found. Set PYTHON=/path/to/python3 and retry." >&2
    exit 1
fi

# One thread per tesseract process; the process pool provides parallelism.
export OMP_THREAD_LIMIT="${OMP_THREAD_LIMIT:-1}"

exec "$PY" -m fr24.rlsm_intelligence_pipeline_v2 "$@"
