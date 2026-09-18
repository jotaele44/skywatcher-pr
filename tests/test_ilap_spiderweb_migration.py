import hashlib
import json

import pytest

from skywatcher.corrim.ilap_airspace_bridge import _hydro_utility_score, _load_spatial_contexts
from skywatcher.spatial_context import SpatialArtifactError


def artifact(subject_id="ilap-poi-cell:360:-1330", depth=-40.0, **changes):
    payload = {"contract_version": "spatial-analysis-result/1.0", "producer_repo": "spiderweb-pr", "analysis_id": "a1", "query_id": "q1", "subject_type": "ilap_poi", "subject_id": subject_id, "subject_manifestation_id": "m1", "geometry_role": "USER_DEFINED_BUFFER", "input_geometry_hash": "a" * 64, "target_domain": "OCEAN_DEPTH", "target_feature_id": None, "target_candidate_id": None, "spatial_state": "FULLY_WITHIN", "identity_state": "UNRESOLVED", "source_manifestation_ids": ["s1"], "measurement_classes": ["INTERPOLATED"], "resolution_summary": {}, "surface_depth_min_m": depth, "surface_depth_max_m": depth, "surface_depth_mean_m": depth, "vertical_datum": "MSL assumed"}
    payload.update(changes)
    payload["result_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return payload


def test_verified_spiderweb_depth_drives_score(tmp_path):
    path = tmp_path / "results.ndjson"
    path.write_text(json.dumps(artifact()) + "\n", encoding="utf-8")
    contexts = _load_spatial_contexts(str(path))
    assert _hydro_utility_score(contexts["ilap-poi-cell:360:-1330"]) == 0.9


def test_missing_or_null_spatial_context_uses_baseline(tmp_path):
    assert _hydro_utility_score(None) == 0.2
    item = artifact(depth=None, spatial_state="NULL_EMPTY")
    path = tmp_path / "results.json"
    path.write_text(json.dumps([item]), encoding="utf-8")
    assert _hydro_utility_score(next(iter(_load_spatial_contexts(str(path)).values()))) == 0.2


def test_non_spiderweb_artifact_fails_closed(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([artifact(producer_repo="skywatcher-pr")]), encoding="utf-8")
    with pytest.raises(SpatialArtifactError, match="Spiderweb-authoritative"):
        _load_spatial_contexts(str(path))
