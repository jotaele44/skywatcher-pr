# FR24 Dashboard UI

## Purpose

Surfaces the FR24 dashboard review queue (`fr24_dashboard_review_queue.csv`) in the standalone Puerto Rico Airspace Intelligence dashboard so an operator can work the highest-priority review items first. The queue is **read-only with respect to candidate confirmation**: no UI control sets a `confirmed*` / `verified_event` / `validated_aircraft_event` label.

## Pipeline

```
fr24_dashboard_review_queue.csv
        │
        ▼
fr24/dashboard_data.py  →  fr24_dashboard_review_queue.json
        │                            │
        │                            ▼
        │              dashboard/dashboard.html fetches it
        │                            │
        │                            ▼
        └────────────►  ReviewQueueTab in dashboard/dashboard.jsx
```

## Generate the JSON

```bash
python fr24/dashboard_data.py \
  --queue-csv data/_manifests/fr24_audit/fr24_dashboard_review_queue.csv \
  --summary-json data/_manifests/fr24_audit/fr24_dashboard_queue_summary.json \
  --output-json fr24_dashboard_review_queue.json
```

Defaults match the canonical paths so `python fr24/dashboard_data.py` works
without arguments after the dashboard queue has been generated.

The JSON payload contains:

| Field | Purpose |
|---|---|
| `generated_at` | ISO timestamp |
| `dashboard_data_version` | `fr24_dashboard_data_v0.1.0` |
| `policy` | `candidate_only_no_auto_confirmation` |
| `allowed_queue_statuses` | Mirrors the lifecycle the UI exposes |
| `row_count` | Rows surfaced (after prohibited-label drop) |
| `prohibited_label_dropped` | Defense-in-depth drop count (expected zero) |
| `tier_counts`, `source_counts` | Pre-computed for the dashboard header |
| `upstream_summary` | Verbatim from `fr24_dashboard_queue_summary.json` |
| `rows` | List of queue rows |

## Serve the dashboard

```bash
python -m http.server 8080
# then open http://localhost:8080/dashboard.html
```

The dashboard fetches both `dashboard_data.json` (existing) and
`fr24_dashboard_review_queue.json` (new) in parallel. If the FR24 file is
missing, the dashboard still loads — the new tab simply shows an empty
state explaining how to generate the file.

## Review Queue tab

| Element | Behavior |
|---|---|
| Tier filter chips (ALL / 1 / 2 / 3 / 4 / 5 / 6) | Filters by `priority_tier` |
| Source filter chips | Filters by `queue_source` |
| Row card | Shows priority, tier, image, review/selection/dedup status, and the current queue status |
| Status transition buttons | Switch among the four allowed queue statuses (open / deferred / rejected / accepted_after_manual_review) |
| "Candidates only" disclaimer | Persistent banner at top of tab |

State transitions are persisted to **`localStorage`** keyed by `candidate_id`
(falling back to `image_path` then `image_name`). The persisted state is a
plain JSON map of `{candidate_id: queue_status}` under the key
`fr24_dashboard_queue_state_v1`. No transition writes to the underlying
CSV — the operator's working state stays local to the browser session.

## Allowed lifecycle

- `dashboard_review_open` (default for every row in the JSON)
- `dashboard_review_deferred`
- `dashboard_review_rejected`
- `dashboard_review_accepted_after_manual_review`

## Prohibited labels (never surfaced, never settable)

- `confirmed`
- `confirmed_aircraft_event`
- `confirmed_anomaly`
- `confirmed_route`
- `verified_event`
- `validated_aircraft_event`

The exporter drops any row carrying a prohibited label and counts it in
`prohibited_label_dropped`. The browser UI has no control that could write
one.

## Recommended local validation

```bash
python -m py_compile fr24/dashboard_data.py
python -m pytest tests/test_fr24_dashboard_data.py -q
python fr24/dashboard_data.py
python -m http.server 8080
# open http://localhost:8080/dashboard.html → Review Queue tab
```
