# FR24 production promotion — operator runbook

Production promotion (`ready_for_hub_live_execution` → true) is **data-gated**:
it needs a real FlightRadar24 capture that only a subscriber can export. The
code path is now fully automated end-to-end; supplying the capture is the only
manual step.

## 1. Supply the capture

Per-flight FR24 playback CSV exports (subscriber feature):

- Filename: `{TAIL}_{date}_{flight_id}.csv`
- Header (exact): `Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction`
- Drop location: the directory `FR24_DOWNLOADS` points at
  (fallbacks: `/sessions/*/mnt/Downloads`, `~/Downloads`)

Then run the quota-aware commit loop (25 fetches/day):

```bash
python scripts/fr24_harvest.py status
python scripts/fr24_harvest.py next        # prints the playback URL to fetch in a browser
python scripts/fr24_harvest.py commit TAIL DATE FLIGHT_ID
```

Screenshot corpora (HEIC) go through `scripts/fr24_vision_ingest.py` instead
(needs `ANTHROPIC_API_KEY`).

## 2. Build the operational DB

```bash
python -m fr24.event_export   # ScreenshotInventory -> screenshots + track_points tables
```

(See `docs/RUNBOOK_FR24_DATA_LOAD.md` for the full corpus-load procedure.)

## 3. Build the producer package (new — automated)

```bash
python scripts/build_producer_package.py --db <fr24 sqlite db> --out exports/fr24_package
```

Emits `observations.geojson`, `observations.csv`, `sources.json`,
`lineage.json`, `confidence.json`, `manifest.json`. Real rows carry
`synthetic=false` / `provenance_status=operator_capture`. Rows without usable
coordinates/timestamp are skipped (manual review queue); `rejected` rows are
excluded.

## 4. Validate + export canonical (production)

```bash
python scripts/validate_airspace_export.py exports/fr24_package --mode production
python scripts/federation_export.py --package exports/fr24_package --mode production
```

Both must pass with zero synthetic rows. Then flip
`federation.json.federation_readiness_gate.ready_for_hub_live_execution` to
`true`, clear the resolved blocking conditions, and coordinate the matching
`thehub-pr` registry/status update (the Hub's status-consistency test requires
both sides to move together).

## Optional terrain layer (not gate-relevant)

```bash
python scripts/fetch_gebco_pr.py          # OpenTopography_API_KEY required
export GEBCO_PATH=data/gebco/gebco_pr_subset.nc
```

Fetches the real PR-extent GEBCO bathymetry subset and converts it to the
NetCDF layout `gebco/io.py` requires (`elevation` on ascending lat/lon).
