# FR24 non-synthetic export gate

## Vector

`BUILD_SKYWATCHER_NON_SYNTHETIC_EXPORT`

## Objective

Promote reviewed FR24-derived observations into a Hub-consumable, non-synthetic airspace package without overstating operator, tenant, or hangar attribution.

## Export entities

| Entity | Schema | Purpose |
|---|---|---|
| Airfield / helipad registry | `schemas/airfield_registry.schema.json` | Puerto Rico facility anchor set for endpoint attribution |
| Hangar / ramp zone | `schemas/hangar_zone.schema.json` | Source-tiered facility sub-zones; unlabeled zones stay unlabeled |
| Airspace observation | `schemas/airspace_observation.schema.json` | Reviewed observation stream from FR24 screenshots/tracks |
| Flight endpoint event | `schemas/flight_endpoint_event.schema.json` | Start/end/touch-and-go match against facility/zone registry |

## Required production-mode checks

1. Reject any row where `synthetic == true`.
2. Require `source_id`, `lineage_id`, `confidence`, and `review_status` on every row.
3. Require endpoint matches to expose:
   - `match_method`;
   - `distance_m`;
   - `matched_facility_id`;
   - `confidence`;
   - `review_status`.
4. Treat Culebra, Vieques, and other unlabeled hangars/zones as `tenant_status: unlabeled` unless a public source confirms tenant/operator identity.
5. Treat FR24 callsign/operator inference as a candidate signal unless corroborated by T1/T2 source material.

## Source-tier rule

| Tier | Meaning in Skywatcher |
|---|---|
| T1 | Technical or official facility/track/export record |
| T2 | Operational/institutional source, airport publication, agency notice |
| T3 | Direct eyewitness/operator note requiring review |
| T4 | Secondary map label, media, or analyst-derived context |

## Hub handoff

The Hub should ingest only the validated package streams and manifest. Skywatcher keeps FR24 processing internals, screenshot review queues, and tenant-confidence logic inside this repo.

## Acceptance string

```text
ACCEPT_WHEN: production-mode package validates with zero synthetic rows, all endpoint events have facility match basis, and unlabeled hangar zones remain non-attributed.
```
