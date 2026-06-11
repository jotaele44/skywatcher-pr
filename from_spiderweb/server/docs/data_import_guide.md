# Data Import Guide

This guide explains how to import external data sources into PRIIS. By
default, the prototype includes a small set of sample records for
contracts, agencies, vendors, and sites. As you collect more data,
follow these steps to load it into the system.

## General Process

1. **Identify the source** – Determine whether the data is public
   (e.g., government procurement records), internal, or FOIA-based.
2. **Normalize field names** – Map source fields to the entity
   schemas defined in `contracts/`. Ensure consistent naming for
   IDs, amounts, dates, coordinates, etc.
3. **Validate against schemas** – Use a JSON Schema validator or
   Python tools (e.g., `pydantic` or `jsonschema`) to ensure each
   record conforms to the appropriate schema.
4. **Clean the data** – Remove or correct invalid entries, trim
   whitespace, deduplicate records, and convert data types.
5. **Load into staging tables** – Insert the cleaned data into
   staging tables in your database for auditing. Use `psql` or
   `COPY` commands for large datasets.
6. **Merge into production tables** – Write SQL or use SQLAlchemy to
   upsert records into the main tables (`agencies`, `vendors`,
   `sites`, `contracts`, etc.). Resolve references between
   entities, such as matching vendor names to IDs.
7. **Record provenance** – Log the source and timestamp of each
   record in a `sources` table. Assign evidence tiers (T1–T4) based
   on the reliability of the origin.

## Contract Data

For contract data, prepare a CSV with columns matching those used by
`ingestion/ingest_data.py`:

```
contract_id,vendor_id,agency_id,amount,start_date,end_date,description
C3,1,2,500000,2025-10-01,2026-09-30,Contract for infrastructure upgrades
```

Run the ingestion script:

```bash
python ingestion/ingest_data.py path/to/contract_data.csv --db $DATABASE_URL
```

## Geospatial Data

Site locations and infrastructure layers often come as GeoJSON,
shapefiles, or KML files. Use tools like [GDAL](https://gdal.org/)
or QGIS to convert them into a format usable by PostGIS. Example
commands:

```bash
# Convert a shapefile to GeoJSON
ogr2ogr -f GeoJSON sites.json input_sites.shp

# Load GeoJSON into PostGIS
ogr2ogr -f "PostgreSQL" PG:"dbname=priis user=user password=password" sites.json \
  -nln sites -append -progress
```

Ensure your data includes latitude and longitude fields or a
geometry column that can be transformed into WGS84 (SRID 4326).

## Evidence and Sources

When importing data, always capture metadata about the source:

- Source URI or file path
- Acquisition date
- Evidence tier (see `evidence_tiers.json`)
- A brief description or notes

Populate the `sources` table accordingly. This provenance information
allows analysts to trace findings back to original documents.

## Next Steps

- Build an automated ETL pipeline that performs validation,
  deduplication, and geocoding for new datasets.
- Extend the ingestion scripts to handle JSON, XML, or PDF inputs
  using OCR tools.
- Integrate with the retrieval layer so that newly imported records
  are automatically indexed for search and RAG.