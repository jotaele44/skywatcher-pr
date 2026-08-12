"""Gate: duplicate detection without operational data."""

from __future__ import annotations

from skywatcher.fr24 import duplicate_detection as dd


def test_exact_duplicate_grouping():
    items = [
        ("a.png", b"same-bytes"),
        ("b.png", b"same-bytes"),
        ("c.png", b"different"),
    ]
    dups = dd.find_exact_duplicates(items)
    # Exactly one duplicate group, containing a.png and b.png.
    assert len(dups) == 1
    group = next(iter(dups.values()))
    assert set(group) == {"a.png", "b.png"}


def test_no_duplicates_returns_empty():
    items = [("a.png", b"x"), ("b.png", b"y")]
    assert dd.find_exact_duplicates(items) == {}


def test_dedup_version_and_helpers_exposed():
    assert isinstance(dd.DEDUP_VERSION, str)
    # dedupe_rows on synthetic candidate rows returns (kept, dups, summary).
    rows = [
        {"image_name": "x.png", "review_status": "region_parsed_candidate"},
        {"image_name": "x.png", "review_status": "region_parsed_candidate"},
    ]
    kept, dups, summary = dd.dedupe_rows(rows)
    assert isinstance(kept, list) and isinstance(dups, list) and isinstance(summary, dict)
