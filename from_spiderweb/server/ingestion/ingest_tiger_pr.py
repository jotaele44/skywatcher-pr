"""
ingest_tiger_pr.py — Download Census TIGER/Line shapefiles for Puerto Rico,
convert to MapLibre-ready GeoJSON, and spatial-join site points to the
municipio and tract GEOIDs they fall within.

Usage:
    pip install -r server/ingestion/requirements-geo.txt
    python server/ingestion/ingest_tiger_pr.py --dry-run
    python server/ingestion/ingest_tiger_pr.py            # default --year 2025
    python server/ingestion/ingest_tiger_pr.py --year 2024 --force

Outputs (repo-root paths):
    data/municipios.geojson      (78 features)
    data/tracts.geojson          (~945)
    data/places.geojson          (~250)
    data/barrios.geojson         (~900)
    data/tiger/{year}/manifest.json
    data/tiger/{year}/sites_unmatched.json   (only if any site fails sjoin)

The /geo/{layer}.geojson FastAPI route resolves these via _find_geojson in
server/backend/main.py (second candidate path: ROOT/"data").
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Heavy deps deferred to keep --help fast and surfaces clearer errors when
# requirements-geo.txt isn't installed.
try:
    import geopandas as gpd
    import pandas as pd
    import requests
    from shapely.geometry import Point
except ImportError as _err:  # pragma: no cover — guarded at runtime
    print(
        f"FATAL: missing dependency: {_err}\n"
        "Install:  pip install -r server/ingestion/requirements-geo.txt",
        file=sys.stderr,
    )
    raise SystemExit(2)

from migrations import run_all as run_migrations  # noqa: E402  (sibling import)

# ─── Constants ─────────────────────────────────────────────────────────────────

INGESTOR_VERSION = "1.0.0"
PR_STATEFP = "72"
DEFAULT_YEAR = 2025  # TIGER vintage default; 2024 supported via --year
TIGER_BASE = "https://www2.census.gov/geo/tiger/TIGER{year}"

# PR bbox tolerances (loose to catch valid points, reject swaps).
PR_BBOX_LON = (-68.0, -65.0)
PR_BBOX_LAT = (17.0, 19.0)

REPO_ROOT = Path(__file__).parent.parent.parent
DEFAULT_DB = Path(__file__).parent.parent / "priis.db"
DEFAULT_DATA_DIR = REPO_ROOT / "data"

# Layer registry. `archive` is the per-state filename; the COUNTY layer is
# nationwide and gets filtered by STATEFP=72 in-memory.
LAYER_SPECS: dict[str, dict[str, Any]] = {
    "municipios": {
        "archive_template": "COUNTY/tl_{year}_us_county.zip",
        "filter_statefp": True,
        "expected_min": 78,
        "expected_max": 78,           # PR's municipios are politically stable
        "simplify_tolerance_initial": 0.0,  # full precision for 78 features
        # TIGER municipios at full precision are ~3 MB raw / ~600 KB gzipped —
        # acceptable for a one-shot admin baselayer load. Budget set well above
        # the empirical 2025 size to leave headroom for future detail growth.
        "max_bytes": 6_000_000,
        # Oversize policy:
        #   "abort"         → raise; suggests a data-quality regression.
        #   "warn_continue" → keep writing the file but flag in manifest so
        #                     the frontend can default-off the layer.
        "on_oversize": "abort",
    },
    "tracts": {
        "archive_template": "TRACT/tl_{year}_72_tract.zip",
        "filter_statefp": False,
        "expected_min": 850,
        "expected_max": 1_100,
        "simplify_tolerance_initial": 0.0005,
        "max_bytes": 8_000_000,
        "on_oversize": "warn_continue",
    },
    "places": {
        "archive_template": "PLACE/tl_{year}_72_place.zip",
        "filter_statefp": False,
        "expected_min": 200,
        "expected_max": 350,
        "simplify_tolerance_initial": 0.0005,
        "max_bytes": 5_000_000,
        "on_oversize": "warn_continue",
    },
    "barrios": {
        "archive_template": "COUSUB/tl_{year}_72_cousub.zip",
        "filter_statefp": False,
        "expected_min": 800,
        "expected_max": 1_100,
        "simplify_tolerance_initial": 0.0005,
        "max_bytes": 10_000_000,
        "on_oversize": "warn_continue",
    },
}

# Properties retained on each output feature.
COMMON_PROPS = ["GEOID", "NAME", "NAMELSAD", "ALAND", "AWATER",
                "INTPTLAT", "INTPTLON"]
EXTRA_PROPS = {
    "tracts": ["COUNTYFP"],
    "barrios": ["COUNTYFP"],
}

# Simplification fallback ladder used when output exceeds size budget.
SIMPLIFY_LADDER = [0.0005, 0.001, 0.002]


# ─── Logging ───────────────────────────────────────────────────────────────────

log = logging.getLogger("ingest_tiger_pr")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


# ─── Retry helper (no tenacity dep) ───────────────────────────────────────────

def _with_retry(fn, *, attempts: int = 3, base_delay: float = 1.0):
    last_exc: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except (requests.RequestException, ConnectionError) as exc:
            last_exc = exc
            if attempt == attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            log.warning("attempt %d/%d failed: %s — retry in %.1fs",
                        attempt, attempts, exc, delay)
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


# ─── Download + cache + manifest ──────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _path_for_manifest(p: Path) -> str:
    """Render a path relative to the repo root when possible (cleaner for
    committed manifests), otherwise fall back to the absolute path. The
    latter happens during testing when cache/output dirs land in tmp_path.
    """
    try:
        return str(p.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(p.resolve())


def _download(url: str, dest: Path) -> None:
    def go():
        log.info("downloading %s", url)
        # connect=10s, read=180s — Census throughput on the 80 MB US-county
        # zip is bursty; a tighter read timeout flakes ~10% of fresh runs.
        with requests.get(url, timeout=(10, 180), stream=True) as r:
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            with tmp.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)
            tmp.replace(dest)
    _with_retry(go)


def _fetch_zip(layer: str, year: int, cache_dir: Path, force: bool) -> Path:
    spec = LAYER_SPECS[layer]
    url = TIGER_BASE.format(year=year) + "/" + spec["archive_template"].format(year=year)
    zip_path = cache_dir / Path(spec["archive_template"].format(year=year)).name
    if force or not zip_path.exists():
        _download(url, zip_path)
    return zip_path


# ─── GeoDataFrame pipeline ────────────────────────────────────────────────────

def _read_layer(zip_path: Path, *, filter_statefp: bool) -> "gpd.GeoDataFrame":
    """Read shapefile from zip via pyogrio, optionally filter to PR (STATEFP=72)."""
    gdf = gpd.read_file(f"zip://{zip_path}", engine="pyogrio")
    if filter_statefp:
        before = len(gdf)
        gdf = gdf[gdf["STATEFP"] == PR_STATEFP].copy()
        log.info("filtered STATEFP=72: %d → %d features", before, len(gdf))
    return gdf


def _repair_geometry(gdf: "gpd.GeoDataFrame") -> "gpd.GeoDataFrame":
    """Make geometries valid; drop empties and non-polygon types."""
    gdf = gdf.copy()
    gdf.geometry = gdf.geometry.make_valid()
    before = len(gdf)
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.geom_type.isin(
        ("Polygon", "MultiPolygon")
    )].copy()
    dropped = before - len(gdf)
    if dropped:
        log.warning("dropped %d invalid/non-polygon geometries", dropped)
    return gdf


def _check_count(layer: str, gdf: "gpd.GeoDataFrame") -> None:
    spec = LAYER_SPECS[layer]
    n = len(gdf)
    if not (spec["expected_min"] <= n <= spec["expected_max"]):
        raise RuntimeError(
            f"{layer}: feature count {n} outside expected range "
            f"[{spec['expected_min']}, {spec['expected_max']}] — Census may "
            f"have changed the shapefile. Investigate before proceeding."
        )
    log.info("%s: %d features (range OK)", layer, n)


def _project_to_wgs84(gdf: "gpd.GeoDataFrame") -> "gpd.GeoDataFrame":
    if gdf.crs is None:
        log.warning("input GeoDataFrame has no CRS — assuming EPSG:4269")
        gdf = gdf.set_crs(4269)
    return gdf.to_crs(4326)


def _trim_props(gdf: "gpd.GeoDataFrame", layer: str) -> "gpd.GeoDataFrame":
    keep = [c for c in COMMON_PROPS if c in gdf.columns]
    keep += [c for c in EXTRA_PROPS.get(layer, []) if c in gdf.columns]
    return gdf[keep + ["geometry"]].copy()


def _serialize_with_size_check(
    gdf: "gpd.GeoDataFrame", layer: str
) -> tuple[bytes, float, bool]:
    """Serialize to GeoJSON, simplifying as needed to stay under budget.

    Returns (bytes, applied_tolerance, oversized).

    If the budget can't be met after the simplification ladder, behavior is
    governed by spec['on_oversize']:
      - 'abort'         → raise RuntimeError (used for municipios, where an
                           oversize implies a real data-quality regression).
      - 'warn_continue' → log loudly, return the most-aggressive payload with
                           oversized=True. Callers should propagate the flag
                           into the manifest so the frontend can default-off
                           the layer until a CB display variant is wired in.
    """
    spec = LAYER_SPECS[layer]
    initial = spec["simplify_tolerance_initial"]
    candidates = [initial] if initial == 0.0 else SIMPLIFY_LADDER

    best_payload: Optional[bytes] = None
    best_tol = candidates[-1]
    best_size: Optional[int] = None
    for tol in candidates:
        working = gdf.copy()
        if tol > 0:
            working.geometry = working.geometry.simplify(
                tol, preserve_topology=True
            )
        payload = working.to_json(drop_id=True).encode("utf-8")
        size = len(payload)
        best_payload, best_tol, best_size = payload, tol, size
        if size <= spec["max_bytes"]:
            if tol > 0:
                log.info("%s: serialized at tolerance=%s (%d bytes ≤ %d)",
                         layer, tol, size, spec["max_bytes"])
            else:
                log.info("%s: serialized at full precision (%d bytes ≤ %d)",
                         layer, size, spec["max_bytes"])
            return payload, tol, False
        log.warning("%s: tolerance=%s produced %d bytes (over %d budget)",
                    layer, tol, size, spec["max_bytes"])

    # All candidates overshot.
    policy = spec.get("on_oversize", "abort")
    msg = (
        f"{layer}: GeoJSON still {best_size} bytes after most aggressive "
        f"simplification (tolerance {best_tol}). Budget is "
        f"{spec['max_bytes']} bytes."
    )
    if policy == "abort":
        raise RuntimeError(
            msg + " Consider switching this layer to a Cartographic "
            "Boundary File source (GENZ) — see plan."
        )
    log.error(
        "%s — keeping oversized payload because on_oversize='warn_continue'. "
        "Manifest will flag this layer; frontend should default-off and "
        "queue a CB display variant.",
        msg,
    )
    assert best_payload is not None
    return best_payload, best_tol, True


# ─── Site spatial join ────────────────────────────────────────────────────────

def _load_site_points(conn: sqlite3.Connection) -> tuple["gpd.GeoDataFrame", list[dict]]:
    """Load sites with non-null lat/lng inside the PR bbox.

    Returns (gdf, skipped) where skipped is a list of {id, name, reason} dicts.
    """
    rows = conn.execute(
        "SELECT id, name, lat, lng FROM sites"
    ).fetchall()
    valid: list[dict] = []
    skipped: list[dict] = []
    for r in rows:
        sid, name, lat, lng = r[0], r[1], r[2], r[3]
        if lat is None or lng is None:
            skipped.append({"id": sid, "name": name, "reason": "missing_lat_lng"})
            continue
        if not (PR_BBOX_LON[0] <= lng <= PR_BBOX_LON[1]):
            skipped.append({"id": sid, "name": name, "reason": "lng_out_of_pr_bbox",
                            "lng": lng, "lat": lat})
            continue
        if not (PR_BBOX_LAT[0] <= lat <= PR_BBOX_LAT[1]):
            skipped.append({"id": sid, "name": name, "reason": "lat_out_of_pr_bbox",
                            "lng": lng, "lat": lat})
            continue
        valid.append({"id": sid, "name": name, "geometry": Point(lng, lat)})

    if not valid:
        return gpd.GeoDataFrame(columns=["id", "name", "geometry"], crs=4326), skipped
    return gpd.GeoDataFrame(valid, crs=4326), skipped


def _sjoin_with_fallback(
    sites_gdf: "gpd.GeoDataFrame",
    polys: "gpd.GeoDataFrame",
    label: str,
) -> tuple[dict[str, str], list[dict]]:
    """Join site points to a polygon layer's GEOID.

    Tries predicate='within' first; for unmatched points retries with
    predicate='intersects'. Returns (site_id → GEOID, unmatched list).
    Resolves multi-hits by smallest-area polygon.
    """
    if sites_gdf.empty or polys.empty:
        return {}, [{"id": r["id"], "name": r["name"], "reason": f"empty_input_{label}"}
                    for _, r in sites_gdf.iterrows()]

    poly_view = polys[["GEOID", "geometry"]].copy()
    # Tie-break by polygon area on EPSG:6933 (equal-area cylindrical),
    # so values are in m² and area-based comparisons are meaningful.
    poly_view["_area"] = poly_view.to_crs("EPSG:6933").geometry.area

    matches: dict[str, str] = {}
    multi_hits: list[dict] = []

    def _join(predicate: str, subset: "gpd.GeoDataFrame") -> set[str]:
        if subset.empty:
            return set()
        joined = gpd.sjoin(subset, poly_view, predicate=predicate, how="left")
        hit_ids: set[str] = set()
        for sid, group in joined.groupby("id"):
            hits = group[group["GEOID"].notna()]
            if hits.empty:
                continue
            if len(hits) == 1:
                matches[sid] = str(hits.iloc[0]["GEOID"])
            else:
                # Smallest-area wins (most specific polygon)
                winner = hits.loc[hits["_area"].idxmin()]
                matches[sid] = str(winner["GEOID"])
                multi_hits.append({
                    "id": sid,
                    "layer": label,
                    "predicate": predicate,
                    "geoids": [str(g) for g in hits["GEOID"].tolist()],
                    "chosen": str(winner["GEOID"]),
                })
            hit_ids.add(sid)
        return hit_ids

    matched_within = _join("within", sites_gdf)
    remaining = sites_gdf[~sites_gdf["id"].isin(matched_within)]
    if not remaining.empty:
        log.info("%s: %d sites unmatched by 'within' — retry 'intersects'",
                 label, len(remaining))
        _join("intersects", remaining)

    unmatched_ids = set(sites_gdf["id"]) - set(matches.keys())
    unmatched = [
        {"id": sid,
         "name": sites_gdf.loc[sites_gdf["id"] == sid, "name"].iloc[0],
         "reason": f"no_polygon_match_{label}"}
        for sid in unmatched_ids
    ]

    if multi_hits:
        log.warning("%s: %d multi-hit sites resolved by smallest-area",
                    label, len(multi_hits))

    return matches, unmatched


# ─── DB updates ───────────────────────────────────────────────────────────────

def _apply_site_updates(
    conn: sqlite3.Connection,
    municipio_geoids: dict[str, str],
    tract_geoids: dict[str, str],
    *,
    dry_run: bool,
) -> int:
    """Set municipio_geoid + tract_geoid on every site row. Clears stale values
    for sites that no longer match. Returns count of UPDATEd rows.

    In dry_run mode, logs proposed updates and returns 0.
    """
    if dry_run:
        log.info("DRY-RUN: would clear all GEOIDs, then update %d municipio "
                 "+ %d tract entries",
                 len(municipio_geoids), len(tract_geoids))
        return 0

    site_ids = [r[0] for r in conn.execute("SELECT id FROM sites").fetchall()]
    cur = conn.cursor()
    cur.execute("BEGIN")
    try:
        cur.execute("UPDATE sites SET municipio_geoid = NULL, tract_geoid = NULL")
        updated = 0
        for sid in site_ids:
            m = municipio_geoids.get(sid)
            t = tract_geoids.get(sid)
            if m is None and t is None:
                continue
            cur.execute(
                "UPDATE sites SET municipio_geoid = ?, tract_geoid = ? WHERE id = ?",
                (m, t, sid),
            )
            updated += 1
        cur.execute("COMMIT")
        return updated
    except Exception:
        cur.execute("ROLLBACK")
        raise


# ─── Manifest ─────────────────────────────────────────────────────────────────

def _write_manifest(
    manifest_path: Path,
    year: int,
    entries: list[dict],
) -> None:
    manifest = {
        "ingestor": "ingest_tiger_pr.py",
        "ingestor_version": INGESTOR_VERSION,
        "year": year,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "layers": entries,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    log.info("manifest written: %s", manifest_path)


# ─── Orchestration ────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> int:
    _setup_logging(args.verbose)
    year = args.year
    cache_dir = (args.cache_dir or (REPO_ROOT / "data" / "tiger" / str(year))).resolve()
    out_dir = (args.data_dir or DEFAULT_DATA_DIR).resolve()
    db_path = (args.db or DEFAULT_DB).resolve()

    log.info("ingest_tiger_pr v%s | year=%d dry_run=%s force=%s",
             INGESTOR_VERSION, year, args.dry_run, args.force)
    log.info("cache_dir=%s  out_dir=%s  db=%s", cache_dir, out_dir, db_path)

    if not db_path.exists() and not args.dry_run:
        raise SystemExit(
            f"DB not found at {db_path}. Run seed_demo.py first, or pass --db."
        )

    cache_dir.mkdir(parents=True, exist_ok=True)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    manifest_entries: list[dict] = []
    geo_layers: dict[str, "gpd.GeoDataFrame"] = {}

    for layer in LAYER_SPECS:
        spec = LAYER_SPECS[layer]
        zip_path = _fetch_zip(layer, year, cache_dir, args.force)
        sha = _sha256(zip_path)
        size_zip = zip_path.stat().st_size

        gdf_raw = _read_layer(zip_path, filter_statefp=spec["filter_statefp"])
        gdf = _repair_geometry(gdf_raw)
        _check_count(layer, gdf)
        gdf = _project_to_wgs84(gdf)
        gdf = _trim_props(gdf, layer)

        # Override per-layer max if caller passed --max-bytes
        if args.max_bytes is not None:
            LAYER_SPECS[layer]["max_bytes"] = args.max_bytes

        payload, applied_tol, oversized = _serialize_with_size_check(gdf, layer)

        out_path = out_dir / f"{layer}.geojson"
        if not args.dry_run:
            out_path.write_bytes(payload)
            log.info("wrote %s (%d bytes)", out_path, len(payload))
        else:
            log.info("DRY-RUN: would write %s (%d bytes)", out_path, len(payload))

        # Keep the simplified geometry in-memory for sjoin only if it'd help —
        # but sjoin should use UN-simplified polygons for accuracy. Re-load the
        # full-precision gdf for the join step:
        geo_layers[layer] = gdf  # already trimmed but full precision for join

        manifest_entries.append({
            "layer": layer,
            "source": {
                "zip_path": _path_for_manifest(zip_path),
                "sha256": sha,
                "bytes": size_zip,
            },
            "output": {
                "path": _path_for_manifest(out_path),
                "sha256": _sha256_bytes(payload),
                "bytes": len(payload),
                "feature_count": int(len(gdf)),
                "applied_simplify_tolerance": applied_tol,
                "oversized_warning": oversized,
            },
        })

    # ─── Spatial join: sites → (municipios, tracts) ───
    log.info("opening DB %s", db_path)
    conn = sqlite3.connect(db_path) if db_path.exists() else None
    municipio_updates: dict[str, str] = {}
    tract_updates: dict[str, str] = {}
    unmatched_total: list[dict] = []

    if conn is not None:
        # Idempotent migration: required if DB pre-dates the schema change.
        run_migrations(conn)

        sites_gdf, skipped = _load_site_points(conn)
        log.info("loaded %d valid site points; skipped %d",
                 len(sites_gdf), len(skipped))
        unmatched_total.extend(skipped)

        municipio_updates, mu_unmatched = _sjoin_with_fallback(
            sites_gdf, geo_layers["municipios"], "municipios"
        )
        tract_updates, tr_unmatched = _sjoin_with_fallback(
            sites_gdf, geo_layers["tracts"], "tracts"
        )
        unmatched_total.extend(mu_unmatched)
        unmatched_total.extend(tr_unmatched)

        updated = _apply_site_updates(
            conn, municipio_updates, tract_updates, dry_run=args.dry_run
        )
        log.info("sites enriched: %d (dry_run=%s)", updated, args.dry_run)
        conn.close()
    else:
        log.warning("DB missing — skipping spatial join. (Run seed_demo.py first.)")

    # ─── Manifest + unmatched report ───
    manifest_path = cache_dir / "manifest.json"
    unmatched_path = cache_dir / "sites_unmatched.json"

    if not args.dry_run:
        _write_manifest(manifest_path, year, manifest_entries)
        if unmatched_total:
            unmatched_path.write_text(json.dumps(unmatched_total, indent=2))
            log.warning("%d unmatched / skipped sites — see %s",
                        len(unmatched_total), unmatched_path)
    else:
        log.info("DRY-RUN: would write manifest %s with %d layers",
                 manifest_path, len(manifest_entries))

    # ─── Summary line ───
    summary = {
        "year": year,
        "layers_written": [e["layer"] for e in manifest_entries],
        "sites_municipio_matched": len(municipio_updates),
        "sites_tract_matched": len(tract_updates),
        "sites_unmatched_or_skipped": len(unmatched_total),
        "dry_run": args.dry_run,
    }
    print(json.dumps(summary, indent=2))
    return 0


# ─── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Ingest TIGER/Line PR geographies into priis workbench."
    )
    p.add_argument("--year", type=int, default=DEFAULT_YEAR,
                   help=f"TIGER vintage (default {DEFAULT_YEAR})")
    p.add_argument("--db", type=Path, default=None,
                   help=f"SQLite DB path (default {DEFAULT_DB})")
    p.add_argument("--cache-dir", type=Path, default=None,
                   help="Zip cache dir (default data/tiger/{year})")
    p.add_argument("--data-dir", type=Path, default=None,
                   help=f"Output GeoJSON dir (default {DEFAULT_DATA_DIR})")
    p.add_argument("--force", action="store_true",
                   help="Re-download zips even if cached")
    p.add_argument("--dry-run", action="store_true",
                   help="Skip GeoJSON writes and DB mutations; log only.")
    p.add_argument("--max-bytes", type=int, default=None,
                   help="Override per-layer size budget (testing aid).")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
