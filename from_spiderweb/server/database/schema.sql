-- SQL schema for PRIIS entities.
-- This file defines tables for agencies, vendors, sites, contracts,
-- anomalies, events, sources, and findings. Use `psql` or a migration
-- tool to apply these definitions to your PostgreSQL/PostGIS database.

CREATE TABLE IF NOT EXISTS agencies (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS vendors (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS sites (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    latitude DECIMAL(10, 6),
    longitude DECIMAL(10, 6),
    description TEXT
);

CREATE TABLE IF NOT EXISTS contracts (
    id SERIAL PRIMARY KEY,
    contract_id TEXT UNIQUE,
    vendor_id INTEGER REFERENCES vendors(id),
    agency_id INTEGER REFERENCES agencies(id),
    amount NUMERIC,
    start_date DATE,
    end_date DATE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS anomalies (
    id SERIAL PRIMARY KEY,
    type TEXT,
    description TEXT,
    details JSONB
);

CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    site_id INTEGER REFERENCES sites(id),
    name TEXT,
    event_timestamp TIMESTAMP,
    description TEXT
);

CREATE TABLE IF NOT EXISTS sources (
    id SERIAL PRIMARY KEY,
    type TEXT,
    uri TEXT,
    tier SMALLINT,
    description TEXT
);

CREATE TABLE IF NOT EXISTS findings (
    id SERIAL PRIMARY KEY,
    anomaly_id INTEGER REFERENCES anomalies(id),
    confidence SMALLINT,
    description TEXT
);