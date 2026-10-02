"""CLI for NOAA Maria 2017 dataset discovery and bounded certified fetch."""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path
from urllib.request import Request, urlopen

from scripts.source_adapters.noaa_maria_2017.adapter import (
    EXPECTED_STAC_ITEM_COUNT,
    PILOT_ITEM_ID,
    STAC_ITEM_COLLECTION_URL,
    URL_LIST_URL,
    build_dry_run_plan,
    build_payload_request,
    discover_from_documents,
)
from scripts.source_adapters.sdk import AdapterPolicy, CertifiedFetchEngine, ManifestEngine


def _read_url(url: str, timeout: int = 120) -> bytes:
    req = Request(url, headers={"User-Agent": "skywatcher-pr-noaa-maria-adapter/1.0"})
    with urlopen(req, timeout=timeout) as response:  # noqa: S310 - fixed NOAA public catalog URLs
        return response.read()


def _policy(root: Path) -> AdapterPolicy:
    return AdapterPolicy(
        raw_payload_root=root / "raw",
        manifest_root=root / "manifests",
        staging_root=root / "staging",
        cache_root=root / "cache",
    )


def discover(output_root: Path) -> int:
    url_text = _read_url(URL_LIST_URL).decode("utf-8")
    stac_bytes = _read_url(STAC_ITEM_COLLECTION_URL)
    denominator, items = discover_from_documents(url_text, stac_bytes)
    output_root.mkdir(parents=True, exist_ok=True)
    rows = [item.to_manifest_row() for item in items]
    with (output_root / "item_denominator.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "tif_count": len(denominator.tif_urls),
        "stac_item_count": len(items),
        "other_url_count": len(denominator.other_urls),
        "time_contradiction_count": sum(1 for item in items if item.time_state == "CONTRADICTION_TIME"),
        "source_lineage_count": len({item.source_lineage_id for item in items}),
        "pilot_item_id": PILOT_ITEM_ID,
    }
    (output_root / "denominator_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    assert summary["tif_count"] == EXPECTED_STAC_ITEM_COUNT
    return 0


def dry_run(output_root: Path, item_ids: list[str]) -> int:
    url_text = _read_url(URL_LIST_URL).decode("utf-8")
    stac_bytes = _read_url(STAC_ITEM_COLLECTION_URL)
    _, items = discover_from_documents(url_text, stac_bytes)
    selected = set(item_ids) if item_ids else {PILOT_ITEM_ID}
    plan = build_dry_run_plan(items, selected)
    if len(plan) != len(selected):
        found = {req.endpoint.product_id for req in plan}
        raise SystemExit(f"selected item(s) not found: {sorted(selected - found)}")
    policy = _policy(output_root)
    engine = CertifiedFetchEngine(policy)
    manifest = ManifestEngine(policy.manifest_root)
    results = [engine.dry_run(req) for req in plan]
    manifest.write_fetch_receipts(results, filename="noaa_maria_8507_dry_run.csv")
    print(json.dumps([asdict(result) for result in results], indent=2))
    return 0


def fetch_pilot(output_root: Path, item_id: str) -> int:
    url_text = _read_url(URL_LIST_URL).decode("utf-8")
    stac_bytes = _read_url(STAC_ITEM_COLLECTION_URL)
    _, items = discover_from_documents(url_text, stac_bytes)
    by_id = {item.item_id: item for item in items}
    if item_id not in by_id:
        raise SystemExit(f"item not found: {item_id}")
    policy = _policy(output_root)
    engine = CertifiedFetchEngine(policy)
    manifest = ManifestEngine(policy.manifest_root)
    result = engine.fetch(build_payload_request(by_id[item_id]))
    manifest.write_fetch_receipts([result], filename="noaa_maria_8507_pilot_receipt.csv")
    print(json.dumps(asdict(result), indent=2))
    return 0 if result.review_status in {"raw", "cache_hit"} else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p_discover = sub.add_parser("discover")
    p_discover.add_argument("--output-root", type=Path, required=True)
    p_dry = sub.add_parser("dry-run")
    p_dry.add_argument("--output-root", type=Path, required=True)
    p_dry.add_argument("--item-id", action="append", default=[])
    p_fetch = sub.add_parser("fetch-pilot")
    p_fetch.add_argument("--output-root", type=Path, required=True)
    p_fetch.add_argument("--item-id", default=PILOT_ITEM_ID)
    args = parser.parse_args(argv)
    if args.command == "discover":
        return discover(args.output_root)
    if args.command == "dry-run":
        return dry_run(args.output_root, args.item_id)
    return fetch_pilot(args.output_root, args.item_id)


if __name__ == "__main__":
    raise SystemExit(main())
