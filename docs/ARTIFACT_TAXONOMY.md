# SATIM Artifact Taxonomy

This taxonomy prevents map/screenshot artifacts from being promoted into physical-site claims.

## Core classes

| Code | Label | Description | Common source |
|---|---|---|---|
| `TRACK_LINE` | Aircraft route line | FR24 playback/route geometry overlaid on map | Flight app UI |
| `TILE_SEAM` | Tile seam | Boundary between map imagery tiles | Basemap rendering |
| `UI_OVERLAY` | Interface overlay | App logo, player, map label, aircraft tag, share icon, legal mark | Mobile screenshot |
| `ZOOM_BLUR` | Zoom blur | Pixelation/smear from over-zoomed imagery | Mobile map zoom |
| `COMPRESSION` | Compression artifact | JPEG/PDF artifacts, halos, blockiness | Screenshot/PDF export |
| `MIXED_EPOCH` | Mixed imagery epoch | Adjacent imagery differs by season, sun angle, source, or date | Basemap mosaic |
| `SHADOW_CONFUSION` | Shadow ambiguity | Vegetation/terrain shadow mistaken for structure or void | Low sun/terrain |
| `LABEL_COLLISION` | Label collision | Place/road/POI labels overlap target | Basemap annotations |
| `STRUCTURAL_SIGNAL` | Physical candidate | Candidate road, clearing, structure, pond, pad, corridor, or access pattern after artifact controls | Imagery observation |

## Promotion rule

A row can be promoted to `STRUCTURAL_SIGNAL` only if:

1. artifact classes have been considered;
2. observation has a page reference;
3. observation has a map context or anchor;
4. at least one contradiction is logged;
5. confidence is not `high` unless multiple independent frames or sources support it.

## Contradiction examples

- The line follows known FR24 track overlay, not terrain.
- Feature disappears at a different zoom level.
- Feature is covered by player UI or label.
- Feature aligns with image tile edge.
- Feature is consistent with vegetation shadow or hillside relief.
- No stable georeference is available from screenshot alone.
