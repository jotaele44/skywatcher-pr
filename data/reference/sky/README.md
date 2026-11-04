# Sky catalog (Sky Target Finder)

Vendored, pinned star and deep-sky data read by `src/skywatcher/core/sky/catalog.py`
for the Space-Track Sky Target Finder (`/space-track/sky`). See
`docs/SKY_TARGET_FINDER.md` for the capability and `ATTRIBUTION.md` for licensing.

| File | What it is |
|---|---|
| `sky_catalog.v1.json` | Generated. Stars to magnitude 6 (5,044, with names, Bayer/Flamsteed labels and aliases for 2,963), Messier 110, Caldwell 109, 88 constellations with stick figures. Schema `skywatcher.sky-catalog/v1`. |
| `sky_stars_deep.v1.json` | Generated. Unnamed stars with 6.0 < magnitude ≤ 7.5 (20,679) for narrow-field charts. Schema `skywatcher.sky-stars-deep/v1`. |
| `sources.lock.json` | Every input's URL, sha256, size, licence and role. The build refuses any input whose sha256 differs. |
| `caldwell_crosswalk.csv` | Hand-reviewed Caldwell crosswalk (designations, names, aliases, types, OpenNGC row, independent check position, overrides). |
| `messier_overrides.csv` | Hand-reviewed Messier names, aliases, types and OpenNGC row. |
| `star_patches.csv` | Corrections to upstream star names. |
| `LICENSE.d3-celestial`, `CC-BY-SA-4.0.txt`, `ATTRIBUTION.md` | Licence texts and attribution, copied from the pinned inputs by the build. |

## Rebuilding

```bash
python3 scripts/build_sky_catalog.py --fetch   # download pinned inputs into ~/.cache/skywatcher-sky-catalog
python3 scripts/build_sky_catalog.py           # regenerate outputs from the cache only (offline)
python3 scripts/build_sky_catalog.py --verify  # validate the committed outputs (offline; run in tests)
```

The build is deterministic and fails closed: a sha256 mismatch, a Messier or Caldwell
number that does not resolve, an OpenNGC Caldwell mapping that disagrees with the
crosswalk, a position outside tolerance of its independent check (0.3° Caldwell,
0.35° Messier), a corrupt Bayer token, a type outside the closed vocabulary or an
output over 1.5 MB stops it before anything is written.
