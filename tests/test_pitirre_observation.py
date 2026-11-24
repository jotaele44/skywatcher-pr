import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from skywatcher.core.pitirre_observation import (
    ADAPTER_VERSION,
    OBSERVATION_SCHEMA_VERSION,
    ObservationAdapterError,
    adapt_airspace_observation,
    adapt_maritime_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "pitirre_observation.v1.schema.json"


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_airspace_adapter_is_lossless_and_valid():
    source = {
        "observation_id": "obs-1",
        "event_datetime": "2026-10-02T12:00:00-04:00",
        "lat": 18.4,
        "lon": -66.0,
        "signal_type": "track_point",
        "source_id": "fr24:raw:001",
        "source_type": "screenshot",
        "source_record_id": "RAW  001",
        "evidence_tier": "T2",
        "confidence": 0.7,
        "geometry_status": "approximate",
        "temporal_status": "exact",
        "lineage_id": " lineage/raw ",
        "synthetic": False,
    }

    adapted = adapt_airspace_observation(source).to_dict()

    assert adapted["schema_version"] == OBSERVATION_SCHEMA_VERSION
    assert adapted["adapter"]["adapter_version"] == ADAPTER_VERSION
    assert adapted["domain"] == "AIR"
    assert adapted["subdomain"] == "AVIATION"
    assert adapted["network_type"] is None
    assert adapted["payload"] == source
    assert adapted["payload"]["source_record_id"] == "RAW  001"
    assert adapted["payload"]["lineage_id"] == " lineage/raw "
    _validator().validate(adapted)


def test_maritime_adapter_binds_water_maritime_and_preserves_context_only_flag():
    source = {
        "record_id": "marine-1",
        "source": "noaa_marinecadastre_baseline",
        "source_tier": "T1",
        "mode": "historical_baseline",
        "observed_at": "2026-09-01T00:00:00Z",
        "lat": 18.45,
        "lon": -66.1,
        "category": "port_context",
        "confidence": 0.9,
        "operational_use_allowed": False,
        "raw_note": " preserve  spacing ",
    }

    adapted = adapt_maritime_baseline(source).to_dict()

    assert adapted["domain"] == "WATER"
    assert adapted["subdomain"] == "MARITIME"
    assert adapted["payload"] == source
    assert adapted["evidence"]["operational_use_allowed"] is False
    assert adapted["payload"]["raw_note"] == " preserve  spacing "
    _validator().validate(adapted)


def test_adapter_copy_prevents_downstream_mutation_of_source_row():
    source = {
        "record_id": "marine-2",
        "source": "source-a",
        "source_tier": "T2",
        "mode": "batch_file",
        "observed_at": "2026-09-01T01:00:00Z",
        "lat": 18.0,
        "lon": -67.0,
        "category": "context",
        "confidence": 0.5,
        "operational_use_allowed": False,
        "nested": {"raw": "value"},
    }

    adapted = adapt_maritime_baseline(source).to_dict()
    adapted["payload"]["nested"]["raw"] = "changed"

    assert source["nested"]["raw"] == "value"


def test_missing_identity_or_time_fields_fail_closed():
    with pytest.raises(ObservationAdapterError):
        adapt_airspace_observation(
            {
                "event_datetime": "2026-10-02T12:00:00Z",
                "source_id": "x",
                "lat": 18.0,
                "lon": -66.0,
            }
        )

    with pytest.raises(ObservationAdapterError):
        adapt_maritime_baseline(
            {
                "record_id": "x",
                "source": "source-a",
                "lat": 18.0,
                "lon": -66.0,
            }
        )


def test_boolean_is_not_accepted_as_coordinate_number():
    with pytest.raises(ObservationAdapterError):
        adapt_maritime_baseline(
            {
                "record_id": "x",
                "source": "source-a",
                "observed_at": "2026-09-01T00:00:00Z",
                "lat": True,
                "lon": -66.0,
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lat", 90.0001),
        ("lat", -90.0001),
        ("lon", 180.0001),
        ("lon", -180.0001),
    ],
)
def test_out_of_range_coordinates_fail_closed(field, value):
    row = {
        "record_id": "x",
        "source": "source-a",
        "observed_at": "2026-09-01T00:00:00Z",
        "lat": 18.0,
        "lon": -66.0,
    }
    row[field] = value
    with pytest.raises(ObservationAdapterError):
        adapt_maritime_baseline(row)
