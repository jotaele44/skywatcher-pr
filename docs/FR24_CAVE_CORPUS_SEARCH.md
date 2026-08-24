# FR24 cave corpus search

`fr24.rlsm_cave_search` is a read-only retrieval layer over the existing RLSM SQLite corpus. It does **not** re-run OCR and it does **not** treat keyword/fuzzy hits as canonical cave identity.

## Baseline versions

- `data/reference/caves/pr_cave_v1_regression_manifest.json` freezes the five-dataset v1 conservative baseline by SHA-256. Never rewrite that snapshot in place.
- `data/reference/caves/pr_cave_ocr_baseline_v2.json` is the versioned cave search dictionary. It contains all 17 direct cave/system names extracted from `Cuevas & Cavernas.csv`, including OPEN/PROVISIONAL records, plus bounded public-source identity/coordinate adjudication.

The v1 source snapshot classified 37,629/37,629 rows across the five supplied CSV datasets. Its conservative spatial baseline had two official cave-system protected-area records. v2 adds stronger public evidence for selected direct cave names but preserves unresolved names instead of force-merging them.

## Search semantics

Default search reads:

1. the newest OCR observation per `(screenshot_id, zone)` using `MAX(obs_id)`, so append-only re-OCR history cannot inflate appearance counts; and
2. `labeled_pins` as a separate `EXTRACTED_LABEL` evidence channel.

RAW, normalized, and canonical strings remain separate. Two records with similar names (for example `Cueva Las Golondrinas` and `Cueva Golondrinas`) stay separate unless independent evidence establishes identity.

Generic terms such as `cueva`, `caverna`, `gruta`, `cave`, and `cavern` produce lexical matches with no `cave_id`. `sumidero`/`sima` terms are opt-in candidate vocabulary. Fuzzy matching is also opt-in and always emits `FUZZY_CANDIDATE` with `CANDIDATE_NOT_IDENTITY`.

## CLI

```bash
python -m fr24.rlsm_cave_search --theme caves
python -m fr24.rlsm_cave_search --theme caves --output json
python -m fr24.rlsm_cave_search --theme caves --output csv --out outputs/cave_matches.csv
python -m fr24.rlsm_cave_search --query "Cueva Ventana"
python -m fr24.rlsm_cave_search --theme caves --include-karst-candidates --fuzzy
```

The default zones are `label_layer,map_center,aircraft_card` because those are the existing RLSM label-bearing/recovery surfaces.

## Certification boundary

A successful search can certify only:

`BOUNDED_RETRIEVAL_EXHAUSTION_OVER_EFFECTIVE_OCR_AND_LABELED_PINS`

It cannot certify visual-text exhaustion. OCR failures, unreadable source screenshots, and OCR false negatives remain possible residuals and are reported in corpus coverage counts.

## Coordinate roles

Coordinates are never silently upgraded:

- `MAPPED_CAVE_ENTRANCE`: open-map cave-entrance geometry; useful for search/correlation but not survey-certified.
- `PUBLISHED_CAVE_SAMPLE_COORDINATE`: coordinate published for a cave sampling location; not necessarily a surveyed entrance.
- `PROTECTED_AREA_REPRESENTATIVE_POINT`: v1 protected-area geometry; search-region anchor only, never an entrance.

Name-only and proximity-only evidence are prohibited as identity proof.
