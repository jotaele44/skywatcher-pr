#!/usr/bin/env bash
set -euo pipefail
satim --input "${1:?input zip dir}" --output "${2:?output dir}"
