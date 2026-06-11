# Data Ingestion

The `ingestion` package contains scripts for loading external data into
the PRIIS database. As of this version the primary focus is on
contracts, but the same pattern can be extended to other entities.

## Ingesting Contracts

Use the `ingest_data.py` script to load contract records from a CSV
file into the `contracts` table. The CSV should include the
following columns:

- `contract_id`: A unique identifier for the contract (e.g., "C3").
- `vendor_id`: The numeric ID of the vendor as stored in the `vendors` table.
- `agency_id`: The numeric ID of the awarding agency as stored in the `agencies` table.
- `amount`: The monetary value of the contract.
- `start_date`: ISO date string for when the contract begins.
- `end_date`: ISO date string for when the contract ends.
- `description` (optional): Free-text description of the contract.

Run the ingestion script like this:

```bash
python ingestion/ingest_data.py path/to/contracts.csv --db postgresql://user:password@localhost:5432/priis
```

If the `--db` flag is omitted, the script looks for a `DATABASE_URL`
environment variable or falls back to a local default. The script
uses `ON CONFLICT DO NOTHING` on the `contract_id` column to avoid
duplicates.

## Extending Ingestion

To ingest other types of entities (such as sites, anomalies, or
events), create additional functions in `ingest_data.py` or
separate modules. Use SQLAlchemy to define the table mappings and
conflict resolution logic. Share common helpers for reading files,
parsing dates, and validating data.