"""
PostGIS schema definitions for GEO-PR-INT.

Tables:
  geo_pr_int_candidates  — ILAP candidates with unified scores
  geo_pr_int_corridors   — detected infrastructure corridors
  geo_pr_int_contracts   — normalised contract records

All geometry stored in EPSG:4326 (WGS-84).
"""

import logging
import os

logger = logging.getLogger(__name__)

CANDIDATES_TABLE = "geo_pr_int_candidates"
CORRIDORS_TABLE  = "geo_pr_int_corridors"
CONTRACTS_TABLE  = "geo_pr_int_contracts"


def _pg_url_from_settings() -> str:
    """Build PostgreSQL connection URL from SETTINGS or DATABASE_URL env var."""
    env_url = os.environ.get("DATABASE_URL", "")
    if env_url:
        return env_url

    from config import SETTINGS
    pg = SETTINGS.get("postgis", {})
    host     = pg.get("host", "localhost")
    port     = pg.get("port", 5432)
    database = pg.get("database", "geo_pr_int")
    user     = pg.get("user", "postgres")
    password = pg.get("password", "postgres")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def get_engine(url: str | None = None):
    """Return a SQLAlchemy engine; raises ImportError if sqlalchemy not installed."""
    from sqlalchemy import create_engine
    if url is None:
        url = _pg_url_from_settings()
    return create_engine(url, pool_pre_ping=True)


def create_tables(engine) -> None:
    """Create all GEO-PR-INT tables (PostGIS extension must already exist)."""
    from sqlalchemy import text

    ddl_candidates = f"""
    CREATE TABLE IF NOT EXISTS {CANDIDATES_TABLE} (
        id                    SERIAL PRIMARY KEY,
        lat                   DOUBLE PRECISION,
        lon                   DOUBLE PRECISION,
        geom                  GEOMETRY(Point, 4326),
        corridor_id           INTEGER DEFAULT 0,
        linearity_r2          DOUBLE PRECISION DEFAULT 0,
        bearing_deg           DOUBLE PRECISION DEFAULT 0,
        linear_corridor       BOOLEAN DEFAULT FALSE,
        ndvi_score            DOUBLE PRECISION DEFAULT 0,
        ndvi_anomaly          BOOLEAN DEFAULT FALSE,
        hydro_score           DOUBLE PRECISION DEFAULT 0,
        hydro_proximity_score DOUBLE PRECISION DEFAULT 0,
        karst_zone            BOOLEAN DEFAULT FALSE,
        contract_match_score  DOUBLE PRECISION DEFAULT 0,
        matched_contract_count INTEGER DEFAULT 0,
        total_obligated_amount DOUBLE PRECISION DEFAULT 0,
        nearest_contract_m    DOUBLE PRECISION DEFAULT 0,
        top_vendor            TEXT,
        contract_keywords     TEXT,
        unified_score         DOUBLE PRECISION DEFAULT 0,
        score_tier            TEXT DEFAULT 'LOW',
        unified_rank          INTEGER,
        classification        TEXT,
        infra_type            TEXT,
        infra_corridor        TEXT,
        infra_priority_score  DOUBLE PRECISION DEFAULT 0,
        infra_status          TEXT,
        flood_risk            DOUBLE PRECISION DEFAULT 0,
        routing_cost          DOUBLE PRECISION DEFAULT 0,
        physics_score         DOUBLE PRECISION DEFAULT 0,
        composite_score       DOUBLE PRECISION DEFAULT 0,
        sar_linear_score      DOUBLE PRECISION DEFAULT 0,
        ndvi_disturbance_score DOUBLE PRECISION DEFAULT 0,
        slope                 DOUBLE PRECISION DEFAULT 0,
        elevation_proxy       DOUBLE PRECISION DEFAULT 0,
        bathymetry_proxy      DOUBLE PRECISION DEFAULT 0,
        cluster               INTEGER DEFAULT -1,
        cluster_size          INTEGER DEFAULT 1,
        source_file           TEXT,
        acquisition_date      TEXT,
        created_at            TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_{CANDIDATES_TABLE}_geom
        ON {CANDIDATES_TABLE} USING GIST(geom);
    CREATE INDEX IF NOT EXISTS idx_{CANDIDATES_TABLE}_corridor_id
        ON {CANDIDATES_TABLE}(corridor_id);
    CREATE INDEX IF NOT EXISTS idx_{CANDIDATES_TABLE}_tier
        ON {CANDIDATES_TABLE}(score_tier);
    """

    ddl_corridors = f"""
    CREATE TABLE IF NOT EXISTS {CORRIDORS_TABLE} (
        corridor_id              INTEGER PRIMARY KEY,
        centroid_lat             DOUBLE PRECISION,
        centroid_lon             DOUBLE PRECISION,
        centroid_geom            GEOMETRY(Point, 4326),
        linearity_r2             DOUBLE PRECISION,
        bearing_deg              DOUBLE PRECISION,
        n_points                 INTEGER,
        dominant_infra_type      TEXT,
        mean_score               DOUBLE PRECISION,
        max_score                DOUBLE PRECISION,
        total_obligated_amount   DOUBLE PRECISION DEFAULT 0,
        matched_contract_count   INTEGER DEFAULT 0,
        bbox_wkt                 TEXT,
        created_at               TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_{CORRIDORS_TABLE}_centroid_geom
        ON {CORRIDORS_TABLE} USING GIST(centroid_geom);
    """

    ddl_contracts = f"""
    CREATE TABLE IF NOT EXISTS {CONTRACTS_TABLE} (
        id                          SERIAL PRIMARY KEY,
        award_id                    TEXT,
        recipient_name              TEXT,
        recipient_name_norm         TEXT,
        description                 TEXT,
        obligated_amount            DOUBLE PRECISION DEFAULT 0,
        award_date                  TEXT,
        fiscal_year                 INTEGER DEFAULT 0,
        place_of_performance_city   TEXT,
        place_of_performance_state  TEXT DEFAULT 'PR',
        awarding_agency_name        TEXT,
        naics_code                  TEXT,
        psc_code                    TEXT,
        lat                         DOUBLE PRECISION,
        lon                         DOUBLE PRECISION,
        geom                        GEOMETRY(Point, 4326),
        geocode_method              TEXT,
        matched_keywords            TEXT,
        created_at                  TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_{CONTRACTS_TABLE}_geom
        ON {CONTRACTS_TABLE} USING GIST(geom);
    CREATE INDEX IF NOT EXISTS idx_{CONTRACTS_TABLE}_recipient
        ON {CONTRACTS_TABLE}(recipient_name_norm);
    """

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
        conn.execute(text(ddl_candidates))
        conn.execute(text(ddl_corridors))
        conn.execute(text(ddl_contracts))

    logger.info(f"PostGIS tables created: {CANDIDATES_TABLE}, {CORRIDORS_TABLE}, {CONTRACTS_TABLE}")


def drop_tables(engine) -> None:
    """Drop all GEO-PR-INT tables."""
    from sqlalchemy import text
    with engine.begin() as conn:
        for tbl in [CANDIDATES_TABLE, CORRIDORS_TABLE, CONTRACTS_TABLE]:
            conn.execute(text(f"DROP TABLE IF EXISTS {tbl} CASCADE;"))
    logger.info("All GEO-PR-INT PostGIS tables dropped")


def postgis_available(engine) -> bool:
    """Return True if PostGIS extension is installed and reachable."""
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text("SELECT PostGIS_version();"))
            version = result.scalar()
            logger.debug(f"PostGIS version: {version}")
            return True
    except Exception as exc:
        logger.debug(f"PostGIS not available: {exc}")
        return False
