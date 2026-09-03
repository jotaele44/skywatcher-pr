# Skywatcher Mobile — source-agnostic screenshot analyzer

Native, offline iOS intake for manually captured screenshots. This target contains no provider-specific names, layouts, parsers, templates, network access, Scriptable, Userscripts, or a-Shell runtime dependency.

## Implemented

- SwiftUI Photos and Files intake
- Share Extension through an App Group
- `Analyze Skywatcher Screenshot` App Intent for Shortcuts
- exact-byte preservation and SHA-256 binding
- 40 MiB and 20,000-pixel fail-closed resource bounds
- ImageIO decoding and orientation-safe `CGImage` handling
- Vision OCR with normalized bounding boxes
- annotated PNG and sorted-key JSON manifest export
- explicit confidence, contradictions, unresolved fields, analyzer version, and `networkAccess=false`
- cancellation checks and atomic writes

## Generate and test

Requirements: macOS, Xcode 16 or later, and XcodeGen.

```bash
cd ios/SkywatcherMobile
brew install xcodegen
./scripts/generate.sh
xcodebuild -project SkywatcherMobile.xcodeproj \
  -scheme SkywatcherMobile \
  -sdk iphonesimulator \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  CODE_SIGNING_ALLOWED=NO test
```

Before device signing, replace the bundle-ID prefix and App Group if they conflict with your Apple Developer account. Select the same signing team for `SkywatcherMobile` and `SkywatcherShare`, then enable the shared App Group on both identifiers.

## Development or Ad Hoc IPA

```bash
cd ios/SkywatcherMobile
./scripts/generate.sh
DEVELOPMENT_TEAM=YOURTEAMID ./scripts/archive.sh
```

The archive script creates `build/SkywatcherMobile.xcarchive`. In Xcode Organizer, choose **Distribute App → Development** or **Ad Hoc**, select the correct provisioning profiles, and export the IPA. For command-line export, copy `Config/ExportOptions.example.plist`, set the team ID and provisioning profile names, then run:

```bash
xcodebuild -exportArchive \
  -archivePath build/SkywatcherMobile.xcarchive \
  -exportPath build/export \
  -exportOptionsPlist Config/ExportOptions.plist
```

## Shortcuts

After installing a signed build, add the **Analyze Skywatcher Screenshot** action to a Shortcut. Supply a screenshot from **Select Photos**, **Get Latest Photos**, or the Share Sheet. The action returns the JSON manifest as a file.

## Evidence boundary

OCR text and generic bounding boxes are observations. Icon meaning, marker identity, source application, and geolocation remain unresolved unless separately corroborated. The mobile target does not promote observations into the desktop operational database.
