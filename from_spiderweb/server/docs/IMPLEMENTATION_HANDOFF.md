# Implementation Handoff

This document explains how to continue the development of PRIIS
V1.5 beyond the prototype contained in this repository. It
summarizes the current state and outlines next steps for
collaborators.

## Current State

The repository contains:

1. A **React/TypeScript frontend** scaffold with a basic layout,
   MapLibre integration, a finance table, and an inspector that
   reflects the global selection.
2. A **FastAPI backend** with in-memory mock data and simple
   endpoints for contracts, sites, anomalies, and queries.
3. A **PostgreSQL/PostGIS database schema** defining tables for
   agencies, vendors, sites, contracts, anomalies, events, sources,
   and findings, along with seed data.
4. An **ingestion script** that can load contract records from a
   CSV into the database using SQLAlchemy.
5. A **retrieval layer stub** to scaffold the hybrid search
   functions needed by the query layer.
6. Detailed **documentation**, including a runbook, deployment
   guide, security model, data import guide, vector lock notice,
   design system extraction, and prompts for coding assistants.

## What Needs To Be Done

1. **Database Integration** – Replace the backend’s mock lists with
   SQLAlchemy models. Create a `database.py` module to configure
   the engine and session. Update endpoints to query the
   database.
2. **Authentication & Authorization** – Introduce a user model and
   implement JWT-based auth. Define roles (analyst, admin) and
   enforce role-based access control on ingestion and query endpoints.
3. **Implement Retrieval** – Choose and configure a vector store.
   Implement keyword and vector search functions, geospatial queries
   using PostGIS, and optional graph queries. Wire these into the
   `/query` endpoint.
4. **LLM Orchestration** – Design and integrate an agent that
   constructs prompts based on retrieved evidence, calls the LLM
   provider (OpenAI/Anthropic), validates the response, and
   returns structured answers according to the answer contract.
5. **Frontend Enhancements** – Load data from the backend using
   fetch/axios. Replace mock tables with dynamic components like
   TanStack Table. Implement module switching and timeline
   synchronization. Add visual components such as EvidenceBadges
   and ConfidenceMeters.
6. **Testing & CI/CD** – Write unit and integration tests for the
   backend and frontend. Set up a CI pipeline (e.g., GitHub
   Actions) to lint, test, and build. Use CD to deploy to your
   chosen hosting platform.

## Collaboration Tips

- Keep your code modular. New features should be added in
  appropriately named files and directories.
- Follow the design system guidelines documented here to ensure
  consistency.
- Document decisions in `docs/` and update the runbook as the
  architecture evolves.
- Use issue trackers and PR templates to coordinate tasks,
  especially when integrating with external services (e.g., LLMs,
  vector stores).

## Questions & Feedback

For further clarifications or to propose changes, open an issue in
your project repository or consult the original design documents.