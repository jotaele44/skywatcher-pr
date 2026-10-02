# FR24 POI / icon reference registry

## Status

**REFERENCE_SEED / fail-closed contract.** This registry adds a controlled list of
FR24 screenshot icon classes and maps POI-related source classes onto Skywatcher's
canonical feature types. It does **not** establish the identity of a physical POI,
operator, aircraft purpose, or mission.

The source seed is the user-supplied `Icon Library.zip`. The public repository stores
the member-level provenance and semantic taxonomy, but not the source or derived icon
pixels because redistribution rights are currently `UNVERIFIED`.

## Canonical separation

Skywatcher keeps four different concepts separate:

1. **Raw manifestation** — exact archive member path, byte count, and SHA-256.
2. **Source icon type** — what the screenshot/icon library calls the glyph
   (`FR24_PIZZA`, `FR24_BANK`, etc.).
3. **Canonical feature type** — the broader Skywatcher semantic class
   (`FOOD_DINING`, `FINANCIAL_SERVICE`, etc.).
4. **Physical identity** — a specific real-world site/entity. This requires independent
   binding evidence and is outside this registry.

Therefore:

`icon match → source class candidate → canonical feature context`

is valid, while:

`icon match → named real-world site`

is not.

## Frozen source snapshot

`configs/fr24_poi_icon_registry.json` binds:

- outer archive SHA-256;
- every non-directory member path + uncompressed size + SHA-256, including macOS
  resource-fork metadata;
- full member-manifest SHA-256;
- semantic-member-manifest SHA-256;
- payload-multiset SHA-256;
- 34 semantic source members: 31 POI-icon source crops and 3 operator/logo crops;
- 33 POI source icon types because two source crops each contain two visible icons.

The two explicit composite source crops are preserved rather than inventing synthetic
combined POI classes:

- `parking & baños` → `FR24_PARKING` + `FR24_RESTROOMS`;
- `pizza & barbería` → `FR24_PIZZA` + `FR24_BARBER_SHOP`.

`mecánico,gomera` remains one broad `AUTO_SERVICE` source class because the source crop
is a single icon with a composite semantic label, not two independently visible glyphs.

## Feature-kind boundary

Road and avenue shields are retained for screenshot interpretation but are classified as
`TRANSPORT_FEATURE`, not POIs. Unknown markers stay `UNKNOWN`. A National Guard-labeled
source crop maps only to the generic canonical `MILITARY_FACILITY` class: the icon alone
does not prove National Guard identity.

## Local pixel installation

The pixel library remains operator-local:

```bash
python scripts/import_fr24_icon_reference_library.py "/path/to/Icon Library.zip"
python scripts/import_fr24_icon_reference_library.py "/path/to/Icon Library.zip" --install
```

The verifier classifies archive relationships as:

- `BYTE_IDENTICAL`
- `PURE_RECOMPRESSION`
- `SAME_PAYLOADS_DIFFERENT_PATHS`
- `DISTINCT_PAYLOADS`
- `UNRESOLVED`

Only `BYTE_IDENTICAL` and `PURE_RECOMPRESSION` are installable automatically. A path
change is not silently treated as the same source manifestation even when payload bytes
match.

Installed pixels are written below
`data/local_reference/fr24_icon_library/<archive-hash-prefix>/`, which is gitignored.
The install receipt preserves the actual archive hash and each installed member hash.

## RLSM integration

The existing icon channel remains authoritative for screenshot extraction:

1. `fr24.rlsm_icons` detects/fingerprints visible glyphs.
2. `fr24.rlsm_icons_certified` clusters recurring glyphs.
3. The generated review file exposes the closed registry vocabulary.
4. An operator/reviewer assigns a source icon class; no automatic identity promotion is
   performed.
5. POI identity, operator attribution, and any flight/POI correlation remain downstream
   evidence-gated processes.

The legacy cluster script accepts declared source IDs and declared aliases, but must not
invent new canonical classes from arbitrary free text.

## Certification boundary

A passing registry gate certifies only that the taxonomy/provenance contract is
structurally self-consistent. It does not certify:

- FR24's own private taxonomy;
- icon artwork licensing;
- a source icon's visual-match accuracy against every screenshot epoch;
- physical-site identity;
- operator identity;
- aircraft mission/purpose;
- correlation significance.

Those remain separate vectors with their own evidence requirements.
