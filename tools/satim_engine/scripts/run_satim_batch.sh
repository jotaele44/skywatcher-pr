#!/usr/bin/env bash
set -euo pipefail
python -m fr24.satim_engine run --input "$1" --output "$2"
