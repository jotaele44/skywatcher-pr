# SAC sky-domain ingestion contract

Status: **PROVISIONAL / INTERNAL**

This change establishes the evidence and contract layer for integrating the Sociedad de Astronomía del Caribe (SAC) into Skywatcher. It does **not** declare the SAC archive exhaustive or the integration certified.

## Frozen baseline

- Repository baseline: `0521581cae5d7a46b04450322682a81a03d47149`
- Source canonical origin: `https://www.sociedadastronomia.com/`
- User-supplied URL parameters such as `fbclid` are preserved only in raw provenance; they are excluded from canonical URL identity.

## Source authority

`source_class = LOCAL_ASTRONOMICAL_OBSERVATION`

SAC may provide locally valuable observations, predicted visibility, directions, azimuths, timing, images, video references, and post-event interpretations. SAC is not treated as a canonical orbital-object identity authority. Upstream authoritative object/launch/orbit identifiers override name or proximity heuristics.

## Event classes

- meteor / fireball / bolide
- rocket launch / upper-stage visibility
- spacecraft pass / breakup
- satellite / constellation visibility
- reentry / debris
- asteroid / NEO
- comet
- planetary / lunar / stellar visibility
- eclipse / occultation
- other locally observed astronomical event

## Object / event / observation separation

Skywatcher must preserve three distinct entities:

1. `object` — physical object or canonical upstream identity when resolvable.
2. `event` — launch, pass, reentry, breakup, meteor, occultation, etc.
3. `observation` — SAC or another observer's report from a location/time/direction.

No source article, object, event, or observation is identical merely because its name, time, category, or proximity agrees.

## Required provenance

Every source manifestation must preserve:

- raw URL
- canonical URL
- retrieval UTC
- publication date/time as represented by source
- title and author strings exactly as observed
- raw/source manifestation hash when raw bytes are available
- normalized logical record hash
- parser/version identity
- source snapshot identifier
- supersession state

## Discovery / archive closure

Search-engine results are discovery only. `site:` search results, tags, nearest articles, result counts, or apparent chronology cannot prove archive exhaustiveness.

Archive certification requires a bounded denominator produced from SAC-controlled archive/tag/pagination/sitemap surfaces or another independently authoritative enumeration. Deleted or changed pages remain separate manifestations.

## Correlation gates

A SAC event can become a conventional-explanation candidate for another observation only after independent gates:

- `TIME_GATE`
- `VISIBILITY_GATE`
- `LOCATION_GATE`
- `AZIMUTH_GATE`
- `ELEVATION_GATE` when available
- `TRAJECTORY_GATE`
- `DURATION_GATE`
- `APPEARANCE_GATE`
- `UPSTREAM_ID_GATE` when an authoritative object/mission identifier is available

Final correlation states:

- `MATCHED`
- `PARTIAL`
- `CONTRADICTED`
- `UNRESOLVED`

A time-only, name-only, category-only, or proximity-only match is forbidden.

## Current bounded discovery set

The initial discovery snapshot contains only pages independently surfaced during the 2026-09-11 integration pass. It is intentionally non-exhaustive and therefore cannot close the archive denominator.

Known high-value positive fixtures include:

- 2025-01-25 Puerto Rico meteor / small asteroid: reported about 19:05 AST, viewed north, movement east-to-west.
- 2025-02-18 Falcon 9 visibility prediction: predicted approximately 19:21–19:24 AST from Puerto Rico, west-northwest, roughly 290–300 degrees, right-to-left.
- 2024-11-19 Starship visibility prediction: predicted roughly 18:12–18:14 AST, northwest/north, left-to-right.
- 2024-03-03 Antares lunar occultation: Puerto Rico local timing and object-specific visibility context.

These are regression fixtures, not a claim of complete SAC coverage.

## Certification gates

`SKYWATCHER SKY-DOMAIN / SAC INTEGRATION CERTIFIED` is prohibited until all of the following pass inside a declared scope:

- bounded source denominator
- source count closure
- source manifestation freeze and hashes
- schema validation
- stable event/object/observation identifiers
- duplicate and null adjudication
- timezone conversion validation
- no M:N multiplication
- authoritative upstream identifiers resolved where available
- complete candidate preservation
- positive regression fixtures
- deliberately false time/azimuth/trajectory negative fixtures
- contradiction ledger closure
- deterministic replay
- user-facing GUI parity if promoted from internal to production
- zero unexplained residue inside the certification scope

Until then the state is `PROVISIONAL`.