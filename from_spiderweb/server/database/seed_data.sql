-- Sample seed data for PRIIS development. These inserts populate
-- agencies, vendors, sites, and contracts tables with a few rows.

INSERT INTO agencies (name, description) VALUES
  ('PR Agency X', 'Sample agency'),
  ('PR Agency Y', 'Another sample agency');

INSERT INTO vendors (name, description) VALUES
  ('ACME Corp', 'Sample vendor'),
  ('Globex Inc', 'Another vendor');

INSERT INTO sites (name, latitude, longitude, description) VALUES
  ('Site One', 18.4655, -66.1057, 'Sample site in San Juan'),
  ('Site Two', 18.2000, -66.5000, 'Sample site in Puerto Rico');

INSERT INTO contracts (contract_id, vendor_id, agency_id, amount, start_date, end_date, description) VALUES
  ('C1', 1, 1, 100000, '2025-01-01', '2025-12-31', 'Contract with ACME Corp'),
  ('C2', 2, 2, 250000, '2025-06-01', '2026-05-30', 'Contract with Globex Inc');