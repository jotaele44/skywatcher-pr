import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from skywatcher.core.pitirre_observation import ObservationAdapterError
from skywatcher.core.spacetrack.adapters import normalize_gp
from skywatcher.core.spacetrack.models import NormalizedBatch
from skywatcher.core.spacetrack.pitirre_adapter import adapt_gp_batch_row


def batch(raw=None):
    raw = raw if raw is not None else {"NORAD_CAT_ID": "123456789", "GP_ID": "456", "EPOCH": "2026-10-01T00:00:00Z", "OBJECT_NAME": " duplicate  name ", "unknown_field": {"raw": " SkyWatcher v1 "}}
    return NormalizedBatch("gp", "2026-10-02T00:00:00Z", "frozen-query", "a" * 64, None, (normalize_gp(raw),))


def test_gp_adapter_preserves_row_manifestation_and_separate_epochs():
    source = batch()
    before = deepcopy(source.rows[0])
    result = adapt_gp_batch_row(source, 0).to_dict()
    assert (result["domain"], result["subdomain"]) == ("SPACE", "ORBITAL")
    assert result["payload"]["row"] == before
    assert result["payload"]["source_manifestation"]["retrieved_utc"] != result["event_time_raw"]
    assert result["payload"]["row"]["raw"]["NORAD_CAT_ID"] == "123456789"
    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/pitirre_observation.v1.schema.json").read_text())
    Draft202012Validator(schema).validate(result)
    result["payload"]["row"]["raw"]["unknown_field"]["raw"] = "changed"
    assert source.rows[0] == before


@pytest.mark.parametrize("catalog", [None, True, "same name", " 123", "１２３"])
def test_names_and_invalid_catalog_tokens_do_not_bind(catalog):
    with pytest.raises(ObservationAdapterError):
        adapt_gp_batch_row(batch({"NORAD_CAT_ID": catalog, "EPOCH": "epoch", "OBJECT_NAME": "123456789"}), 0)


def test_conflicting_raw_and_normalized_identity_fails_closed():
    source = batch()
    source.rows[0]["norad_cat_id"] = "999"
    with pytest.raises(ObservationAdapterError):
        adapt_gp_batch_row(source, 0)


@pytest.mark.parametrize("index", [-1, 1, True])
def test_row_selection_never_uses_nearest_or_silent_fallback(index):
    with pytest.raises(ObservationAdapterError):
        adapt_gp_batch_row(batch(), index)
