# Runtime Media Input Contract

Skywatcher/SATIM media intake is runtime-only. The repository must not commit source screenshots, photos, PDFs, or phone exports used for a specific investigation.

## Supported runtime media

The engine accepts analyst-provided local files with these extensions:

- `.pdf`
- `.jpg`
- `.jpeg`
- `.png`
- `.heic`
- `.heif`
- `.webp`
- `.tif`
- `.tiff`

## Repository boundary

Allowed in repository:

- schemas;
- generic docs;
- scripts;
- generic fixtures without investigative content;
- validation ledgers describing engine behavior.

Not allowed in repository:

- source screenshots;
- investigation-specific image/PDF filenames;
- raw phone exports;
- hard-coded aircraft/event examples from uploaded media;
- source-media hashes unless the operator explicitly creates a private evidence manifest outside the public repo.

## Manifest-driven run

Runtime command pattern:

```bash
python scripts/ingest_fr24_screenshot_packet.py runtime_manifest.json --out out/flight_event_ledger.jsonl
```

Example manifest shape:

```json
{
  "run_id": "operator_defined_run_id",
  "input_path": "/local/runtime/path/input.pdf",
  "source_family": "fr24",
  "source_app": "optional app label",
  "observed_timestamp_local": null,
  "observed_timestamp_utc": null,
  "aircraft_label": null,
  "registration": null,
  "callsign": null,
  "geographic_context": null,
  "qa_flags": []
}
```

The manifest itself should be treated as runtime-local if it contains source filenames, private paths, aircraft identifiers, or case-specific metadata.
