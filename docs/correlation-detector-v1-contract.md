# Skywatcher Correlation Detector V1 Contract

Status: **PROVISIONAL descriptive trajectory analysis**.

This detector operationalizes synchronized point-level comparison for historical
FR24 track data. It does not infer mission, coordination, targeting, intent, or
common tasking.

## Input contract

The detector accepts FR24-like CSV tracks with:

- an observation timestamp (UTC, ISO timestamp, or epoch Timestamp);
- position (Position as lat,lon, or separate latitude/longitude fields);
- optional altitude;
- optional speed;
- optional heading/direction.

A logical track is keyed by flight ID. When multiple manifestations of the same
flight ID are present, the denser valid-point manifestation is preferred.
Filename or folder similarity alone does not create a new identity binding.

## Synchronization contract

- Match only actual observations.
- Default maximum timestamp difference: **5 seconds**.
- Each source observation may participate in at most one synchronized match.
- No long-gap interpolation is performed.
- Proximity duration accumulates only between consecutive synchronized samples
  separated by at most **30 seconds**.
- Track pairs need at least **60 seconds** of temporal overlap to enter the
  registration-pair event analysis.

Missing geometry is BLOCKED_GEOMETRY; it is never converted to zero distance,
no encounter, or negative evidence.

## Descriptive classifications

**AIRBORNE_CO_ROUTE**
: At least 120 seconds within 5 km, median close-sample heading difference <=30
  degrees, median speed difference <=30 kt, and not predominantly a <=500 ft
  ground/airport pattern.

**CROSSING_TRAJECTORIES**
: Sustained proximity with median close-sample heading difference >=60 degrees.

**SYNCHRONIZED_PROXIMITY**
: Sustained synchronized proximity that does not satisfy the more specific
  co-route, crossing, or ground-pattern rules.

**SHARED_AIRPORT_OR_GROUND_PATTERN**
: At least 60 seconds within 5 km and at least 70% of close synchronized samples
  have both aircraft at or below 500 ft.

**BRIEF_PROXIMITY**
: At least one synchronized separation <=5 km, but less than 60 seconds of
  bounded close duration.

**OUT_OF_AREA_CONCURRENT**
: Synchronized observations exist, but minimum separation remains >50 km.

**TIME_ONLY**
: Sufficient synchronized samples exist without close spatial proximity.

**UNRESOLVED_SYNC_SPARSE**
: Fewer than three synchronized observations survive the bounded matcher.

**NO_SYNCHRONIZED_EVENT**
: No synchronized point event survives the timing/overlap gates.

**BLOCKED_GEOMETRY**
: One or both sides lack usable point geometry.

These states are descriptive and are not ordered suspicion scores.

## Frozen regression denominator

The V1 registry contains the 25 pair families emitted by the earlier record-level
detector. The old reported pair count is retained only as provenance for the
regression family; it is not treated as an encounter denominator.

Point-level V1 leaves only one pair with sustained airborne co-route evidence:

- N196DM <-> N407PR, 2025-09-12
- two independent same-day airborne co-route manifestations
- V4 descriptive promotion remains REPEATED_AIRBORNE_CO_ROUTE_CANDIDATE
- mission: UNKNOWN
- coordination: UNKNOWN

This independently reproduces the existing Flight Corpus V4 analytical candidate;
it does not create a new mission claim.

## Geometry recovery denominator

**N5854Z**
: 111 Master Flight Log records; 86 now have recoverable per-flight geometry;
  25 remain snapshot-only and unresolved.

**N936DM**
: 25 Master Flight Log records; 0 currently have recovered point geometry;
  all 25 remain blocked.

The direct historical 14-day snapshot track_points.csv source bytes remain
BLOCKED_SOURCE_BYTES.

## Interpretation gates

The following implications are forbidden:

- synchronized proximity -> coordination;
- airborne co-route -> common tasking;
- repeated co-route -> mission;
- shared airport -> shared mission;
- out-of-area concurrency -> coordinate artifact;
- no synchronized event -> no relationship.

Any future promotion beyond descriptive geometry requires independent evidence
outside this detector.
