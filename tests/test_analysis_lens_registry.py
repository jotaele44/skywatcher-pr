"""Contract tests for the declarative lens / parameter / objective registry.

The registry's whole value is that adding an analytical parameter is a config edit
rather than a code edit. That only holds if the config is actually validated, every
threshold a lens names really exists, and an unmet requirement genuinely blocks a run
instead of quietly passing. Those are the properties pinned here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skywatcher.core.lenses import (
    DEGRADED,
    EVIDENCE_AXES,
    MISSING,
    NOT_APPLICABLE,
    SATISFIED,
    LensRegistry,
    LensSpec,
    ObjectiveProfile,
    ObjectiveProfileRegistry,
    ParameterSpec,
    ThresholdNotExecutable,
    ThresholdRegistry,
    evaluate_coverage,
    evaluate_lens,
    load_default_registries,
    unknown_lens_references,
)
from skywatcher.core.lenses.models import RESTRICTIONS

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas"


@pytest.fixture(scope="module")
def registries() -> tuple[LensRegistry, ObjectiveProfileRegistry]:
    return load_default_registries()


@pytest.fixture(scope="module")
def thresholds() -> ThresholdRegistry:
    registry = ThresholdRegistry()
    registry.load()
    return registry


# ── the committed seed set ──────────────────────────────────────────────────────


def test_seed_lenses_load_and_cover_both_stages(registries) -> None:
    lenses, _ = registries
    assert len(lenses) >= 6

    stages = {lens.stage for lens in lenses.all()}
    assert "flight_data_collection" in stages, "flight data collection must have lenses"
    assert "satellite_image_processing" in stages, "imagery must have lenses"

    # The four lenses this system was built to carry.
    for lens_id in (
        "satim.image_artifacts",
        "satim.hydrogeography",
        "satim.subsurface_infrastructure",
        "satim.dual_use_function",
    ):
        assert lens_id in lenses, f"{lens_id} missing from the seed set"


def test_every_referenced_threshold_exists_and_is_executable(registries, thresholds) -> None:
    """A lens naming a threshold that does not exist is a runtime failure waiting."""
    lenses, _ = registries
    for threshold_id in lenses.threshold_ids():
        spec = thresholds.get(threshold_id)
        assert spec.executable, (
            f"{threshold_id} is referenced by a lens but has status {spec.status}, "
            "which cannot execute"
        )


def test_no_lens_references_a_prohibited_threshold(registries, thresholds) -> None:
    """ILAP-IDENTITY-PRIORITY stayed PROHIBITED through the unfreeze; keep it unused."""
    lenses, _ = registries
    prohibited = {
        tid for tid in thresholds.threshold_ids()
        if thresholds.get(tid).status == "PROHIBITED"
    }
    assert prohibited, "the prohibited class must not vanish"
    assert not (set(lenses.threshold_ids()) & prohibited)


def test_objective_profiles_resolve(registries) -> None:
    lenses, objectives = registries
    assert objectives.profile_ids()
    assert unknown_lens_references(objectives.all(), lenses) == {}


def test_infrastructure_survey_requires_all_four_named_lenses(registries) -> None:
    _, objectives = registries
    survey = objectives.get("infrastructure_survey")
    assert {
        "satim.image_artifacts",
        "satim.hydrogeography",
        "satim.subsurface_infrastructure",
        "satim.dual_use_function",
    } <= set(survey.required_lenses)


def test_dual_use_lens_carries_its_governance_constraints(registries) -> None:
    """ADR v2.1 A1 permits a bounded claim; the lens must state the bounds."""
    lenses, _ = registries
    lens = lenses.get("satim.dual_use_function")

    assert lens.owner == "SATIM"
    assert "DUAL_USE_FUNCTION_CANDIDATE" in lens.emits

    # All ten evidence axes: a function claim may not collapse any of them.
    assert set(lens.evidence_axes_required) == set(EVIDENCE_AXES)

    # The section 5.3 confidence record is required input, not optional decoration.
    required = {p.parameter_id for p in lens.required_parameters}
    assert {"confidence_method", "confidence_scope", "method_version"} <= required
    assert "structural_feature_ids" in required, "a function claim needs observed structure"

    prohibited = " ".join(lens.prohibited_claims).lower()
    for forbidden in ("ownership", "intent", "mission", "wrongdoing"):
        assert forbidden in prohibited


def test_optional_parameters_all_declare_what_absence_costs(registries) -> None:
    """The anti-silent-fallback rule, enforced across the whole seed set."""
    lenses, _ = registries
    for lens in lenses.all():
        for spec in lens.optional_parameters:
            assert spec.degraded_behavior, (
                f"{lens.lens_id}.{spec.parameter_id} is optional but does not say "
                "what is lost when it is absent"
            )


def test_core_restriction_vocabulary_matches_satim_gate() -> None:
    """core cannot import satim, so the ladder is duplicated. Keep the copies equal."""
    from skywatcher.satim.artifacts.restriction_gate import ORDER

    assert list(RESTRICTIONS) == sorted(ORDER, key=lambda k: ORDER[k])


# ── model validation ────────────────────────────────────────────────────────────


def _lens(**overrides) -> dict:
    base = {
        "lens_id": "satim.example",
        "name": "Example",
        "owner": "SATIM",
        "stage": "satellite_image_processing",
        "objective": "Example objective.",
    }
    base.update(overrides)
    return base


def test_lens_rejects_unknown_owner_and_stage() -> None:
    with pytest.raises(ValueError, match="unknown owner"):
        LensSpec.from_mapping(_lens(owner="MARKETING"))
    with pytest.raises(ValueError, match="unknown stage"):
        LensSpec.from_mapping(_lens(stage="whenever"))


def test_only_corrim_may_own_a_cross_domain_lens() -> None:
    """The one boundary the data model can enforce on its own (ADR v2.0 section 3)."""
    with pytest.raises(ValueError, match="only CORRIM"):
        LensSpec.from_mapping(_lens(stage="cross_domain", owner="SATIM"))

    ok = LensSpec.from_mapping(_lens(lens_id="corrim.x", stage="cross_domain", owner="CORRIM"))
    assert ok.stage == "cross_domain"


def test_optional_parameter_without_degraded_behavior_is_rejected() -> None:
    with pytest.raises(ValueError, match="degraded_behavior"):
        ParameterSpec.from_mapping(
            {"parameter_id": "x", "kind": "number", "required": False}
        )


def test_profile_with_no_required_lenses_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot gate anything"):
        ObjectiveProfile.from_mapping({"profile_id": "empty", "name": "Empty"})


def test_coverage_state_demands_a_reason() -> None:
    from skywatcher.core.lenses.models import LensCoverage

    with pytest.raises(ValueError, match="requires a reason"):
        LensCoverage(lens_id="satim.example", state=MISSING)


# ── coverage evaluation ─────────────────────────────────────────────────────────


@pytest.fixture()
def sample_lens() -> LensSpec:
    return LensSpec.from_mapping(
        _lens(
            required_inputs=["source_frame"],
            required_parameters=[{"parameter_id": "roi_target", "kind": "array"}],
            optional_parameters=[
                {
                    "parameter_id": "control_roi",
                    "kind": "array",
                    "required": False,
                    "degraded_behavior": "no local baseline",
                }
            ],
        )
    )


def test_all_inputs_present_is_satisfied(sample_lens) -> None:
    entry = evaluate_lens(
        sample_lens,
        supplied_parameters={"roi_target": [0, 0, 4, 4], "control_roi": [5, 5, 9, 9]},
        available_inputs=["source_frame"],
    )
    assert entry.state == SATISFIED


def test_absent_required_parameter_is_missing_and_names_itself(sample_lens) -> None:
    entry = evaluate_lens(
        sample_lens, supplied_parameters={}, available_inputs=["source_frame"]
    )
    assert entry.state == MISSING
    assert entry.unmet_parameters == ("roi_target",)
    assert "roi_target" in entry.reason


def test_absent_optional_parameter_degrades_with_its_stated_cost(sample_lens) -> None:
    entry = evaluate_lens(
        sample_lens,
        supplied_parameters={"roi_target": [0, 0, 4, 4]},
        available_inputs=["source_frame"],
    )
    assert entry.state == DEGRADED
    assert entry.unmet_parameters == ("control_roi",)
    assert "no local baseline" in entry.reason


def test_absent_required_input_is_missing(sample_lens) -> None:
    entry = evaluate_lens(
        sample_lens, supplied_parameters={"roi_target": [0]}, available_inputs=[]
    )
    assert entry.state == MISSING
    assert "source_frame" in entry.reason


def test_ran_but_produced_nothing_is_degraded_not_satisfied(sample_lens) -> None:
    entry = evaluate_lens(
        sample_lens,
        supplied_parameters={"roi_target": [0], "control_roi": [1]},
        available_inputs=["source_frame"],
        produced=False,
    )
    assert entry.state == DEGRADED


def test_a_default_counts_as_supplied() -> None:
    lens = LensSpec.from_mapping(
        _lens(required_parameters=[{"parameter_id": "cap", "kind": "boolean", "default": False}])
    )
    assert evaluate_lens(lens, supplied_parameters={}).state == SATISFIED


# ── the fail-closed guarantee ───────────────────────────────────────────────────


def _two_lens_registry() -> tuple[LensRegistry, ObjectiveProfile]:
    registry = LensRegistry()
    registry.register(
        LensSpec.from_mapping(
            _lens(
                lens_id="satim.required_one",
                required_parameters=[{"parameter_id": "roi_target", "kind": "array"}],
            )
        )
    )
    registry.register(LensSpec.from_mapping(_lens(lens_id="satim.optional_one")))
    profile = ObjectiveProfile.from_mapping(
        {
            "profile_id": "p",
            "name": "P",
            "required_lenses": ["satim.required_one"],
            "optional_lenses": ["satim.optional_one"],
        }
    )
    return registry, profile


def test_unmet_required_lens_blocks_completion() -> None:
    registry, profile = _two_lens_registry()
    report = evaluate_coverage(profile, registry, run_id="r1")

    assert report.complete is False
    assert report.blocking_reasons
    assert "satim.required_one" in report.blocking_reasons[0]
    assert report.states()["satim.required_one"] == MISSING


def test_met_required_lens_completes() -> None:
    registry, profile = _two_lens_registry()
    report = evaluate_coverage(
        profile,
        registry,
        run_id="r2",
        supplied_parameters={"satim.required_one": {"roi_target": [0, 0, 1, 1]}},
    )
    assert report.complete is True
    assert report.blocking_reasons == ()


def test_unmet_optional_lens_never_blocks() -> None:
    registry, profile = _two_lens_registry()
    report = evaluate_coverage(
        profile,
        registry,
        run_id="r3",
        supplied_parameters={"satim.required_one": {"roi_target": [0]}},
        produced={"satim.optional_one": False},
    )
    assert report.states()["satim.optional_one"] == DEGRADED
    assert report.complete is True


def test_required_lens_marked_not_applicable_still_blocks() -> None:
    """Declaring a required lens inapplicable must not be a way to pass the gate."""
    registry, profile = _two_lens_registry()
    report = evaluate_coverage(
        profile,
        registry,
        run_id="r4",
        supplied_parameters={"satim.required_one": {"roi_target": [0]}},
        applicable={"satim.required_one": False},
    )
    assert report.states()["satim.required_one"] == NOT_APPLICABLE
    assert report.complete is False


def test_profile_naming_an_unregistered_lens_blocks_rather_than_crashing() -> None:
    registry = LensRegistry()
    registry.register(LensSpec.from_mapping(_lens(lens_id="satim.only")))
    profile = ObjectiveProfile.from_mapping(
        {"profile_id": "p", "name": "P", "required_lenses": ["satim.gone"]}
    )
    report = evaluate_coverage(profile, registry, run_id="r5")
    assert report.complete is False
    assert "not registered" in report.blocking_reasons[0]


def test_seed_survey_run_with_nothing_supplied_is_not_complete(registries) -> None:
    """The end-to-end shape: an empty run against the real profile must fail closed."""
    lenses, objectives = registries
    report = evaluate_coverage(
        objectives.get("infrastructure_survey"), lenses, run_id="empty"
    )
    assert report.complete is False
    assert len(report.blocking_reasons) == len(
        objectives.get("infrastructure_survey").required_lenses
    )


# ── threshold execution ─────────────────────────────────────────────────────────


def test_prohibited_threshold_refuses_to_execute(thresholds) -> None:
    with pytest.raises(ThresholdNotExecutable, match="PROHIBITED"):
        thresholds.value_of("ILAP-IDENTITY-PRIORITY")


def test_non_executable_status_refuses_to_execute(thresholds) -> None:
    with pytest.raises(ThresholdNotExecutable, match="not executable"):
        thresholds.value_of("RLSM-SCALEBAR-OCR-15PCT")


def test_executed_threshold_stamps_its_provenance(thresholds) -> None:
    """ADR v2.1 A2: a consumer must always see the status behind a number."""
    (stamp,) = thresholds.stamp(["SATIM-ARTIFACT-HIGH-0.75"])
    assert stamp == {
        "threshold_id": "SATIM-ARTIFACT-HIGH-0.75",
        "value": 0.75,
        "status": "EXECUTABLE_CANDIDATE",
    }


def test_unknown_threshold_says_what_to_do(thresholds) -> None:
    with pytest.raises(KeyError, match="register it"):
        thresholds.get("SATIM-MADE-UP-0.99")


# ── schemas ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "analysis_lens_v1.schema.json",
        "analysis_objective_profile_v1.schema.json",
        "analysis_coverage_report_v1.schema.json",
    ],
)
def test_new_schemas_follow_house_rules(name: str) -> None:
    schema = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"]


def test_seed_lenses_validate_against_the_lens_schema(registries) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (SCHEMA_DIR / "analysis_lens_v1.schema.json").read_text(encoding="utf-8")
    )
    lenses, _ = registries
    for lens in lenses.all():
        payload = {k: v for k, v in lens.to_dict().items() if v not in (None, [], ())}
        # to_dict emits every field; drop the empties so absent-optional stays absent.
        jsonschema.validate(payload, schema)


def test_ontology_gate_fails_closed_on_a_missing_lens_registry(tmp_path: Path) -> None:
    """A run must not be able to pass the gate by having no lenses at all."""
    from skywatcher.core.ontology_gate import run_gate

    result = run_gate(config_dir=tmp_path)
    failures = " ".join(str(f) for f in result["failures"])
    assert result["status"] == "fail"
    assert "analysis/lenses" in failures
    assert "analysis/objectives" in failures


def test_ontology_gate_fails_closed_on_a_dangling_lens_reference(tmp_path: Path) -> None:
    """An objective naming a lens nobody implements is a silent-skip in waiting."""
    import shutil

    from skywatcher.core.ontology_gate import run_gate

    # Real configs, so only the injected fault differs from a passing run.
    shutil.copytree(REPO_ROOT / "configs", tmp_path / "configs")
    config_dir = tmp_path / "configs"
    (config_dir / "analysis" / "objectives" / "broken.yaml").write_text(
        "profile_id: broken\n"
        "name: Broken\n"
        "version: 1.0.0\n"
        "status: experimental\n"
        "required_lenses:\n"
        "  - satim.does_not_exist\n",
        encoding="utf-8",
    )

    result = run_gate(config_dir=config_dir)
    assert result["status"] == "fail"
    assert any("satim.does_not_exist" in str(f) for f in result["failures"])


def test_coverage_report_validates_against_its_schema(registries) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (SCHEMA_DIR / "analysis_coverage_report_v1.schema.json").read_text(encoding="utf-8")
    )
    lenses, objectives = registries
    report = evaluate_coverage(
        objectives.get("satellite_imagery_standard"), lenses, run_id="schema-check"
    )
    jsonschema.validate(report.to_dict(), schema)
