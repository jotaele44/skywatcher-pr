# Sky Cameras catalog

`cameras.v1.json` is the curated list behind the **Sky Cameras** page (`/sky-cameras`).
Its shape is `schemas/sky_camera.schema.json`; `tests/test_sky_cameras_catalog.py`
checks every entry. Policy, API and moderation are documented in `docs/SKY_CAMERAS.md`.

## Inclusion rules

1. **Public and owner-published.** The camera's owner (or an aggregator carrying the
   owner's stream) shows it to the public without login. No private, leaked or
   guessed stream URLs.
2. **A public place in Puerto Rico** — sky, beach, coast, mountain, river, lake or
   lagoon views. No cameras aimed into homes, workplaces or at individuals.
3. **Never invent a URL.** Every `page_url` and `source_url` was opened by a person (or
   by `scripts/check_sky_cameras.py`) on `verified_at`.
4. **Embed only when the owner allows it.** `embed` is set only for a YouTube or Vimeo
   stream whose owner permits embedding (YouTube oEmbed answers for it). Everything
   else is `null` and the page shows a link to the owner's page.
5. **Coordinates are approximate** view locations, inside the PR bounding box, and
   `municipality` is one of the 78 names in `data/geo/pr_municipios_boundaries.json`.

## Adding a camera

Either edit `cameras.v1.json` directly, or approve a community suggestion on the page
and promote it:

```bash
python scripts/promote_sky_camera.py <submission_id>   # appends to cameras.v1.json
python scripts/check_sky_cameras.py                     # refresh liveness
pytest tests/test_sky_cameras_catalog.py
```
