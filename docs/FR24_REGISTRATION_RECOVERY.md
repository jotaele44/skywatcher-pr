# FR24 Registration Recovery & Alerts

This covers two operator questions: **why aircraft registrations went missing**,
how to **recover** them, and how to **set up registration alerts** in the PRIIS
server app (`server/`, `server/priis.db`).

## Why registrations were missed

`scripts/fr24_vision_ingest.py` extracts each aircraft's `registration` (plus
operator, type, route, altitude, speed) into the FR24 CSV. But the server ingest
step used to store only `id/at/site_id/ref_id/label`, and the `events` table had
no `registration` column — so **every registration was dropped at ingest** and
never reached the app you log into.

Secondary causes:

- `fr24/field_select.py` blanks `registration` when whole-image vs region OCR
  disagree (routed to review, never confirmed).
- `scripts/fr24_vision_ingest.py` used to checkpoint images even when extraction
  failed, so failed screenshots were never retried.

All three are addressed below.

## 1. Persisting registration (now fixed)

- The `events` table now carries `registration, callsign, aircraft_type,
  operator, origin_code, destination_code, altitude_ft, ground_speed_mph,
  flight_status, image_path`. Existing DBs are migrated automatically on backend
  boot and on `ingest_data.py` runs (`server/ingestion/migrations.py`).
- `ingest_fr24_csv` writes these fields and uses `ON CONFLICT(id) DO UPDATE`, so
  **re-ingesting backfills registration onto rows already stored** — no DB wipe.
- `/events` and `/alerts` return the new fields.

## 2. Recover already-missed registrations

```bash
# (a) Re-run vision extraction, reprocessing previously-failed screenshots
python3 scripts/fr24_vision_ingest.py --retry-errors

# (b) Re-ingest — backfills registration onto existing event rows
python3 server/ingestion/ingest_data.py --db server/priis.db

# (c) Reconcile against the registrations you know were seen
#     (a newline list or CSV with a `registration` column, e.g. from FR24)
python3 server/ingestion/reconcile_registrations.py \
    --known known_regs.csv --db server/priis.db
```

Reconciliation writes `outputs/registration_recovery_queue.csv` with two
categories:

- `ingest_gap` — in the FR24 CSV but not the DB → fixed by re-running ingest (b).
- `known_miss` — on your known list but never captured → re-scan screenshots
  (`--retry-errors`) or check FR24 directly. Each one also raises an alert.

Registrations are matched case/space/dash-insensitively (`N-5854 z` == `N5854Z`).

## 3. Registration watchlist alerts

Edit `config/registration_watchlist.yaml`:

```yaml
registrations:
  - registration: N5854Z
    label: PREPA powerline inspection
    expected_within_days: 14   # also alert if not seen within 14 days
  - registration: N767PD
    expected_within_days: 30
```

Two rules fire (written to the `alerts` table, `kind='aircraft'`):

- **"seen"** — the registration appears in ingested events.
- **"expected but missing"** — a registration with `expected_within_days` hasn't
  appeared inside that window.

Alerts run automatically at the end of `ingest_data.py`, or on demand:

```bash
python3 server/ingestion/registration_alerts.py --db server/priis.db
```

Deterministic alert ids (`REG-SEEN-{reg}-{date}` / `REG-MISS-{reg}-{date}`) dedupe
within a day, so re-running is safe.

## 4. External notification (optional)

New alerts are pushed to any channel configured via environment variables
(no-op if unset, so nothing leaves your environment until you opt in):

```bash
export ALERT_WEBHOOK_URL="https://hooks.slack.com/services/XXX"   # Slack-compatible
# or email:
export ALERT_EMAIL_TO="ops@example.com"
export ALERT_SMTP_HOST="smtp.example.com"
export ALERT_SMTP_PORT="587"
export ALERT_SMTP_USER="user"
export ALERT_SMTP_PASSWORD="secret"
```

See `server/notifications/notifier.py`.
