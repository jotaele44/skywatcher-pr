#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v xcodegen >/dev/null || { echo "xcodegen is required" >&2; exit 1; }
xcodegen generate --spec project.yml
