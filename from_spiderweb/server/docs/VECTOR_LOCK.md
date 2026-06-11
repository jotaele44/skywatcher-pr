# Vector Lock

This document records that the Spiderweb Demo handoff has been
designated as the visual and interaction baseline for the PRIIS
V1.5 prototype. All UI components, layouts, and flow patterns in
this repository are derived from or aligned with that baseline.

Key implications of the vector lock:

1. **No redesign from scratch** – The existing workbench pattern of a
   command bar, left rail, central workspace, right inspector, and
   bottom timeline is preserved.
2. **Component extraction** – Elements such as Evidence Badges,
   Confidence Meters, Contradiction Flags, and Anomaly Cards have
   been cataloged in `DESIGN_SYSTEM_EXTRACTION.md` and should be
   reimplemented in React/TypeScript rather than copied from the
   prototype.
3. **Map engine correction** – Leaflet has been replaced with
   MapLibre to align with the open-stack mapping strategy.
4. **Separation of concerns** – The design reference remains purely
   visual; schemas, state management, and backend architecture are
   defined in the `/contracts`, `/database`, and `/backend` directories.

Refer to `docs/DESIGN_SYSTEM_EXTRACTION.md` for a list of extracted
components and to the runbook for instructions on implementing
them.