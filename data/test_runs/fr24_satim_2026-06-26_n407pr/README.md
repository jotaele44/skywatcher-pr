# FR24 SATIM Test Run: 2026-06-26 N407PR

Event ID: `FR24_2026-06-26_2313UTC_N407PR_TEST01`

## Source

- Packet: `IMG_6925.pdf`
- Source app: Flightradar24 over Apple Maps
- Visible timestamp: Fri, Jun 26, 2026, 11:13 PM UTC -04:00
- Visible aircraft label: `N407PR`
- Visible context: Puerto Rico overview, Arecibo/San Juan labels, west-central track corridor, San Sebastian/Lares/PR-370 zoom sequence, forest/road/structure visual targets

## Files

| File | Description |
|---|---|
| `flight_event_ledger.jsonl` | Normalized aircraft-event stub |
| `visual_review_ledger.csv` | SATIM visual observation stub |
| `tile_artifact_ledger.csv` | Artifact-control stub |

## Analyst constraints

- Treat screenshot-derived observations as T4 unless corroborated by raw ADS-B data, independent imagery, or GIS layers.
- Do not infer facility purpose from screenshots alone.
- Treat diagonal dark line in FR24 map context as `TRACK_LINE` by default unless contradicted by independent basemap evidence.
- Treat zoomed forest/vegetation frames as low-to-medium confidence unless stable coordinates are recovered.
