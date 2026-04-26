"""
File-based cache manager for GEO-PR-INT.

Provides CSV and GeoJSON persistence for all pipeline outputs so that
the pipeline can resume without re-fetching remote data.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import SETTINGS, GEO_PR_INT_ROOT

logger = logging.getLogger(__name__)

_OUTPUT = SETTINGS["output"]
_CACHE_ROOT = GEO_PR_INT_ROOT / _OUTPUT.get("cache_dir", "data/cache")
_CSV_ROOT   = GEO_PR_INT_ROOT / _OUTPUT.get("csv_dir", "outputs/csv")
_GJ_ROOT    = GEO_PR_INT_ROOT / _OUTPUT.get("geojson_dir", "outputs/geojson")
_TS_FILE    = _CACHE_ROOT / ".last_run"


class CacheManager:
    """Manages CSV and GeoJSON outputs for GEO-PR-INT pipeline."""

    def __init__(self, root: Path | None = None):
        self.root     = Path(root) if root else _CSV_ROOT
        self.gj_root  = _GJ_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        self.gj_root.mkdir(parents=True, exist_ok=True)

    # ── CSV helpers ──────────────────────────────────────────────────────────

    def _csv_path(self, name: str) -> Path:
        return self.root / f"{name}.csv"

    def _save_csv(self, df: pd.DataFrame, name: str) -> Path:
        path = self._csv_path(name)
        df.to_csv(path, index=False)
        logger.info(f"Cache: saved {len(df)} rows → {path}")
        return path

    def _load_csv(self, name: str) -> pd.DataFrame | None:
        path = self._csv_path(name)
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path, low_memory=False)
            logger.info(f"Cache: loaded {len(df)} rows from {path}")
            return df
        except Exception as exc:
            logger.warning(f"Cache read failed ({path}): {exc}")
            return None

    # ── Candidates ───────────────────────────────────────────────────────────

    def save_candidates(self, df: pd.DataFrame) -> Path:
        return self._save_csv(df, "candidates")

    def load_candidates(self) -> pd.DataFrame | None:
        return self._load_csv("candidates")

    # ── Corridors ────────────────────────────────────────────────────────────

    def save_corridors(self, df: pd.DataFrame) -> Path:
        return self._save_csv(df, "corridors")

    def load_corridors(self) -> pd.DataFrame | None:
        return self._load_csv("corridors")

    # ── Contracts ────────────────────────────────────────────────────────────

    def save_contracts(self, df: pd.DataFrame) -> Path:
        return self._save_csv(df, "contracts")

    def load_contracts(self) -> pd.DataFrame | None:
        return self._load_csv("contracts")

    # ── GeoJSON ──────────────────────────────────────────────────────────────

    def _gj_path(self, name: str) -> Path:
        return self.gj_root / f"{name}.geojson"

    def save_geojson(self, data: dict, name: str) -> Path:
        path = self._gj_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        logger.info(f"Cache: saved GeoJSON → {path}")
        return path

    def load_geojson(self, name: str) -> dict | None:
        path = self._gj_path(name)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:
            logger.warning(f"GeoJSON read failed ({path}): {exc}")
            return None

    def cache_exists(self, name: str) -> bool:
        return self._csv_path(name).exists() or self._gj_path(name).exists()

    def clear_cache(self) -> None:
        """Delete all CSV and GeoJSON files managed by this instance."""
        for p in self.root.glob("*.csv"):
            p.unlink(missing_ok=True)
        for p in self.gj_root.glob("*.geojson"):
            p.unlink(missing_ok=True)
        logger.info("Cache cleared")

    # ── Timestamp helpers ────────────────────────────────────────────────────

    @staticmethod
    def get_last_run_timestamp() -> str | None:
        """Return ISO timestamp of last successful pipeline run, or None."""
        if _TS_FILE.exists():
            try:
                return _TS_FILE.read_text().strip()
            except Exception:
                pass
        return None

    @staticmethod
    def set_last_run_timestamp() -> None:
        """Record current UTC time as the last-run timestamp."""
        _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().isoformat()
        _TS_FILE.write_text(ts)
        logger.debug(f"Last-run timestamp: {ts}")

    # ── Convenience export helpers ────────────────────────────────────────────

    def export_candidates_geojson(self, df: pd.DataFrame) -> Path:
        """Convert candidates DataFrame to GeoJSON FeatureCollection and save."""
        features = []
        for _, row in df.iterrows():
            lat = row.get("lat")
            lon = row.get("lon")
            if pd.isna(lat) or pd.isna(lon):
                continue
            props = {k: (v if not isinstance(v, float) or not pd.isna(v) else None)
                     for k, v in row.items() if k not in ("lat", "lon")}
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                "properties": props,
            })
        fc = {"type": "FeatureCollection", "features": features}
        return self.save_geojson(fc, "candidates")

    def export_corridors_geojson(self, corridors_df: pd.DataFrame) -> Path:
        """Convert corridors DataFrame to GeoJSON FeatureCollection and save."""
        features = []
        for _, row in corridors_df.iterrows():
            lat = row.get("centroid_lat") or row.get("lat")
            lon = row.get("centroid_lon") or row.get("lon")
            if pd.isna(lat) or pd.isna(lon):
                continue
            props = {k: (v if not isinstance(v, float) or not pd.isna(v) else None)
                     for k, v in row.items()
                     if k not in ("centroid_lat", "centroid_lon", "lat", "lon")}
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                "properties": props,
            })
        fc = {"type": "FeatureCollection", "features": features}
        return self.save_geojson(fc, "corridors")
