"""
seed_demo.py — Populate priis.db with the V1 demo dataset.

Run from the repo root:
    python server/ingestion/seed_demo.py

Creates server/priis.db (via schema_sqlite.sql) and inserts the canonical
demo records that mirror the V1 frontend mock data.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from migrations import run_all as run_migrations  # noqa: E402  (sibling import)

ROOT = Path(__file__).parent.parent.parent
SCHEMA = Path(__file__).parent.parent / "database" / "schema_sqlite.sql"
DB = Path(__file__).parent.parent / "priis.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text())
    conn.commit()


def seed(conn: sqlite3.Connection) -> None:
    agencies = [
        ("AG-001", "PRASA",  "Puerto Rico Aqueduct & Sewer Authority"),
        ("AG-002", "PREPA",  "Puerto Rico Electric Power Authority"),
        ("AG-003", "COR3",   "Central Office for Recovery & Reconstruction"),
        ("AG-004", "AAFAF",  "Fiscal Agency & Financial Advisory Authority"),
        ("AG-005", "DTOP",   "Dept. of Transportation & Public Works"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO agencies (id, code, name) VALUES (?,?,?)", agencies
    )

    vendors = [
        ("V-1024", "Caribe Civil Works LLC",       0.82, "T2"),
        ("V-2071", "Atlantica Infrastructure Corp", 0.74, "T2"),
        ("V-1188", "Borinquen Logistics Group",     0.41, "T2"),
        ("V-3340", "Cordillera Engineering S.E.",   0.66, "T2"),
        ("V-1502", "Sargasso Marine Services",      0.58, "T2"),
        ("V-4012", "Vega Telecom Partners",         0.71, "T2"),
        ("V-3771", "Coastal Power Solutions LLC",   0.69, "T2"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO vendors (id, name, risk, tier) VALUES (?,?,?,?)", vendors
    )

    sites = [
        ("S-001", "Roosevelt Roads — Ceiba",  "former-naval-station", 18.246, -65.62,  1, "military_adjacent"),
        ("S-002", "Punta Salinas Radar",       "radar",               18.466, -66.22,  1, "other"),
        ("S-003", "PRASA Caguas WTP",          "water-treatment",     18.23,  -66.04,  0, "water"),
        ("S-004", "Aguadilla — Rafael Hernández","airport",           18.495, -67.13,  0, "airport"),
        ("S-005", "Ponce — Mercedita",         "airport",             18.008, -66.563, 0, "airport"),
        ("S-006", "Aguirre Power Complex",     "power-plant",         17.953, -66.22,  0, "power"),
        ("S-007", "Yabucoa Oil Terminal",      "terminal",            18.058, -65.836, 0, "port"),
        ("S-008", "Toa Baja PRASA Pump 4",     "water-pumping",       18.443, -66.26,  0, "water"),
        ("S-009", "Cabo Rojo Telecom Tower",   "telecom",             17.985, -67.155, 0, "telecom"),
        ("S-010", "Vieques Western Reserve",   "former-military",     18.118, -65.56,  1, "military_adjacent"),
        ("S-011", "San Juan Port — Pier 15",   "port",                18.46,  -66.106, 0, "port"),
        ("S-012", "Arecibo Substation N-3",    "substation",          18.46,  -66.715, 0, "power"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO sites (id, name, kind, lat, lng, sensitive, infrastructure_class) "
        "VALUES (?,?,?,?,?,?,?)",
        sites,
    )

    contracts = [
        ("C-9241", "AG-001", "V-1024", "S-008", 12400000, "2024-03-11", "executed", "T2", "Emergency pump rehab — sole source.", "sole_source"),
        ("C-9301", "AG-003", "V-1024", "S-001", 24780000, "2024-05-02", "executed", "T2", "Site clearing + perimeter works.", "emergency"),
        ("C-9382", "AG-003", "V-2071", "S-001", 18300000, "2024-06-19", "amended",  "T2", "Amend +2 — scope expansion, unspecified.", "amendment"),
        ("C-9421", "AG-002", "V-3771", "S-012",  6750000, "2024-07-14", "executed", "T2", None, None),
        ("C-9555", "AG-005", "V-1188", "S-004",  9640000, "2024-09-29", "amended",  "T2", "Cargo apron resurfacing — no-bid.", "sole_source"),
        ("C-9620", "AG-003", "V-1024", "S-010", 31200000, "2024-10-22", "flagged",  "T2", "Disposal & clearing — concealed access road.", None),
        ("C-9802", "AG-003", "V-2071", "S-001", 14950000, "2025-01-17", "flagged",  "T2", "Third amendment — no project closeout.", None),
        ("C-9920", "AG-003", "V-1024", "S-010", 19800000, "2025-03-01", "flagged",  "T2", "Continuation works — Vieques W. Reserve.", None),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO contracts "
        "(id, agency, vendor, site, amount, signed, status, tier, note, procurement_method) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        contracts,
    )

    events = [
        ("E-001", "contract", "2024-05-02", "S-001", "C-9301", "C-9301 signed",                "T2"),
        ("E-002", "contract", "2024-06-19", "S-001", "C-9382", "C-9382 amend",                 "T2"),
        ("E-003", "imagery",  "2024-08-12", "S-001", None,     "New clearing — 4.1 ha",        "T1"),
        ("E-004", "flight",   "2024-08-14", "S-001", None,     "Unscheduled C-130 loiter",     "T1"),
        ("E-005", "report",   "2024-08-17", "S-001", None,     "Local sighting — Ceiba",       "T3"),
        ("E-006", "contract", "2024-10-22", "S-010", "C-9620", "C-9620 signed",                "T2"),
        ("E-007", "imagery",  "2024-11-04", "S-010", None,     "Access road extended",         "T1"),
        ("E-008", "flight",   "2024-11-07", "S-010", None,     "Rotary-wing approach",         "T1"),
        ("E-009", "outage",   "2024-11-07", "S-010", None,     "Local grid outage 32m",        "T2"),
        ("E-011", "imagery",  "2025-02-22", "S-010", None,     "Concrete pad — 18×24m",        "T1"),
        ("E-012", "report",   "2025-02-25", "S-010", None,     "Witness — light formation",    "T3"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO events (id, kind, at, site_id, ref_id, label, tier) "
        "VALUES (?,?,?,?,?,?,?)",
        events,
    )

    anomalies = [
        (
            "A-014",
            "Ceiba contract concentration with imagery + flight overlap",
            "cross-domain", 0.91, "hi", "S-001",
            "Four awards to two vendors converge on Roosevelt Roads inside a 9-month window. "
            "Imagery shows new clearing near the contract-amendment window; flight activity and "
            "a local report appear in the same period.",
            json.dumps([
                {"tag": "finance",   "note": "Vendor concentration across linked awards"},
                {"tag": "spatial",   "note": "Contracts converge near sensitive infrastructure"},
                {"tag": "temporal",  "note": "Imagery and flight events cluster inside one week"},
                {"tag": "report",    "note": "One T3 local report remains uncorroborated"},
            ]),
            json.dumps(["C-9301", "C-9382", "C-9802"]),
            json.dumps(["E-001", "E-002", "E-003", "E-004", "E-005"]),
            3,
            json.dumps(["Witness date and technical-event date do not fully align; keep T3 claim as lead only."]),
        ),
        (
            "A-021",
            "Vieques amendment cluster + grid outage",
            "infrastructure", 0.84, "hi", "S-010",
            "Two awards converge on Vieques western reserve with imagery, flight, and outage "
            "events in close sequence. Pattern is operationally significant but not dispositive "
            "without additional records.",
            json.dumps([
                {"tag": "finance", "note": "Large vendor concentration on restricted-adjacent site"},
                {"tag": "infra",   "note": "New construction signature needs permit reconciliation"},
                {"tag": "temporal","note": "Outage and approach event share date"},
            ]),
            json.dumps(["C-9620", "C-9920"]),
            json.dumps(["E-006", "E-007", "E-008", "E-009", "E-011", "E-012"]),
            3,
            json.dumps([]),
        ),
        (
            "A-029",
            "Aguadilla apron resurfacing — no-bid",
            "financial", 0.62, "md", "S-004",
            "Single sole-source award for apron resurfacing at Rafael Hernández airport with "
            "no competitive procurement and an amendment in progress.",
            json.dumps([
                {"tag": "finance", "note": "No-bid award above threshold"},
                {"tag": "source",  "note": "Missing permit documentation"},
            ]),
            json.dumps(["C-9555"]),
            json.dumps([]),
            2,
            json.dumps([]),
        ),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO anomalies "
        "(id, title, category, score, band, site_id, summary, factors, contracts, event_ids, confidence, contradictions) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        anomalies,
    )

    sources = [
        ("SRC-01", "FR24 Flight Archive",      "T1", "technical",    "online"),
        ("SRC-02", "USASPENDING Contracts",    "T2", "operational",  "online"),
        ("SRC-03", "Sentinel-2 Imagery",       "T1", "technical",    "online"),
        ("SRC-04", "GEBCO Bathymetry",         "T1", "technical",    "online"),
        ("SRC-05", "Reddit UAP/UFO PR",        "T3", "eyewitness",   "online"),
        ("SRC-06", "FEMA Contract DB",         "T2", "operational",  "partial"),
        ("SRC-07", "PR DTOP Permits",          "T2", "operational",  "offline"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO sources (id, name, tier, kind, status) VALUES (?,?,?,?,?)",
        sources,
    )

    investigations = [
        ("INV-007", "Roosevelt Roads Contractor Activity",    "COR3 vendor concentration + imagery", "active"),
        ("INV-012", "Vieques Construction Pattern",          "Amendment cluster + flight overlay",   "active"),
        ("INV-019", "Aguadilla Airport No-Bid Awards",       "DTOP sole-source procurement",         "needs_review"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO investigations (id, title, active_vector, status) VALUES (?,?,?,?)",
        investigations,
    )

    alerts = [
        ("ALT-001", "2025-03-01", "finance",  "New flagged contract C-9920",         "T2", "INV-012"),
        ("ALT-002", "2025-02-22", "spatial",  "Imagery: new pad S-010",              "T1", "INV-012"),
        ("ALT-003", "2025-01-17", "finance",  "C-9802 third amendment — no closeout","T2", "INV-007"),
        ("ALT-004", "2024-11-07", "anomaly",  "A-021 score updated to 0.84",         "T1", "INV-012"),
        ("ALT-005", "2024-09-29", "source",   "PR DTOP Permits offline",             "T4", None),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO alerts (id, at, kind, title, tier, investigation) VALUES (?,?,?,?,?,?)",
        alerts,
    )

    conn.commit()
    print(f"Seeded demo data into {DB}")


def main() -> None:
    conn = _conn()
    init_schema(conn)
    migration_result = run_migrations(conn)
    print(f"Migrations applied: {migration_result}")
    seed(conn)
    conn.close()


if __name__ == "__main__":
    main()
