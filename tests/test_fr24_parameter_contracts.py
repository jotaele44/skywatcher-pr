import pytest

from fr24_parameter_contracts import (
    ParameterContract,
    ParameterContractError,
    ParameterStatus,
    validate_parameter_contracts,
)


def valid_contract(**overrides):
    payload = {
        "parameter_id": "small_waterbody_type",
        "family": "small_waterbody_identity",
        "type": "enum",
        "source_method": "visual",
        "confidence_field": "small_waterbody_confidence",
        "failure_modes": ["not_visible", "shadow_confusion"],
        "export_target": "small_waterbody_locator",
        "review_rule": "review when type is unknown or confidence < 0.7",
        "implemented_by": None,
        "test_required": True,
        "status": "queued",
        "allowed_values": ["small_pond", "well", "unknown_water_feature"],
        "created_in_operation": 13,
        "mapped_operation_ids": [13, 14, 20, 22, 28, 30, 31, 32],
        "parameter_origin": "user_established",
    }
    payload.update(overrides)
    return ParameterContract(**payload)


def test_valid_parameter_contract_serializes_round_trip():
    contract = valid_contract()
    payload = contract.to_dict()

    assert payload["parameter_id"] == "small_waterbody_type"
    assert payload["family"] == "small_waterbody_identity"
    assert payload["status"] == "queued"
    assert payload["mapped_operation_ids"] == [13, 14, 20, 22, 28, 30, 31, 32]
    assert ParameterContract.from_dict(payload) == contract


def test_required_parameter_cannot_be_nullable():
    with pytest.raises(ParameterContractError, match="required parameters"):
        valid_contract(required=True, nullable=True)


def test_enum_requires_allowed_values():
    with pytest.raises(ParameterContractError, match="enum parameters"):
        valid_contract(allowed_values=[])


def test_snake_case_required_for_parameter_id_and_family():
    with pytest.raises(ParameterContractError, match="parameter_id"):
        valid_contract(parameter_id="BadName")

    with pytest.raises(ParameterContractError, match="family"):
        valid_contract(family="BadFamily")


def test_failure_modes_are_required_and_snake_case():
    with pytest.raises(ParameterContractError, match="failure_modes"):
        valid_contract(failure_modes=[])

    with pytest.raises(ParameterContractError, match="failure_modes"):
        valid_contract(failure_modes=["Bad Failure"])


def test_implemented_status_requires_implemented_by():
    with pytest.raises(ParameterContractError, match="implemented parameters"):
        valid_contract(status=ParameterStatus.IMPLEMENTED, implemented_by=None)

    implemented = valid_contract(
        status=ParameterStatus.IMPLEMENTED,
        implemented_by="fr24_ground_context.py",
    )
    assert implemented.status == ParameterStatus.IMPLEMENTED


def test_deprecated_requires_replacement_parameter_id():
    with pytest.raises(ParameterContractError, match="deprecated parameters"):
        valid_contract(deprecated=True, status="deprecated")

    deprecated = valid_contract(
        deprecated=True,
        status="deprecated",
        replacement_parameter_id="small_waterbody_type_v2",
    )
    assert deprecated.replacement_parameter_id == "small_waterbody_type_v2"


def test_invalid_type_source_method_export_target_and_origin_are_rejected():
    with pytest.raises(ParameterContractError, match="unsupported parameter type"):
        valid_contract(type="bad_type")

    with pytest.raises(ParameterContractError, match="unsupported source_method"):
        valid_contract(source_method="bad_method")

    with pytest.raises(ParameterContractError, match="unsupported export_target"):
        valid_contract(export_target="bad_export")

    with pytest.raises(ParameterContractError, match="unsupported parameter_origin"):
        valid_contract(parameter_origin="bad_origin")


def test_validate_parameter_contracts_rejects_duplicate_ids():
    first = valid_contract(parameter_id="pond_present", type="boolean", allowed_values=[])
    duplicate = valid_contract(parameter_id="pond_present", type="boolean", allowed_values=[])

    with pytest.raises(ParameterContractError, match="duplicate parameter_id"):
        validate_parameter_contracts([first, duplicate])


def test_registry_ready_status():
    assert valid_contract(status="queued").is_registry_ready is True
    assert valid_contract(status="draft").is_registry_ready is False
