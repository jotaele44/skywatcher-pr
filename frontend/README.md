# Skywatcher PR Frontend

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

The client expects the backend to expose standard federation endpoints:

```text
GET    /api/auth/me
POST   /api/auth/login
POST   /api/auth/register
GET    /api/entities/:entity
POST   /api/entities/:entity/filter
POST   /api/entities/:entity
PATCH  /api/entities/:entity/:id
DELETE /api/entities/:entity/:id
POST   /api/functions/:name/invoke
POST   /api/integrations/llm/invoke
POST   /api/files/upload
```

## Development

```bash
npm install
npm run lint
npm run build
```

## Migration status

Removed proprietary runtime packages, generated config folders, app-builder branding, function shims, and direct SDK imports. This app now relies on the backend repository and the Hub federation contract for data, authentication, functions, and review operations.
