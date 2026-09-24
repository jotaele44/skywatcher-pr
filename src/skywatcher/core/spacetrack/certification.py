"""Certification gates for the Space-Track v1 control plane."""

from __future__ import annotations

from .contracts import CONTROLLER_CONTRACTS, SOURCE_CONTRACTS
from .models import (
    CertificationState,
    GateResult,
    SpaceTrackCertificationReport,
)
from .storage import SpaceTrackStore


def _report(
    scope: str,
    gates: list[GateResult],
    unresolved: list[str],
) -> SpaceTrackCertificationReport:
    if any(gate.state is CertificationState.FAIL for gate in gates):
        state = CertificationState.FAIL
    elif any(gate.state is CertificationState.BLOCKED for gate in gates):
        state = CertificationState.BLOCKED
    elif any(
        gate.state in {CertificationState.OPEN, CertificationState.PROVISIONAL}
        for gate in gates
    ):
        state = CertificationState.OPEN
    else:
        state = CertificationState.PASS
    return SpaceTrackCertificationReport(
        scope=scope,
        state=state,
        gates=tuple(gates),
        unresolved=tuple(sorted(set(unresolved))),
    )


def certify_static_contracts() -> SpaceTrackCertificationReport:
    gates: list[GateResult] = []
    unresolved: list[str] = []

    source_ids = [contract.source_id for contract in SOURCE_CONTRACTS]
    source_unique = len(source_ids) == len(set(source_ids))
    gates.append(
        GateResult(
            "SOURCE_ID_UNIQUENESS",
            CertificationState.PASS if source_unique else CertificationState.FAIL,
            f"{len(source_ids)} declared source contracts",
        )
    )

    controllers = {contract.controller for contract in CONTROLLER_CONTRACTS}
    unknown_controllers = sorted(
        {
            contract.controller
            for contract in SOURCE_CONTRACTS
            if contract.controller not in controllers
        }
    )
    gates.append(
        GateResult(
            "CONTROLLER_REFERENTIAL_INTEGRITY",
            CertificationState.PASS
            if not unknown_controllers
            else CertificationState.FAIL,
            "all source contracts bind declared controllers"
            if not unknown_controllers
            else f"unknown controllers: {', '.join(unknown_controllers)}",
        )
    )

    invalid_windows = [
        contract.source_id
        for contract in SOURCE_CONTRACTS
        if (contract.window_limit_count is None) != (contract.window_seconds is None)
        or (
            contract.window_limit_count is not None
            and (
                contract.window_limit_count <= 0
                or contract.window_seconds is None
                or contract.window_seconds <= 0
            )
        )
    ]
    gates.append(
        GateResult(
            "RATE_WINDOW_CONTRACTS",
            CertificationState.PASS if not invalid_windows else CertificationState.FAIL,
            "all rolling-window limits are complete and positive"
            if not invalid_windows
            else f"invalid windows: {', '.join(invalid_windows)}",
        )
    )

    invalid_query_once = [
        contract.source_id
        for contract in SOURCE_CONTRACTS
        if contract.query_once and not contract.retain_locally
    ]
    gates.append(
        GateResult(
            "QUERY_ONCE_RETENTION",
            CertificationState.PASS
            if not invalid_query_once
            else CertificationState.FAIL,
            "all query-once sources require local retention"
            if not invalid_query_once
            else f"query-once without retention: {', '.join(invalid_query_once)}",
        )
    )

    distribution_fail_open = [
        contract.source_id
        for contract in SOURCE_CONTRACTS
        if contract.distribution_class.value in {"BASIC_SSA_CITABLE", "PUBLIC_FILE"}
    ]
    gates.append(
        GateResult(
            "DISTRIBUTION_FAIL_CLOSED",
            CertificationState.PASS
            if not distribution_fail_open
            else CertificationState.FAIL,
            "authenticated Space-Track outputs default to ACCOUNT_ONLY or stricter"
            if not distribution_fail_open
            else f"review distribution defaults: {', '.join(distribution_fail_open)}",
        )
    )

    return _report("SPACE_TRACK_STATIC_CONTRACT_V1", gates, unresolved)


def certify_local_runtime(store: SpaceTrackStore) -> SpaceTrackCertificationReport:
    gates: list[GateResult] = []
    unresolved: list[str] = []

    required = [
        contract
        for contract in SOURCE_CONTRACTS
        if contract.source_id
        not in {
            "publicfile_download",
            "gp_history",
            "organization",
            "curated_favorites",
        }
    ]

    present_count = 0
    for contract in required:
        batches = store.load_normalized_batches(contract.source_id)
        if batches:
            present_count += 1
            state = CertificationState.PASS
            detail = f"{len(batches)} frozen normalized batch(es)"
        else:
            state = CertificationState.OPEN
            detail = "no frozen normalized batch"
            unresolved.append(f"SOURCE:{contract.source_id}")
        gates.append(GateResult(f"SOURCE:{contract.source_id}", state, detail))

        if contract.schema_required:
            schema = store.load_schema(contract.source_id)
            if schema is None:
                gates.append(
                    GateResult(
                        f"SCHEMA:{contract.source_id}",
                        CertificationState.OPEN,
                        "no accepted modeldef baseline",
                    )
                )
                unresolved.append(f"SCHEMA:{contract.source_id}")
            else:
                gates.append(
                    GateResult(
                        f"SCHEMA:{contract.source_id}",
                        CertificationState.PASS,
                        schema.canonical_sha256,
                    )
                )

    if present_count == 0:
        gates.append(
            GateResult(
                "LIVE_ACQUISITION",
                CertificationState.BLOCKED,
                "no authenticated Space-Track runtime acquisition has been frozen",
            )
        )
        unresolved.append("LIVE_AUTHENTICATED_ACQUISITION")

    for name in ("space_objects", "reentry_events"):
        materialized = store.load_materialization(name)
        if materialized is None:
            gates.append(
                GateResult(
                    f"MATERIALIZATION:{name}",
                    CertificationState.OPEN,
                    "current materialization not frozen",
                )
            )
            unresolved.append(f"MATERIALIZATION:{name}")
            continue

        contradictions = materialized.get("contradictions", [])
        unresolved_contradictions = [
            item
            for item in contradictions
            if isinstance(item, dict) and item.get("state") == CertificationState.UNRESOLVED.value
        ]
        gates.append(
            GateResult(
                f"MATERIALIZATION:{name}",
                CertificationState.PASS
                if not unresolved_contradictions
                else CertificationState.OPEN,
                f"{len(unresolved_contradictions)} unresolved contradiction(s)",
            )
        )
        if unresolved_contradictions:
            unresolved.append(f"CONTRADICTIONS:{name}")

    return _report("SPACE_TRACK_LOCAL_RUNTIME_V1", gates, unresolved)
