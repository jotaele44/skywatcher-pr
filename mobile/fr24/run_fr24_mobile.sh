#!/bin/sh
set -eu

# Fixed paths are intentional: Shortcuts' a-Shell Put File actions write these
# names, so no untrusted filename or user text is interpolated into the command.
ROOT="${HOME}/shortcuts/skywatcher-fr24"
INPUT="${ROOT}/input/source_image"
MANIFEST="${ROOT}/input/input_manifest.json"
OUTPUT="${ROOT}/output/result.json"
SCRIPT="${ROOT}/app/analyze_fr24_mobile.py"

mkdir -p "${ROOT}/input" "${ROOT}/output"
rm -f "${OUTPUT}"

if [ ! -f "${SCRIPT}" ]; then
  printf '%s\n' 'Skywatcher mobile analyzer is not installed at the fixed app path.' >&2
  exit 66
fi
if [ ! -f "${INPUT}" ] || [ ! -f "${MANIFEST}" ]; then
  printf '%s\n' 'Shortcut did not stage source_image and input_manifest.json.' >&2
  exit 66
fi

python3 "${SCRIPT}" \
  --input "${INPUT}" \
  --manifest "${MANIFEST}" \
  --output "${OUTPUT}"
