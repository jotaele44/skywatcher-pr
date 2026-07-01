from __future__ import annotations
import hashlib, shutil, zipfile
from pathlib import Path
import pandas as pd

TRACK_EXT = {".csv", ".kml", ".gpx"}
VISUAL_EXT = {".png", ".jpg", ".jpeg", ".pdf", ".mp4", ".mov"}
GIS_EXT = {".geojson", ".gpkg", ".shp", ".dbf", ".shx", ".prj", ".tif", ".tiff"}

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def classify(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in TRACK_EXT: return "track_candidate"
    if ext in VISUAL_EXT: return "visual_candidate"
    if ext in GIS_EXT: return "gis_context"
    if ext in {".py", ".md", ".json", ".yml", ".yaml"}: return "repo_or_config"
    return "other"

def extract_zips(input_dir: str, out_dir: str) -> Path:
    input_dir, out_dir = Path(input_dir), Path(out_dir)
    extract_dir = out_dir / "extracted"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    for z in sorted(input_dir.glob("*.zip")):
        target = extract_dir / z.stem.replace(" ", "_")
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(target)
    return extract_dir

def build_manifest(root: str) -> pd.DataFrame:
    rows = []
    root = Path(root)
    for p in root.rglob("*"):
        if p.is_file() and not p.name.startswith("._"):
            rows.append({
                "file_id": hashlib.md5(str(p).encode()).hexdigest()[:12],
                "path": str(p),
                "sha256": sha256_file(p),
                "size_bytes": p.stat().st_size,
                "extension": p.suffix.lower(),
                "source_zip": next((part for part in p.parts if part.endswith('.zip')), "extracted"),
                "role": classify(p),
            })
    return pd.DataFrame(rows)
