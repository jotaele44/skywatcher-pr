# Sky Cameras

**`/sky-cameras`** ("Sky Cameras" in the sidebar, under Sky Target Finder) gathers the
publicly available live cameras of Puerto Rico's sky, beaches, coast, mountains,
rivers, lagoons and lakes in one place. It also lets people contribute their own video.

"All the cameras" is a goal that keeps moving: cameras appear, move and go dark. The page
does not claim to be complete. It shows **coverage** instead: how many cameras there are,
how many were online at the last check, how many of the 78 municipalities have one, and
which categories have none yet. The gaps are what the contribution flow is for.

## What the page does

- **Browse.** Filter by category chips, by municipality, or with free-text search.
  Each card shows the provider, the municipality, the categories, the status at the last
  check, and a link to the owner's page.
- **Players or links.** A card plays inline only when the owner publishes an embeddable
  YouTube or Vimeo stream. The player is served from `youtube-nocookie.com` or
  `player.vimeo.com` in a sandboxed iframe, and no other host is ever framed. Every other
  camera is a link card that opens the owner's page. The **Players on / Links only**
  toggle switches every card to links, and the browser remembers the choice
  (localStorage, used only as a convenience).
- **Contribute.**
  - *Suggest a public camera:* a link to a camera its owner already shows to the public.
  - *Share your video:* a link to your own YouTube or Vimeo video, which can be embedded,
    or an uploaded file (MP4, MOV or WebM, up to 100 MB).

  Either way, the submitter must confirm two things: that they have the right to share
  it (or that the camera is already public), and that it shows a public place with no
  identifiable people who haven't consented and no private interiors.

  Optional fields: municipality, coordinates, description, a public credit name, and a
  private contact address for the reviewer. Uploaded videos also take a license choice:
  "show it here only" or CC BY 4.0.
- **Review queue.** Reviewers see pending submissions, including the private contact
  and a preview of any uploaded clip, and can **Approve** or **Reject** each one. They
  can also **Take down** an approved entry. The queue works only where the backend write
  guard allows writes: a local network, or `PRII_WRITE_TOKEN`.

## Moderation and privacy

- Submissions are **quarantined**. `POST /api/sky-cameras/submissions` is the only
  write open to the public. It writes only to the moderation queue, and nothing is
  listed or served until a reviewer approves it.
- Uploads are streamed to disk, hashed with sha256, and accepted only if their first
  bytes are MP4/MOV (`ftyp`) or WebM (EBML). The size cap is enforced both from
  `Content-Length` and while streaming.
- The submissions endpoint is rate-limited per client address, held in memory only.
  **No IP address is stored.**
- The contact address goes only to reviewers and never appears in a public payload.
- Rejecting or taking down a submission deletes its uploaded file.
- Approved third-party camera links are **never embedded automatically**. A curator
  adds an `embed` only after checking that the owner allows it.

## Data

| Path | What | Tracked |
|---|---|---|
| `data/reference/sky_cameras/cameras.v1.json` | Curated catalog (schema `schemas/sky_camera.schema.json`) | yes |
| `data/reference/sky_cameras/README.md` | Inclusion rules | yes |
| `data/sky_cameras/submissions.sqlite` | Moderation queue | no (gitignored) |
| `data/sky_cameras/uploads/` | Uploaded clips | no |
| `data/sky_cameras/status.json` | Last liveness check | no |

The runtime root is `SKYWATCHER_SKY_CAMERAS_ROOT` (default `data/sky_cameras`). Point it
at a writable, backed-up location on a real deployment, and always in the desktop build,
whose bundle directory may be read-only. Other settings:

- `SKYWATCHER_SKY_CAMERAS_MAX_UPLOAD_MB` (default 100)
- `SKYWATCHER_SKY_CAMERAS_SUBMISSIONS_PER_HOUR` (default 20; 0 disables the limit)
- `SKYWATCHER_SKY_CAMERAS_CATALOG_DIR`

Municipality names and the total of 78 come from `data/geo/pr_municipios_boundaries.json`.

### Seed catalog (verified 2026-11-07)

There are ten cameras in five municipalities: Carolina, San Juan, Río Grande, Fajardo
and Patillas. Sources are SkylineWebcams, EarthCam, Ozolio's YouTube live stream,
WorldCams and Hillside PR. Each URL was opened when the catalog was built, and four
SkylineWebcams feeds reported OFFLINE at that time.

Candidates that turned out not to be in Puerto Rico were left out. For example, the
"Culebra" surf-cam streams were actually in the USVI. No river, lake or El Yunque
interior camera was found, so those gaps show on the page.

Leads still to verify:
- USGS CoastCams (Isla Verde, Dorado) and the USGS Tres Palmas (Rincón) research
  cameras. usgs.gov refused the automated check.
- CariCOOS coastal stations.
- Any municipal or DRNA (Departamento de Recursos Naturales y Ambientales) reservoir
  or river cameras.

## Maintenance

```bash
python scripts/check_sky_cameras.py                  # liveness -> data/sky_cameras/status.json
python scripts/check_sky_cameras.py --write-catalog  # also refresh verified_at / last_known_status
python scripts/promote_sky_camera.py <submission_id> --lat 18.5 --lon -67.1
pytest tests/test_sky_cameras_catalog.py tests/test_sky_cameras_endpoints.py tests/test_sky_cameras_scripts.py
```

The checker needs network access, so it is a manual step rather than part of CI. It
treats a camera as `online` when:
- the owner's page answers 200,
- the page does not carry the provider's offline marker, and
- the camera's YouTube or Vimeo oEmbed still answers, if it has an embed.

A site that refuses automated clients is recorded as `unknown`, not `offline`.

The promotion script copies an approved camera or video *link* into the tracked
catalog. Uploaded clips stay in the runtime store and are never committed.

## API

| Method | Path | Access |
|---|---|---|
| GET | `/api/sky-cameras?category=&municipality=&q=` | public |
| GET | `/api/sky-cameras/coverage` | public |
| GET | `/api/sky-cameras/media/{submission_id}` | public; approved uploads only (404 otherwise) |
| POST | `/api/sky-cameras/submissions` | public; multipart, writes to the queue only |
| GET | `/api/sky-cameras/submissions?status=` | reviewer (write guard) |
| GET | `/api/sky-cameras/submissions/{id}/media` | reviewer |
| POST | `/api/sky-cameras/submissions/{id}/decision` | reviewer; `{"decision": "approved"\|"rejected"\|"removed", "note"}` |

Submission form fields:
- `kind`: `camera_link`, `video_link` or `video_upload`
- `title`
- `url`, or `file` when `kind` is `video_upload`
- `categories`: repeatable, from `sky beach coast mountain river lake lagoon city`
- `license`: `display-only` or `cc-by-4.0`
- `attest_rights` and `attest_consent`
- Optional: `municipality`, `lat`/`lon`, `description`, `contributor`, `contact`

The code lives in `server/backend/cameras_router.py` and `src/skywatcher/core/cameras/`.

## Boundary

This repository's dashboard is a diagnostic surface (see the README). The catalog and
API are built so that the hub app (`thehub-pr`) can render the same cameras later.
Before the contribution form is opened to the general public, run it behind
`PRII_WRITE_TOKEN` and decide who reviews submissions and how fast takedown requests are
answered.
