#!/usr/bin/env python3
"""Build the vendored sky catalog behind the Space-Track Sky Target Finder.

Inputs are pinned by URL and sha256 in data/reference/sky/sources.lock.json:
d3-celestial 0.7.35 (stars, star names, constellations, Messier; BSD-3-Clause),
OpenNGC v20260501 (Caldwell crosswalk authority and positions; CC BY-SA 4.0) and
the Stellarium v26.3 "modern" sky culture (star-name aliases; CC BY-SA 4.0). The
hand-reviewed crosswalks (caldwell_crosswalk.csv, messier_overrides.csv,
star_patches.csv) are frozen next to the outputs.

    python3 scripts/build_sky_catalog.py --fetch   # download pinned inputs to the cache
    python3 scripts/build_sky_catalog.py           # rebuild outputs from the cache only
    python3 scripts/build_sky_catalog.py --verify  # re-validate committed outputs offline

Every input is checked against its pinned sha256 before parsing, and the build
fails closed (non-zero exit) on any mismatch, missing object, out-of-tolerance
position or vocabulary violation instead of writing a partial catalog.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SKY_DIR = ROOT / "data" / "reference" / "sky"
LOCK_NAME = "sources.lock.json"
CATALOG_NAME = "sky_catalog.v1.json"
DEEP_NAME = "sky_stars_deep.v1.json"
DEFAULT_CACHE = Path.home() / ".cache" / "skywatcher-sky-catalog"

CATALOG_SCHEMA = "skywatcher.sky-catalog/v1"
DEEP_SCHEMA = "skywatcher.sky-stars-deep/v1"
MAX_OUTPUT_BYTES = 1_500_000
BASE_MAG_LIMIT = 6.0
DEEP_MAG_LIMIT = 7.5
POSITION_TOLERANCE_DEG = 0.3
MESSIER_TOLERANCE_DEG = 0.35

OBJECT_TYPES = frozenset(
    {
        "galaxy",
        "open_cluster",
        "globular_cluster",
        "cluster_with_nebula",
        "emission_nebula",
        "reflection_nebula",
        "planetary_nebula",
        "supernova_remnant",
        "dark_nebula",
        "star_cloud",
        "asterism",
        "double_star",
        "other",
    }
)

GREEK_NAMES = {
    "α": "Alpha", "β": "Beta", "γ": "Gamma", "δ": "Delta", "ε": "Epsilon", "ζ": "Zeta",
    "η": "Eta", "θ": "Theta", "ι": "Iota", "κ": "Kappa", "λ": "Lambda", "μ": "Mu",
    "ν": "Nu", "ξ": "Xi", "ο": "Omicron", "π": "Pi", "ρ": "Rho", "σ": "Sigma",
    "τ": "Tau", "υ": "Upsilon", "φ": "Phi", "χ": "Chi", "ψ": "Psi", "ω": "Omega",
}  # fmt: skip
_BAYER_RE = re.compile(r"^([α-ω]|[A-Za-z])(\d*)$")
_SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_OPENNGC_CONSTELLATION = {"Se1": "Ser", "Se2": "Ser"}


class _BuildError(Exception):
    """Raised when the build must fail closed."""


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_lock(sky_dir: Path) -> dict[str, dict[str, Any]]:
    lock = json.loads((sky_dir / LOCK_NAME).read_text(encoding="utf-8"))
    return {item["id"]: item for item in lock["inputs"]}


def _fetch(lock: dict[str, dict[str, Any]], cache_dir: Path) -> list[str]:
    errors: list[str] = []
    cache_dir.mkdir(parents=True, exist_ok=True)
    for item in lock.values():
        if not item.get("fetch", True):
            continue
        target = cache_dir / item["file"]
        if target.exists() and _sha256(target) == item["sha256"]:
            continue
        partial = target.with_suffix(target.suffix + ".part")
        request = urllib.request.Request(
            item["url"], headers={"User-Agent": "skywatcher-sky-catalog-builder"}
        )
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
        actual = _sha256(partial)
        if actual != item["sha256"]:
            partial.unlink()
            errors.append(f"{item['id']}: sha256 {actual} != pinned {item['sha256']}")
            continue
        partial.replace(target)
    return errors


def _read_input(lock: dict[str, dict[str, Any]], cache_dir: Path, input_id: str) -> bytes:
    item = lock[input_id]
    path = cache_dir / item["file"]
    if not path.exists():
        raise _BuildError(f"missing cached input {input_id} ({path}); run with --fetch")
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != item["sha256"]:
        raise _BuildError(f"{input_id}: sha256 {actual} != pinned {item['sha256']}")
    return data


def _json_input(lock: dict[str, dict[str, Any]], cache_dir: Path, input_id: str) -> Any:
    return json.loads(_read_input(lock, cache_dir, input_id).decode("utf-8"))


def _frozen_csv(path: Path) -> list[dict[str, str]]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    body = "\n".join(line for line in lines if not line.startswith("#"))
    return list(csv.DictReader(io.StringIO(body)))


def _openngc_rows(lock: dict[str, dict[str, Any]], cache_dir: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for input_id in ("openngc-ngc", "openngc-addendum"):
        text = _read_input(lock, cache_dir, input_id).decode("utf-8")
        for row in csv.DictReader(io.StringIO(text), delimiter=";"):
            rows[row["Name"]] = row
    return rows


# ---------------------------------------------------------------------------
# Geometry and formatting helpers
# ---------------------------------------------------------------------------


def _sexagesimal(value: str, *, hours: bool) -> float:
    text = value.strip()
    sign = -1.0 if text.startswith("-") else 1.0
    parts = [float(part) for part in text.lstrip("+-").split(":")]
    while len(parts) < 3:
        parts.append(0.0)
    degrees = parts[0] + parts[1] / 60.0 + parts[2] / 3600.0
    return sign * degrees * (15.0 if hours else 1.0)


def _separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    a1, d1, a2, d2 = (math.radians(v) for v in (ra1, dec1, ra2, dec2))
    cos_c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(a1 - a2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_c))))


def _ra(lon: float) -> float:
    return lon % 360.0


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "-":
        return None
    return float(text)


def _size(major: Any, minor: Any) -> list[float] | None:
    maj = _float_or_none(major)
    if maj is None:
        return None
    mnr = _float_or_none(minor)
    return [round(maj, 2), round(mnr if mnr is not None else maj, 2)]


def _d3_dim(dim: Any) -> list[float] | None:
    text = str(dim or "").strip()
    if not text:
        return None
    parts = text.lower().split("x")
    return _size(parts[0], parts[1] if len(parts) > 1 else None)


def _openngc_display(name: str) -> str:
    match = re.match(r"^(NGC|IC)0*(\d+)([A-Z]?)$", name)
    if match:
        return f"{match.group(1)} {int(match.group(2))}{match.group(3)}"
    return name


def _clean_aliases(values: list[str], *exclude: str | None) -> list[str]:
    skip = {value.casefold() for value in exclude if value}
    out: dict[str, str] = {}
    for value in values:
        text = " ".join(str(value).replace(" ", " ").split())
        if text and text.casefold() not in skip:
            out.setdefault(text.casefold(), text)
    return sorted(out.values(), key=lambda item: (item.casefold(), item))


def _serialize(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def _constellations(lock, cache_dir) -> tuple[list[dict[str, Any]], dict[str, str]]:
    features = _json_input(lock, cache_dir, "d3-constellations")["features"]
    seen: dict[str, dict[str, Any]] = {}
    for feature in features:
        cid = feature["id"]
        if cid in seen:
            if cid != "Ser":
                raise _BuildError(f"unexpected duplicate constellation id {cid}")
            continue
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"]
        seen[cid] = {
            "id": cid,
            "name": props["name"],
            "genitive": props["gen"],
            "label_ra_deg": round(_ra(lon), 3),
            "label_dec_deg": round(lat, 3),
        }
    if len(seen) != 88:
        raise _BuildError(f"expected 88 constellations, found {len(seen)}")
    ordered = [seen[key] for key in sorted(seen)]
    return ordered, {item["id"]: item["genitive"] for item in ordered}


def _constellation_lines(lock, cache_dir, known: dict[str, str]) -> list[dict[str, Any]]:
    merged: dict[str, list[list[list[float]]]] = {}
    for feature in _json_input(lock, cache_dir, "d3-constellation-lines")["features"]:
        cid = feature["id"]
        if cid not in known:
            raise _BuildError(f"constellation line for unknown id {cid}")
        lines = merged.setdefault(cid, [])
        for line in feature["geometry"]["coordinates"]:
            lines.append([[round(_ra(lon), 3), round(lat, 3)] for lon, lat in line])
    return [{"id": cid, "lines": merged[cid]} for cid in sorted(merged)]


def _stars(lock, cache_dir) -> list[list[float | int]]:
    rows = []
    for feature in _json_input(lock, cache_dir, "d3-stars-6")["features"]:
        hip = feature["id"]
        if not isinstance(hip, int):
            raise _BuildError(f"non-HIP star id {hip!r} in stars.6")
        mag = float(feature["properties"]["mag"])
        if mag > BASE_MAG_LIMIT:
            continue
        lon, lat = feature["geometry"]["coordinates"]
        rows.append([hip, round(_ra(lon), 4), round(lat, 4), round(mag, 2)])
    rows.sort(key=lambda row: (row[3], row[0]))
    return rows


def _star_label(bayer: str | None, flamsteed: str | None, genitive: str | None) -> str | None:
    if bayer and genitive:
        match = _BAYER_RE.match(bayer)
        if match is None:
            raise _BuildError(f"corrupt Bayer token {bayer!r}")
        letter, index = match.groups()
        return f"{GREEK_NAMES.get(letter, letter)}{index.translate(_SUPERSCRIPT)} {genitive}"
    if flamsteed and genitive:
        return f"{flamsteed} {genitive}"
    return None


def _star_names(lock, cache_dir, stars, genitives: dict[str, str]) -> dict[str, dict[str, Any]]:
    d3_names = _json_input(lock, cache_dir, "d3-starnames")
    stellarium = _json_input(lock, cache_dir, "stellarium-modern").get("common_names", {})
    patches = _frozen_csv(SKY_DIR / "star_patches.csv")
    for patch in patches:
        entry = d3_names.get(patch["hip"])
        if entry is None or patch["field"] not in ("bayer", "desig"):
            raise _BuildError(f"star patch does not apply: {patch}")
        entry[patch["field"]] = patch["value"]

    out: dict[str, dict[str, Any]] = {}
    for hip, *_ in stars:
        key = str(hip)
        d3 = d3_names.get(key, {})
        culture = [
            item["english"]
            for item in stellarium.get(f"HIP {hip}", [])
            if isinstance(item, dict) and item.get("english")
        ]
        name = (d3.get("name") or "").strip() or (culture[0] if culture else None)
        bayer = (d3.get("bayer") or "").strip() or None
        flamsteed = (d3.get("flam") or "").strip() or None
        if not (name or bayer or flamsteed):
            continue
        if bayer and _BAYER_RE.match(bayer) is None:
            raise _BuildError(f"HIP {hip}: corrupt Bayer token {bayer!r}")
        constellation = (d3.get("c") or "").strip() or None
        if constellation is not None and constellation not in genitives:
            constellation = None
        genitive = genitives.get(constellation) if constellation else None
        label = _star_label(bayer, flamsteed, genitive) or name or f"HIP {hip}"
        aliases = [*culture, f"HIP {hip}"]
        if name:
            aliases.append(name)
        if bayer and constellation:
            aliases.append(f"{bayer} {constellation}")
        if flamsteed and constellation:
            aliases.append(f"{flamsteed} {constellation}")
        hd = (d3.get("hd") or "").replace(" ", " ").strip()
        if hd:
            aliases.append(hd)
        out[key] = {
            "name": name,
            "bayer": bayer,
            "flamsteed": flamsteed,
            "constellation": constellation,
            "label": label,
            "aliases": _clean_aliases(aliases, label),
        }
    return out


def _messier(lock, cache_dir, openngc, genitives) -> list[dict[str, Any]]:
    features = {
        int(feature["id"][1:]): feature
        for feature in _json_input(lock, cache_dir, "d3-messier")["features"]
    }
    rows = {int(row["m"]): row for row in _frozen_csv(SKY_DIR / "messier_overrides.csv")}
    expected = set(range(1, 111))
    if set(features) != expected or set(rows) != expected:
        raise _BuildError("Messier set is not exactly M1..M110")
    out = []
    for number in sorted(expected):
        feature, row = features[number], rows[number]
        ngc_row = openngc.get(row["openngc_name"])
        if ngc_row is None or ngc_row["Type"] in ("Dup", "NonEx"):
            raise _BuildError(f"M{number}: OpenNGC row {row['openngc_name']} unusable")
        lon, lat = feature["geometry"]["coordinates"]
        ra, dec = _ra(lon), lat
        check = _separation(
            ra,
            dec,
            _sexagesimal(ngc_row["RA"], hours=True),
            _sexagesimal(ngc_row["Dec"], hours=False),
        )
        if check > MESSIER_TOLERANCE_DEG:
            raise _BuildError(f"M{number}: d3 vs OpenNGC separation {check:.3f} deg")
        constellation = _OPENNGC_CONSTELLATION.get(ngc_row["Const"], ngc_row["Const"])
        if constellation not in genitives:
            raise _BuildError(f"M{number}: unknown constellation {constellation}")
        if row["object_type"] not in OBJECT_TYPES:
            raise _BuildError(f"M{number}: object_type {row['object_type']!r}")
        props = feature["properties"]
        designation, long_designation = f"M {number}", f"Messier {number}"
        name = row["name"].strip() or None
        aliases = [alias for alias in row["aliases"].split("|") if alias]
        aliases.append(f"M{number}")
        out.append(
            {
                "id": f"messier:M{number}",
                "catalog": "messier",
                "number": number,
                "designation": designation,
                "long_designation": long_designation,
                "name": name,
                "aliases": _clean_aliases(aliases, designation, long_designation, name),
                "object_type": row["object_type"],
                "constellation": constellation,
                "magnitude": _float_or_none(props.get("mag")),
                "size_arcmin": _d3_dim(props.get("dim")),
                "ra_deg": round(ra, 4),
                "dec_deg": round(dec, 4),
            }
        )
    return out


def _caldwell(lock, cache_dir, openngc, genitives) -> list[dict[str, Any]]:
    rows = {int(row["c"]): row for row in _frozen_csv(SKY_DIR / "caldwell_crosswalk.csv")}
    expected = set(range(1, 110))
    if set(rows) != expected:
        raise _BuildError("Caldwell crosswalk is not exactly C1..C109")

    upstream: dict[int, str] = {}
    for row in openngc.values():
        tokens = [int(t) for t in re.findall(r"\bC (\d{3})\b", row.get("Identifiers") or "")]
        own = re.match(r"^C(\d{3})$", row["Name"])
        if own:
            tokens.append(int(own.group(1)))
        for number in tokens:
            if number in upstream and upstream[number] != row["Name"]:
                raise _BuildError(f"C{number}: OpenNGC maps it to two rows")
            upstream[number] = row["Name"]
    if set(upstream) != expected:
        raise _BuildError("OpenNGC Caldwell identifiers are not exactly C1..C109")

    d3 = {f["id"]: f for f in _json_input(lock, cache_dir, "d3-dsos-14")["features"]}
    out = []
    for number in sorted(expected):
        row = rows[number]
        if upstream[number] != row["openngc_name"]:
            raise _BuildError(
                f"C{number}: crosswalk row {row['openngc_name']} != OpenNGC {upstream[number]}"
            )
        ngc_row = openngc[row["openngc_name"]]
        if ngc_row["Type"] in ("Dup", "NonEx"):
            raise _BuildError(f"C{number}: OpenNGC row {row['openngc_name']} is {ngc_row['Type']}")
        if row["ra_override"]:
            ra, dec = float(row["ra_override"]), float(row["dec_override"])
        else:
            ra = _sexagesimal(ngc_row["RA"], hours=True)
            dec = _sexagesimal(ngc_row["Dec"], hours=False)
        checked = False
        if row["d3_id"]:
            feature = d3.get(row["d3_id"])
            if feature is None:
                raise _BuildError(f"C{number}: d3 id {row['d3_id']} missing upstream")
            lon, lat = feature["geometry"]["coordinates"]
            sep = _separation(ra, dec, _ra(lon), lat)
            if sep > POSITION_TOLERANCE_DEG:
                raise _BuildError(f"C{number}: {sep:.3f} deg from d3 {row['d3_id']}")
            checked = True
        if row["check_ra"]:
            sep = _separation(ra, dec, float(row["check_ra"]), float(row["check_dec"]))
            if sep > POSITION_TOLERANCE_DEG:
                raise _BuildError(f"C{number}: {sep:.3f} deg from frozen check position")
            checked = True
        if not checked:
            raise _BuildError(f"C{number}: no independent position check")
        constellation = _OPENNGC_CONSTELLATION.get(ngc_row["Const"], ngc_row["Const"])
        if constellation not in genitives:
            raise _BuildError(f"C{number}: unknown constellation {constellation}")
        if row["object_type"] not in OBJECT_TYPES:
            raise _BuildError(f"C{number}: object_type {row['object_type']!r}")
        designation, long_designation = f"C {number}", f"Caldwell {number}"
        name = row["name"].strip() or None
        aliases = [alias for alias in row["aliases"].split("|") if alias]
        aliases.extend(
            common.strip() for common in (ngc_row.get("Common names") or "").split(",")
        )
        if re.match(r"^(NGC|IC)\d", row["openngc_name"]):
            aliases.append(_openngc_display(row["openngc_name"]))
        if ngc_row.get("M"):
            aliases.append(f"M {int(ngc_row['M'])}")
        out.append(
            {
                "id": f"caldwell:C{number}",
                "catalog": "caldwell",
                "number": number,
                "designation": designation,
                "long_designation": long_designation,
                "name": name,
                "aliases": _clean_aliases(aliases, designation, long_designation, name),
                "object_type": row["object_type"],
                "constellation": constellation,
                "magnitude": _float_or_none(row["magnitude"]),
                "size_arcmin": _size(ngc_row.get("MajAx"), ngc_row.get("MinAx")),
                "ra_deg": round(ra, 4),
                "dec_deg": round(dec, 4),
            }
        )
    return out


def _deep_stars(lock, cache_dir) -> list[list[float]]:
    rows = []
    for feature in _json_input(lock, cache_dir, "d3-stars-8")["features"]:
        mag = float(feature["properties"]["mag"])
        if BASE_MAG_LIMIT < mag <= DEEP_MAG_LIMIT:
            lon, lat = feature["geometry"]["coordinates"]
            rows.append([round(_ra(lon), 3), round(lat, 3), round(mag, 2)])
    rows.sort(key=lambda row: (row[2], row[0], row[1]))
    return rows


def _build(cache_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes]]:
    lock = _load_lock(SKY_DIR)
    openngc = _openngc_rows(lock, cache_dir)
    constellations, genitives = _constellations(lock, cache_dir)
    stars = _stars(lock, cache_dir)
    catalog = {
        "schema_version": CATALOG_SCHEMA,
        "generated_by": "scripts/build_sky_catalog.py",
        "data_license": "CC-BY-SA-4.0",
        "attribution_file": "data/reference/sky/ATTRIBUTION.md",
        "sources": [
            {"id": "d3-celestial", "version": "0.7.35", "license": "BSD-3-Clause"},
            {"id": "openngc", "version": "v20260501", "license": "CC-BY-SA-4.0"},
            {"id": "stellarium-modern", "version": "v26.3", "license": "CC-BY-SA-4.0"},
        ],
        "constellations": constellations,
        "constellation_lines": _constellation_lines(lock, cache_dir, genitives),
        "stars": stars,
        "star_names": _star_names(lock, cache_dir, stars, genitives),
        "deep_sky": _messier(lock, cache_dir, openngc, genitives)
        + _caldwell(lock, cache_dir, openngc, genitives),
    }
    deep = {
        "schema_version": DEEP_SCHEMA,
        "mag_min_exclusive": BASE_MAG_LIMIT,
        "mag_max": DEEP_MAG_LIMIT,
        "stars": _deep_stars(lock, cache_dir),
    }
    licences = {
        item["copy_to"]: _read_input(lock, cache_dir, item["id"])
        for item in lock.values()
        if item.get("copy_to")
    }
    return catalog, deep, licences


# ---------------------------------------------------------------------------
# Verification (offline, committed outputs only)
# ---------------------------------------------------------------------------


def verify_outputs(directory: Path) -> list[str]:
    """Re-validate the committed catalog files; return a list of error strings."""
    errors: list[str] = []
    try:
        catalog_text = (directory / CATALOG_NAME).read_text(encoding="utf-8")
        deep_text = (directory / DEEP_NAME).read_text(encoding="utf-8")
        catalog = json.loads(catalog_text)
        deep = json.loads(deep_text)
    except (OSError, ValueError) as exc:
        return [f"cannot read outputs: {exc}"]

    if catalog.get("schema_version") != CATALOG_SCHEMA:
        errors.append("catalog schema_version mismatch")
    if deep.get("schema_version") != DEEP_SCHEMA:
        errors.append("deep-star schema_version mismatch")
    if _serialize(catalog) != catalog_text or _serialize(deep) != deep_text:
        errors.append("outputs are not in canonical serialization")
    size = len(catalog_text.encode("utf-8")) + len(deep_text.encode("utf-8"))
    if size >= MAX_OUTPUT_BYTES:
        errors.append(f"outputs total {size} bytes (limit {MAX_OUTPUT_BYTES})")

    deep_sky = catalog.get("deep_sky", [])
    ids = [item.get("id") for item in deep_sky]
    if len(ids) != len(set(ids)):
        errors.append("duplicate deep-sky ids")
    messier = {item["number"] for item in deep_sky if item.get("catalog") == "messier"}
    caldwell = {item["number"] for item in deep_sky if item.get("catalog") == "caldwell"}
    if messier != set(range(1, 111)):
        errors.append("Messier set is not exactly M1..M110")
    if caldwell != set(range(1, 110)):
        errors.append("Caldwell set is not exactly C1..C109")
    constellation_ids = {item["id"] for item in catalog.get("constellations", [])}
    for item in deep_sky:
        if item.get("object_type") not in OBJECT_TYPES:
            errors.append(f"{item.get('id')}: object_type {item.get('object_type')!r}")
        if item.get("constellation") not in constellation_ids:
            errors.append(f"{item.get('id')}: unknown constellation")
        if not (0.0 <= item.get("ra_deg", -1) < 360.0 and -90.0 <= item.get("dec_deg", 99) <= 90.0):
            errors.append(f"{item.get('id')}: position out of range")
    for hip, entry in catalog.get("star_names", {}).items():
        if entry.get("constellation") not in (None, *constellation_ids):
            errors.append(f"HIP {hip}: unknown constellation")
        bayer = entry.get("bayer")
        if bayer is not None and _BAYER_RE.match(bayer) is None:
            errors.append(f"HIP {hip}: corrupt Bayer token {bayer!r}")
    for text in _walk_strings(catalog):
        if "undefined" in text.lower():
            errors.append(f"string contains 'undefined': {text!r}")
            break

    c33 = next((item for item in deep_sky if item.get("id") == "caldwell:C33"), None)
    if c33 is None or _separation(c33["ra_deg"], c33["dec_deg"], 314.0795, 31.7428) > 0.01:
        errors.append("C33 is not at (314.0795, 31.7428)")
    elif c33.get("name") != "East Veil Nebula":
        errors.append("C33 is not named East Veil Nebula")
    names = catalog.get("star_names", {})
    if names.get("102488", {}).get("label") != "Epsilon Cygni":
        errors.append("HIP 102488 is not labelled Epsilon Cygni")
    if not any("Marfak-East" in alias for alias in names.get("5542", {}).get("aliases", [])):
        errors.append("HIP 5542 is missing the Marfak-East alias")
    if any(not (BASE_MAG_LIMIT < row[2] <= DEEP_MAG_LIMIT) for row in deep.get("stars", [])):
        errors.append("deep-star layer outside its magnitude band")
    if any(row[3] > BASE_MAG_LIMIT for row in catalog.get("stars", [])):
        errors.append("base star layer exceeds its magnitude limit")
    return errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Fetch, build or verify the vendored sky catalog."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fetch", action="store_true", help="download pinned inputs first")
    parser.add_argument("--verify", action="store_true", help="validate committed outputs only")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args(argv)

    if args.verify:
        errors = verify_outputs(SKY_DIR)
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        print("sky catalog verify: " + ("FAIL" if errors else "PASS"))
        return 1 if errors else 0

    if args.fetch:
        errors = _fetch(_load_lock(SKY_DIR), args.cache_dir)
        if errors:
            for error in errors:
                print(f"FAIL {error}", file=sys.stderr)
            return 1

    try:
        catalog, deep, licences = _build(args.cache_dir)
    except _BuildError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1

    staged = {CATALOG_NAME: _serialize(catalog), DEEP_NAME: _serialize(deep)}
    size = sum(len(text.encode("utf-8")) for text in staged.values())
    # Verify the staged outputs before anything in data/reference/sky is replaced.
    with tempfile.TemporaryDirectory() as staging:
        for name, text in staged.items():
            (Path(staging) / name).write_text(text, encoding="utf-8")
        errors = verify_outputs(Path(staging))
    if errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        return 1
    for name, text in staged.items():
        (SKY_DIR / name).write_text(text, encoding="utf-8")
    for name, data in licences.items():
        (SKY_DIR / name).write_bytes(data)
    deep_sky = catalog["deep_sky"]
    print(
        f"sky catalog: stars={len(catalog['stars'])} named={len(catalog['star_names'])} "
        f"deep_stars={len(deep['stars'])} messier="
        f"{sum(1 for i in deep_sky if i['catalog'] == 'messier')} caldwell="
        f"{sum(1 for i in deep_sky if i['catalog'] == 'caldwell')} bytes={size}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
