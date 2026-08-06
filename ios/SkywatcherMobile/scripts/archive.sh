#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/generate.sh
: "${DEVELOPMENT_TEAM:?Set DEVELOPMENT_TEAM to your Apple team ID}"
rm -rf build/SkywatcherMobile.xcarchive
xcodebuild -project SkywatcherMobile.xcodeproj -scheme SkywatcherMobile -configuration Release -destination 'generic/platform=iOS' -archivePath build/SkywatcherMobile.xcarchive DEVELOPMENT_TEAM="$DEVELOPMENT_TEAM" clean archive
