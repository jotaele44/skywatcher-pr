# SATIM human-annotation binding contract

## Purpose

Human markup is an evidence manifestation that defines candidate ROIs. It is not imagery and it is never a measurement source.

The contract exists to prevent a colored annotation line or filled spot from creating the exact edge, blur, or radiometric signal the detector is supposed to test.

## Hard invariant

For every measured ROI:

```text
measurement_sha256 == pristine_source_sha256
measurement_sha256 != annotation_sha256
```

Violation fails closed.

## Positive-only semantics

Unless an annotation explicitly declares an exhaustive negative denominator, unmarked pixels and unmarked regions are `UNKNOWN`.

Therefore a positive-only annotation run may report:

```text
SUPPORTED | PARTIAL | UNRESOLVED | CONTRADICTED
```

It must not synthesize `TN` or `FN` from missing markup.

## Color-to-candidate mapping

The mapping produces candidate sets only. It never promotes a final SATIM class by color alone.

| Color | Human meaning | Candidate set |
|---|---|---|
| RED | tile seam | `SATIM-A01` |
| BLUE | blurred spot | `SATIM-A03`, `SATIM-A05` |
| YELLOW | shadow mismatch/anomaly | `SATIM-A09`, `SATIM-A02`, `REAL_SHADOW`, `UNRESOLVED` |

### RED

A red line is a candidate seam geometry. Production promotion still requires independent pixel evidence. When overlapping screenshots exist, register pristine source imagery and classify the candidate as `SCREEN_LOCKED`, `GROUND_LOCKED`, or `UNRESOLVED`. Ground-locking disproves a screen-only overlay but does not by itself prove a provider tile seam.

### BLUE

A blue region is a blur candidate. Measure pristine pixels inside the rebound ROI against a local control annulus using at least two independent sharpness signals, for example Laplacian variance, gradient energy, or high-frequency residual. Directional smear (`SATIM-A03`) and resampling/interpolation (`SATIM-A05`) remain separate hypotheses until causal evidence distinguishes them.

### YELLOW

A yellow region is an anomaly candidate. Preserve `SATIM-A09`, `SATIM-A02`, genuine shadow, and unresolved explanations until solar/shadow geometry, radiometry, or independent source imagery adjudicates the cause.

## Required provenance

Freeze and record:

- pristine source filename and exact SHA-256
- annotation manifestation filename and exact SHA-256
- source-to-annotation registration transform
- accepted annotation pixels and rejected source-color pixels
- ROI geometry in original-source pixel coordinates
- detector measurements from pristine bytes only
- machine state and contradictions
- all superseded results

## Arithmetic closure

Every explicit positive ROI belongs to exactly one agreement state:

```text
denominator = SUPPORTED + PARTIAL + UNRESOLVED + CONTRADICTED + MISSING_RESULTS
```

`certification_ready` requires arithmetic closure, zero unresolved ROIs, and zero missing results. Additional source-provenance requirements can still block certification.

Color segmentation also closes independently:

```text
detected_color_pixels
= accepted_annotation_pixels
+ rejected_source_color_pixels
+ unexplained_pixels
```

Any nonzero unexplained residue keeps the annotation binding open.

## Regression gates

Positive gates:

1. pristine measurement bytes pass the SHA-256 invariant;
2. all explicit ROIs receive unique IDs;
3. multi-artifact frames preserve multiple independent ROIs;
4. agreement arithmetic closes exactly;
5. annotation-color false positives in the source image are retained as rejected color pixels rather than silently discarded.

Negative gates:

1. annotation image supplied as measurement bytes -> fail;
2. duplicate ROI ID -> fail;
3. machine result for an unknown ROI ID -> fail;
4. missing machine result -> arithmetic closes but certification remains false;
5. unmarked region -> remains `UNKNOWN`, never automatic negative.

## Relationship to SATIM artifact arbitration

This layer precedes `ArtifactAssessmentEngine`. It creates bound candidate ROIs and provenance. The existing SATIM engine still arbitrates candidate classes and applies mandatory interpretation restrictions; human color labels do not bypass those gates.
