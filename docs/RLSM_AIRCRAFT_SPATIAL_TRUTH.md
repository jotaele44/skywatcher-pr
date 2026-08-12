# RLSM aircraft spatial truth v0.1

This contract turns an aircraft label extracted from an FR24 screenshot into a
bounded, auditable aircraft coordinate. It does not infer that the aircraft was
at a map label. A coordinate is published only when a selected aircraft glyph
and an accepted screenshot georeference are both present.

## Coordinate and rotation conventions

- Decode the source image and apply EXIF transpose before measurement.
- Pixel origin is the upper-left of that transposed source image. `x` increases
  right and `y` increases down. Coordinates are source-image pixels, not crop
  coordinates. `pixel_x`/`pixel_y` are the arithmetic foreground-component
  centroid of the selected glyph.
- The searched viewport is the configured `label_layer` rectangle. Its source
  rectangle is persisted with each marker and georeference decision.
- `icon_rotation_deg` is zero at image-up and increases clockwise in `[0, 360)`.
  A symmetric glyph may retain an undirected axis in candidate evidence while
  the direction-bearing field remains null.
- `heading_deg` is independent OCR/legacy evidence. Marker detection never
  overwrites it. Consumers may compare heading and rotation, but cannot silently
  substitute one for the other.

## Marker binding and provenance

The detector preserves every plausible high-saturation FR24-color component in
`aircraft_marker_detections`. Exactly one terminal row per targeted screenshot
and detector version is stored in `aircraft_marker_frames`:

`selected`, `ambiguous_candidates`, `ambiguous_observation`, `no_marker`,
`missing_source`, or `unreadable`.

Pixel fields are copied to `aircraft_observations` only when the frame has
exactly one aircraft observation and one candidate clears both the confidence
threshold and the separation margin. Multiple plausible candidates and multiple
aircraft rows fail closed. A normal rerun resumes after terminal decisions;
when a version's frame/evidence is explicitly cleared for recomputation, its
stale observation binding is cleared before a new decision is made.

## Georeference and relative zoom

Multi-anchor fits use measured, vocabulary-resolved pins. Static anchors whose
pixels were projected from a PR-wide approximation are excluded from fitting and
from zoom training. Accepted transforms persist the coefficients

`lon = lon0 + dlon_dx * x` and `lat = lat0 + dlat_dy * y`,

plus viewport profile, anchor count, axis scales, normalized meters-per-pixel,
axis disagreement, residual, confidence, error, and evidence. Bad residual or
geometry receives an explicit rejected status.

Zoom is a relative, self-calibrated ladder local to one viewport profile. Scale
clusters are matched only to power-of-two rungs within the declared log2
tolerance. The densest corroborated cluster is relative rung zero; this is not
an assertion about FR24's private absolute zoom identifier. Unsupported scales
remain unassigned. Support is counted by independent evidence unit: screenshots
in the same near-duplicate group contribute one vote, while ungrouped
screenshots contribute individually. Clusters with fewer than three independent
accepted multi-anchor fits may remain in the ladder table as evidence-only
records, but they are neither assigned to frames nor used for transfer.

One-anchor recovery requires all of the following:

1. exactly one measured anchor in the target frame;
2. a transferable rung learned only from accepted multi-anchor fits;
3. an independently linked source in the same near-duplicate group and viewport
   profile; and
4. a combined estimated error no greater than 500 m.

Recovered frames cannot become evidence sources for other recovered frames.

## Aircraft projection and uncertainty

A selected marker is projected only through an accepted persisted transform.
The output error combines georeference error and marker-centroid uncertainty in
meters. Rows exceeding 500 m are not located. Published position confidence is
bounded by the weaker of marker and georeference confidence.
Database triggers reject partial marker bindings, partial coordinate metadata,
unsupported position methods, and observation errors above that ceiling.

The read-only API exposes located rows through both the mixed
`AirspaceObservations` feed and the evidence-only `RLSMSpatialObservations`
entity. The latter is fetched at full-corpus scale by the diagnostic GUI;
`RLSMSpatialFrames` and `RLSMZoomRungs` preserve terminal accounting and zoom
evidence. The `/spatial-truth` GUI route shows the same contract. CSV exports
carry observations, every marker candidate, terminal decisions, transforms,
and relative rungs.

## Explicit deferrals

- Dedicated scale-bar OCR remains deferred while no more than 15% of
  otherwise-recoverable frames remain unresolved. For the dashboard metric,
  otherwise-recoverable means a selected marker and at least one measured
  anchor; unresolved means no accepted georeference.
- Track-polyline extraction is outside v0.1.

Run `./run-rlsm.sh` on the operator machine to populate corpus results, then use
`./run-rlsm.sh --status` and `outputs/rlsm_run_report.md` to audit accounting.
