# Claude Code Continuation Prompts

These prompts can be used with Claude Code (or similar coding
assistants) to continue developing the PRIIS V1.5 system. They help
focus the assistant on specific tasks and maintain architectural
alignment.

## Extend the Backend

```
You are continuing work on the PRIIS backend. The current version
uses FastAPI with in-memory mock data. Replace the mock lists with
SQLAlchemy models connected to a PostgreSQL database specified by
the `DATABASE_URL` environment variable. For each endpoint
(`/contracts`, `/sites`, `/anomalies`), implement GET methods that
query the database and return Pydantic models. Write a test using
`pytest` to validate that the `/contracts` endpoint returns at
least one contract after the seed data is loaded.
```

## Add Authentication

```
You are enhancing security for the PRIIS backend. Integrate JWT
authentication using the `fastapi.security` module. Add a login
endpoint that issues tokens and require valid tokens on all
protected endpoints. Define user roles in the database and add
authorization checks so that only users with the role `analyst`
can call the data ingestion endpoint. Update the deployment
instructions in `docs/deployment.md` to mention the new auth
requirements.
```

## Build Query Layer

```
You are implementing the query layer for PRIIS. The `/query`
endpoint should accept a natural-language query and use the
retrieval layer (`rag/retrieval.py`) to fetch relevant entities.
After combining retrieval results, construct a prompt for the LLM
that cites evidence and includes an answer contract template. The
LLM's response should be parsed into the `llm_answer_contract` format.
Write unit tests that mock the retrieval functions and verify that
the query handler returns the expected JSON structure.
```

## Extend the Frontend

```
You are adding interactivity to the PRIIS frontend. Fetch the list
of contracts from `/contracts` on component mount and display
them in a paginated table using TanStack Table. When a row is
selected, highlight it and show its details in the inspector. Add a
loading spinner while data is being fetched. Provide type safety by
defining a `Contract` interface matching the backend model.
```

## Connect Map to Backend

```
You are improving the MapPane component. Instead of a dummy click
handler, fetch the list of sites from the `/sites` endpoint and add
markers to the map. When a marker is clicked, update the global
selection state with the site details. Use MapLibre's
`Popup` class to show the site name on hover. Ensure that markers
reuse a single GeoJSON source rather than adding individual layers
for each feature.
```