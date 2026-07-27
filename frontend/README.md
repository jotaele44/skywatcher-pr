# Skywatcher PR Frontend

> **Diagnostic-only surface (ADR 0001, Phase 2).** This repo's dashboard is a
> development and diagnostic tool for this producer only. The supported product
> surface for the PRII federation is the hub app
> (`thehub-pr/server/frontend`), which renders this producer's data alongside
> the other engines. See `thehub-pr/docs/adr/0001-federated-engines-single-hub.md`.

This frontend has been detached from the proprietary app-builder runtime and now targets the PRII federation backend layer.

## Backend target

| Field | Value |
|---|---|
| Program id | `skywatcher-pr` |
| Canonical backend repo | `jotaele44/skywatcher-pr` |
| Frontend role | Airspace / aircraft intelligence frontend |
| Runtime client | `src/api/federationClient.js` |

## Runtime configuration

```bash
cp .env.example .env.local
VITE_SKYWATCHER_API_BASE_URL=http://localhost:8000/api
VITE_FEDERATION_PROGRAM_ID=skywatcher-pr
VITE_FEDERATION_MODE=diagnostic
```

## Backend endpoints

`src/api/federationClient.js` is written against the full federation contract, but
`server/backend/main.py` here is a deliberately small read-mostly surface over
committed artifacts. Verified against a running server:

| Endpoint | Implemented? |
|---|---|
| `GET /api/health`, `GET /health` | yes |
| `GET /api/apps/public-settings` | yes — reports `requires_auth: false`, `mode: diagnostic` |
| `GET /api/auth/me` | yes, but always **401** in diagnostic mode |
| `GET /api/entities/:entity` | yes |
| `GET /api/entities/:entity/:id` | yes |
| `POST /api/entities/:entity/filter` | yes (a read, despite the verb — deliberately not write-guarded) |
| `POST /api/entities/:entity` | yes — **write-guarded**, session-scoped only |
| `PATCH /api/entities/:entity/:id` | yes — **write-guarded**, session-scoped only |
| `DELETE /api/entities/:entity/:id` | **no** |
| `POST /api/auth/login`, `/register`, `/verify-otp`, `/resend-otp`, `/password/*` | **no — 404** |
| `POST /api/functions/*`, `/api/integrations/*`, `/api/files/upload` | **no** |

Writes never touch the repository: creates and updates land in an in-memory
overlay that disappears on restart (`_created` / `_overlay` in
`server/backend/main.py`).

### Authentication

There is no authentication backend. Because the six `/auth/*` endpoints the client
calls all return 404, the `/login`, `/register`, `/forgot-password` and
`/reset-password` routes are **not rendered** while
`public_settings.requires_auth` is false — `src/App.jsx` redirects them to `/`,
after waiting for public settings to resolve so a real `requires_auth: true`
backend is never mistaken for diagnostic mode. Set
`VITE_FEDERATION_REQUIRE_AUTH=true`, or have the backend report
`requires_auth: true`, and the pages come back.

### Write authorization

Mutating routes are guarded by `require_write_access`:

- `PRII_WRITE_TOKEN` **set** → every mutating request needs `Authorization: Bearer <token>`
- `PRII_WRITE_TOKEN` **unset** → writes are served to local-network clients
  (loopback, RFC1918 private, link-local) and refused for public addresses

Reads are never affected. With the token set this UI cannot currently supply it;
see `docs/MATURITY_AUDIT.md` for the tracked federation-wide fix.

## Development

```bash
npm install
npm run lint
npm run build
```

## Migration status

Removed proprietary runtime packages, generated config folders, app-builder branding, function shims, and direct SDK imports. This app now relies on the backend repository and the Hub federation contract for data, authentication, functions, and review operations.
