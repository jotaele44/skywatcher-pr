# Design System Extraction

This document summarizes the components, layout grids, and tokens
extracted from the Spiderweb Demo design. It provides a reference
for implementing the PRIIS workbench in React/TypeScript.

## Layout Specification

The workbench layout consists of:

| Region       | Purpose                                    |
|-------------|--------------------------------------------|
| **Command bar** | Displays the application name and global actions. |
| **Left rail**   | Module navigation (Finance, Spatial, Anomaly, Graph, Query). |
| **Center workspace** | Houses the current module’s views (e.g., map, tables). |
| **Right inspector** | Shows details of the selected entity. |
| **Bottom timeline** | (Not yet implemented) Synchronizes time across modules. |

Use a CSS grid or flexbox layout to implement these regions. The
sidebar is ~200 px wide; the inspector is ~250 px; the command bar is
approximately 60 px tall.

## Component Inventory

- **EvidenceBadge** – A small badge that indicates the evidence tier
  (T1–T4). Use distinct colors for each tier (e.g., dark blue for
  T1, green for T2, orange for T3, gray for T4).
- **ConfidenceMeter** – A horizontal bar or icon that conveys
  confidence levels (low, medium, high). Implemented via a simple
  colored bar or a series of dots.
- **ContradictionFlag** – An icon or badge that appears when
  conflicting evidence is detected. Typically shown in red.
- **AnomalyCard** – A card summarizing an anomaly, including its
  type, description, and score. Clicking the card selects the
  anomaly and reveals details in the inspector.
- **EntityCard** – A reusable component for agencies, vendors,
  sites, contracts, events, and sources. Displays the name and
  short metadata.
- **MapLayerToggle** – A set of toggles or checkboxes for turning
  map layers on and off (e.g., contracts, infrastructure, reports).
- **TimelineEvent** – A marker in the timeline (to be built) that
  indicates a contract award, site event, or anomaly detection.
- **QueryComposer** – A text input with suggestions and a button
  to run a query. This will integrate with the RAG layer.

These components should be built as reusable React components with
TypeScript types. Use props to customize labels, colors, and click
handlers.

## Design Tokens

Define a set of CSS variables to ensure consistency across the UI:

```css
:root {
  --color-bg: #f9fafb;
  --color-fg: #1f2937;
  --color-border: #e5e7eb;
  --color-tier-1: #1d4ed8; /* blue */
  --color-tier-2: #059669; /* green */
  --color-tier-3: #d97706; /* orange */
  --color-tier-4: #6b7280; /* gray */
  --spacing-xs: 0.25rem;
  --spacing-sm: 0.5rem;
  --spacing-md: 1rem;
  --spacing-lg: 1.5rem;
  --radius-sm: 0.25rem;
  --radius-md: 0.5rem;
  --radius-lg: 1rem;
}
```

Use these tokens in your `index.css` and component styles to avoid
hard-coded values. Adapt the colors to meet accessibility
requirements.

## State Matrix

Each major component should handle at least these states:

- **Empty** – No data loaded or no selection made.
- **Loading** – Data is being fetched from the backend; display a
  spinner or skeleton.
- **Error** – An error occurred; show a message and allow retry.
- **Selected** – An entity is selected; highlight it in the table
  or map and show details in the inspector.
- **Contradiction** – Evidence conflict detected; show the
  ContradictionFlag and highlight conflicting data.

Implement these states in a consistent manner across modules to
improve user experience.

## Interaction Guidelines

- Clicking a row or marker updates the global selection state and
  opens the inspector.
- Navigating between modules preserves the current selection where
  appropriate (e.g., switching from Finance to Spatial keeps the
  selected contract highlighted if it has a location).
- Evidence tiers should always be visible on entities and findings.
- Do not allow the user to confirm findings without T1 or T2
  evidence.

This document is a living reference. Update it as new components
and design patterns emerge.