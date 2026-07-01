from pathlib import Path


def test_source_registry_disallows_public_tactical_tracking():
    registry = Path("registry/source_registry.yaml").read_text(encoding="utf-8")

    assert "tactical_public_tracking: false" in registry
    assert "historical_baseline" in registry
    assert "delayed_or_rate_limited" in registry


def test_schemas_require_confidence_and_source_tier():
    schema_paths = [
        Path("schemas/air_event.schema.json"),
        Path("schemas/maritime_baseline.schema.json"),
        Path("schemas/cross_domain_overlap.schema.json"),
    ]

    for path in schema_paths:
        text = path.read_text(encoding="utf-8")
        assert "confidence" in text

    assert "source_tier" in Path("schemas/air_event.schema.json").read_text(encoding="utf-8")
    assert "source_tier" in Path("schemas/maritime_baseline.schema.json").read_text(encoding="utf-8")
