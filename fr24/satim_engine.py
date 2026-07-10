"""Manifest-driven SATIM engine protocol runner.

This module provides the repo-native interface behind the SATIM operator flow.
It accepts either a manifest or an input directory/zip, normalizes known SATIM
inputs, runs the existing L1-L5 calibration adapters, merges the layer reports,
and exports the legacy readiness payload expected by federation surfaces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pipeline.normalize_locations import load_simple_yaml

from .calibration.l1_segmenter_calibration import calibrate as calibrate_l1
from .calibration.l2_route_calibration import calibrate as calibrate_l2
from .calibration.l3_ocr_scoring import calibrate as calibrate_l3
from .calibration.l4_registry_audit import calibrate as calibrate_l4
from .calibration.l5_tile_seam_shadow_calibration import calibrate as calibrate_l5
from .calibration.l5_tile_seam_shadow_calibration import classify_candidate, load_candidates
from .calibration.models import LayerCalibrationResult, merge_layer_reports, write_json
from .calibration.readiness_adapter import satim_report_to_legacy_calibration

try:  # pragma: no cover - optional calibration-packet scoring path
    from satim_calibration import load_calibration_set, score_calibration_set
except Exception:  # pragma: no cover
    load_calibration_set = None  # type: ignore[assignment]
    score_calibration_set = None  # type: ignore[assignment]

try:  # pragma: no cover - exercised when the repo script is importable
    from scripts.validate_satim_calibration import validate_set as validate_calibration_packet_set
except Exception:  # pragma: no cover
    validate_calibration_packet_set = None  # type: ignore[assignment]

MANIFEST_SCHEMA_VERSION = "satim.engine.input.v1"
RUN_SCHEMA_VERSION = "satim.engine.run.v1"

BASE_REQUIRED_LAYERS = {
    "L1_ui_segmenter",
    "L2_route_extractor",
    "L3_vision_ocr",
}

LAYER_OUTPUTS = {
    "L1_ui_segmenter": "l1_ui_segmenter.json",
    "L2_route_extractor": "l2_route_extractor.json",
    "L3_vision_ocr": "l3_vision_ocr.json",
    "L4_aircraft_intelligence": "l4_aircraft_intelligence.json",
    "L5_tile_seam_shadow": "l5_tile_seam_shadow.json",
}

DIRECTORY_INPUT_NAMES = {
    "screenshots_dir": ("screenshots", "images", "input", "fr24_screenshots"),
    "blank_screenshots_dir": ("blanks", "blank_screenshots", "controls"),
}

FILE_INPUT_NAMES = {
    "annotations_json": ("annotations.json", "l1_annotations.json"),
    "ground_truth_csv": ("ground_truth.csv", "truth.csv", "l3_ground_truth.csv"),
    "predictions_json": ("predictions.json", "l3_predictions.json"),
    "fr24_csv": ("fr24_export.csv", "fr24.csv", "observations.csv"),
    "l5_candidates_csv": ("l5_candidates.csv", "tile_seam_candidates.csv", "artifact_candidates.csv"),
    "artifact_assessment_json": ("artifact_assessment.json", "satim_artifact_assessment.json"),
}


@dataclass(frozen=True)
class SATIMEngineManifest:
    """Resolved SATIM protocol input manifest."""

    schema_version: str
    run_id: str
    input_profile: str
    inputs: dict[str, Path]
    options: dict[str, Any]
    outputs: dict[str, Path]
    source_manifest: Path | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "input_profile": self.input_profile,
            "inputs": {key: str(value) for key, value in sorted(self.inputs.items())},
            "options": self.options,
            "outputs": {key: str(value) for key, value in sorted(self.outputs.items())},
            "source_manifest": str(self.source_manifest) if self.source_manifest else None,
        }


def _is_present(path: Path | None) -> bool:
    return bool(path and path.exists())


def _resolve_path(value: Any, base_dir: Path) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _load_manifest_mapping(path: Path) -> Mapping[str, Any]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = load_simple_yaml(path)
    if not isinstance(data, Mapping):
        raise ValueError(f"SATIM manifest must be a mapping: {path}")
    return data


def load_manifest(path: str | Path) -> SATIMEngineManifest:
    """Load and resolve a SATIM engine manifest."""

    manifest_path = Path(path).expanduser().resolve()
    data = _load_manifest_mapping(manifest_path)

    schema_version = str(data.get("schema_version") or "")
    if schema_version != MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported SATIM manifest schema_version {schema_version!r}; "
            f"expected {MANIFEST_SCHEMA_VERSION!r}"
        )

    inputs_raw = data.get("inputs") or {}
    outputs_raw = data.get("outputs") or {}
    options_raw = data.get("options") or {}
    if not isinstance(inputs_raw, Mapping):
        raise ValueError("SATIM manifest 'inputs' must be a mapping")
    if not isinstance(outputs_raw, Mapping):
        raise ValueError("SATIM manifest 'outputs' must be a mapping")
    if not isinstance(options_raw, Mapping):
        raise ValueError("SATIM manifest 'options' must be a mapping")

    base_dir = manifest_path.parent
    inputs = {
        str(key): resolved
        for key, value in inputs_raw.items()
        if (resolved := _resolve_path(value, base_dir)) is not None
    }
    outputs = {
        str(key): resolved
        for key, value in outputs_raw.items()
        if (resolved := _resolve_path(value, base_dir)) is not None
    }

    return SATIMEngineManifest(
        schema_version=schema_version,
        run_id=str(data.get("run_id") or manifest_path.stem),
        input_profile=str(data.get("input_profile") or "fr24_screenshot_batch"),
        inputs=inputs,
        options=dict(options_raw),
        outputs=outputs,
        source_manifest=manifest_path,
    )


def autodetect_inputs(root: str | Path) -> dict[str, Path]:
    """Detect standard SATIM input names under an input root."""

    root_path = Path(root).expanduser().resolve()
    detected: dict[str, Path] = {}

    for key, names in DIRECTORY_INPUT_NAMES.items():
        for name in names:
            candidate = root_path / name
            if candidate.is_dir():
                detected[key] = candidate
                break

    for key, names in FILE_INPUT_NAMES.items():
        for name in names:
            candidate = root_path / name
            if candidate.is_file():
                detected[key] = candidate
                break

    calibration_root = root_path / "calibration_set"
    if calibration_root.is_dir():
        detected["calibration_set_dir"] = calibration_root

    return detected


def find_manifest(root: str | Path) -> Path | None:
    """Find a conventional SATIM manifest under a root directory."""

    root_path = Path(root).expanduser().resolve()
    for name in ("satim_manifest.yaml", "satim_manifest.yml", "satim_manifest.json"):
        candidate = root_path / name
        if candidate.is_file():
            return candidate
    return None


def prepare_input_root(input_path: str | Path, output_dir: str | Path) -> Path:
    """Return an input root, extracting zip bundles into the run output when needed."""

    source = Path(input_path).expanduser().resolve()
    if source.suffix.lower() != ".zip":
        return source

    target = Path(output_dir).expanduser().resolve() / "_input_unpacked"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        archive.extractall(target)

    children = [p for p in target.iterdir() if p.is_dir()]
    files = [p for p in target.iterdir() if p.is_file()]
    if len(children) == 1 and not files:
        return children[0]
    return target


def manifest_from_input(input_path: str | Path, output_dir: str | Path) -> SATIMEngineManifest:
    """Build a manifest from an input directory/zip using standard names."""

    root = prepare_input_root(input_path, output_dir)
    manifest_path = find_manifest(root)
    if manifest_path:
        return load_manifest(manifest_path)

    run_id = Path(root).name or "satim_run"
    return SATIMEngineManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        run_id=run_id,
        input_profile="autodetected_fr24_screenshot_batch",
        inputs=autodetect_inputs(root),
        options={"strict": False, "include_l5": True, "export_legacy_readiness": True},
        outputs={"run_dir": Path(output_dir).expanduser().resolve()},
        source_manifest=None,
    )


def missing_layer(layer: str, reason: str) -> dict[str, Any]:
    severity = "blocker" if layer in BASE_REQUIRED_LAYERS else "warning"
    return LayerCalibrationResult(
        layer=layer,
        status="MISSING",
        metrics={},
        thresholds={},
        findings=[{"severity": severity, "detail": reason}],
    ).to_dict()


def degraded_layer(layer: str, reason: str, error: Exception) -> dict[str, Any]:
    severity = "blocker" if layer in BASE_REQUIRED_LAYERS else "warning"
    return LayerCalibrationResult(
        layer=layer,
        status="DEGRADED",
        metrics={},
        thresholds={},
        findings=[
            {
                "severity": severity,
                "detail": reason,
                "error_type": error.__class__.__name__,
                "error": str(error),
            }
        ],
    ).to_dict()


def _write_layer(layer: str, payload: Mapping[str, Any], layers_dir: Path) -> Path:
    output_path = layers_dir / LAYER_OUTPUTS[layer]
    write_json(output_path, payload)
    return output_path


def _require_or_missing(manifest: SATIMEngineManifest, layer: str, paths: Mapping[str, Path | None]) -> str | None:
    missing = [name for name, path in paths.items() if not _is_present(path)]
    if not missing:
        return None
    detail = f"missing input(s) for {layer}: {', '.join(missing)}"
    if manifest.options.get("strict") and layer in BASE_REQUIRED_LAYERS:
        raise ValueError(detail)
    return detail


def validate_calibration_set(set_dir: Path) -> dict[str, Any]:
    """Run the existing SATIM calibration-packet validator when available."""

    if validate_calibration_packet_set is None:
        return {
            "status": "SKIPPED",
            "errors": ["scripts.validate_satim_calibration.validate_set is unavailable"],
            "warnings": [],
        }
    errors, warnings = validate_calibration_packet_set(set_dir)
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
    }


def score_calibration_packet(set_dir: Path) -> dict[str, Any] | None:
    """Score an optional SATIM calibration packet without affecting layer readiness."""

    if load_calibration_set is None or score_calibration_set is None:
        return None
    try:
        return score_calibration_set(load_calibration_set(set_dir))
    except Exception as exc:  # malformed packets are already captured by validation
        return {"status": "SKIPPED", "reason": str(exc)}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(str(item.relative_to(path)).replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_provenance(manifest: SATIMEngineManifest) -> dict[str, Any]:
    """Build deterministic input provenance for files and directories."""

    inputs: list[dict[str, Any]] = []
    for key, path in sorted(manifest.inputs.items()):
        if not path.exists():
            inputs.append({"name": key, "path": str(path), "exists": False})
            continue
        if path.is_dir():
            inputs.append({
                "name": key,
                "path": str(path),
                "exists": True,
                "kind": "directory",
                "sha256_tree": _sha256_tree(path),
            })
        else:
            inputs.append({
                "name": key,
                "path": str(path),
                "exists": True,
                "kind": "file",
                "sha256": _sha256_file(path),
            })
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": manifest.run_id,
        "input_profile": manifest.input_profile,
        "inputs": inputs,
    }


def run_satim_engine(manifest: SATIMEngineManifest, output_dir: str | Path | None = None) -> dict[str, Any]:
    """Execute the SATIM protocol run and return the run summary."""

    run_dir = Path(output_dir or manifest.outputs.get("run_dir") or f"reports/satim/runs/{manifest.run_id}")
    run_dir = run_dir.expanduser().resolve()
    layers_dir = run_dir / "layers"
    layers_dir.mkdir(parents=True, exist_ok=True)

    write_json(run_dir / "resolved_manifest.json", manifest.to_jsonable())
    if manifest.source_manifest and manifest.source_manifest.exists():
        manifest_copy_dir = run_dir / "input_manifest"
        manifest_copy_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(manifest.source_manifest, manifest_copy_dir / manifest.source_manifest.name)

    inputs = manifest.inputs
    layer_paths: list[Path] = []

    screenshots = inputs.get("screenshots_dir")
    annotations = inputs.get("annotations_json")
    missing = _require_or_missing(manifest, "L1_ui_segmenter", {"screenshots_dir": screenshots})
    l1_payload = missing_layer("L1_ui_segmenter", missing) if missing else calibrate_l1(str(screenshots), str(annotations) if _is_present(annotations) else None)
    layer_paths.append(_write_layer("L1_ui_segmenter", l1_payload, layers_dir))

    blanks = inputs.get("blank_screenshots_dir")
    missing = _require_or_missing(manifest, "L2_route_extractor", {"screenshots_dir": screenshots})
    if missing:
        l2_payload = missing_layer("L2_route_extractor", missing)
    else:
        try:
            l2_payload = calibrate_l2(
                str(screenshots),
                str(blanks) if _is_present(blanks) else None,
                int(manifest.options.get("min_route_pixels", 8)),
            )
        except Exception as exc:
            l2_payload = degraded_layer(
                "L2_route_extractor",
                "adapter failure while running L2 route extraction",
                exc,
            )
    layer_paths.append(_write_layer("L2_route_extractor", l2_payload, layers_dir))

    ground_truth = inputs.get("ground_truth_csv")
    predictions = inputs.get("predictions_json")
    missing = _require_or_missing(
        manifest,
        "L3_vision_ocr",
        {"ground_truth_csv": ground_truth, "predictions_json": predictions},
    )
    l3_payload = missing_layer("L3_vision_ocr", missing) if missing else calibrate_l3(str(ground_truth), str(predictions))
    layer_paths.append(_write_layer("L3_vision_ocr", l3_payload, layers_dir))

    fr24_csv = inputs.get("fr24_csv")
    missing = _require_or_missing(manifest, "L4_aircraft_intelligence", {"fr24_csv": fr24_csv})
    l4_payload = missing_layer("L4_aircraft_intelligence", missing) if missing else calibrate_l4(str(fr24_csv))
    layer_paths.append(_write_layer("L4_aircraft_intelligence", l4_payload, layers_dir))

    l5_candidates = inputs.get("l5_candidates_csv")
    include_l5 = bool(manifest.options.get("include_l5", True))
    if include_l5:
        missing = _require_or_missing(manifest, "L5_tile_seam_shadow", {"l5_candidates_csv": l5_candidates})
        l5_payload = missing_layer("L5_tile_seam_shadow", missing) if missing else calibrate_l5(str(l5_candidates))
    else:
        l5_payload = LayerCalibrationResult(
            layer="L5_tile_seam_shadow",
            status="READY",
            metrics={"skipped_by_operator": True},
            thresholds={},
            findings=[
                {
                    "severity": "info",
                    "detail": "L5 disabled via include_l5=false; layer intentionally not evaluated",
                }
            ],
        ).to_dict()
    layer_paths.append(_write_layer("L5_tile_seam_shadow", l5_payload, layers_dir))

    artifact_input = inputs.get("artifact_assessment_json")
    artifact_output: Path | None = None
    artifact_auto_derived = False
    ledger_output: Path | None = None
    provider_compatibility: list[dict[str, Any]] | None = None
    artifact_error: str | None = None
    artifact_schema = (
        Path(__file__).resolve().parents[1]
        / "schemas"
        / "satim_artifact_assessment_v1.schema.json"
    )
    if _is_present(artifact_input):
        # Analyst-supplied assessment: fail-loud per the failure contract.
        from skywatcher.satim.artifacts.engine import ArtifactAssessmentEngine
        from skywatcher.satim.artifacts.schema_validator import ArtifactSchemaValidator

        artifact_payload = json.loads(artifact_input.read_text(encoding="utf-8"))
        ArtifactSchemaValidator(artifact_schema).require_valid(artifact_payload)
        artifact_output = run_dir / "artifact_assessment_result.json"
        write_json(
            artifact_output,
            ArtifactAssessmentEngine().assess(artifact_payload).to_dict(),
        )
    elif manifest.options.get("auto_artifact_assessment", True) and include_l5 and _is_present(
        l5_candidates
    ):
        # Best-effort auto-derivation from L5 candidate classification. This
        # path is purely additive: any failure is recorded but never breaks
        # the run or changes its status.
        try:
            from skywatcher.satim.artifacts.confidence_ledger import ConfidenceLedger
            from skywatcher.satim.artifacts.engine import ArtifactAssessmentEngine
            from skywatcher.satim.artifacts.pipeline_chain import (
                build_assessment_from_l5,
                build_ledger_entry,
            )
            from skywatcher.satim.artifacts.provider_registry import ProviderProfileRegistry
            from skywatcher.satim.artifacts.schema_validator import ArtifactSchemaValidator

            scored = [classify_candidate(row) for row in load_candidates(l5_candidates)]
            source_type = str(manifest.options.get("artifact_source_type", "screenshot"))
            payload = build_assessment_from_l5(scored, source_type=source_type)
            if payload is not None:
                ArtifactSchemaValidator(artifact_schema).require_valid(payload)
                result = ArtifactAssessmentEngine().assess(payload).to_dict()
                artifact_output = run_dir / "artifact_assessment_result.json"
                write_json(artifact_output, {"auto_derived": True, **result})
                artifact_auto_derived = True

                profiles_dir = Path(__file__).resolve().parents[1] / "profiles"
                if profiles_dir.is_dir():
                    registry = ProviderProfileRegistry()
                    registry.load_dir(profiles_dir)
                    provider_compatibility = [
                        {
                            "profile_id": profile_id,
                            "compatible": registry.compatible(profile_id, payload["source"]),
                        }
                        for profile_id in registry.profile_ids()
                    ]
                    write_json(
                        run_dir / "artifact_provider_compatibility.json",
                        provider_compatibility,
                    )

                ledger_output = run_dir / "confidence_ledger.jsonl"
                ConfidenceLedger(ledger_output).append(build_ledger_entry(payload, result))
        except Exception as exc:
            # Additive enrichment must never fail an otherwise-valid run.
            artifact_error = f"{type(exc).__name__}: {exc}"
            artifact_output = None
            artifact_auto_derived = False
            ledger_output = None
            provider_compatibility = None
            write_json(run_dir / "artifact_assessment_error.json", {"error": artifact_error})

    calibration_set_dir = inputs.get("calibration_set_dir")
    calibration_packet: dict[str, Any] | None = None
    if _is_present(calibration_set_dir):
        validation = validate_calibration_set(calibration_set_dir)  # type: ignore[arg-type]
        if manifest.options.get("strict") and validation["status"] == "FAIL":
            raise ValueError("calibration_set_dir failed validation")
        calibration_packet = {"validation": validation}
        score_payload = score_calibration_packet(calibration_set_dir)  # type: ignore[arg-type]
        if score_payload is not None:
            calibration_packet["score"] = score_payload
        write_json(run_dir / "calibration_set_validation.json", calibration_packet)

    calibration_report_path = run_dir / "calibration_report.json"
    report = merge_layer_reports(layer_paths, calibration_report_path)

    legacy_path: Path | None = None
    if manifest.options.get("export_legacy_readiness", True):
        legacy_path = run_dir / "legacy_readiness.json"
        write_json(legacy_path, satim_report_to_legacy_calibration(report))

    provenance = build_provenance(manifest)
    write_json(run_dir / "provenance.json", provenance)

    summary = {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": manifest.run_id,
        "status": report.get("overall_status"),
        "blocking_gaps": report.get("blocking_gaps", []),
        "recommended_next_actions": report.get("recommended_next_actions", []),
        "outputs": {
            "run_dir": str(run_dir),
            "calibration_report": str(calibration_report_path),
            "legacy_readiness": str(legacy_path) if legacy_path else None,
            "provenance": str(run_dir / "provenance.json"),
            "calibration_set_validation": str(run_dir / "calibration_set_validation.json") if calibration_packet else None,
            "artifact_assessment": str(artifact_output) if artifact_output else None,
            "artifact_assessment_auto_derived": artifact_auto_derived,
            "confidence_ledger": str(ledger_output) if ledger_output else None,
            "artifact_provider_compatibility": provider_compatibility,
            "artifact_assessment_error": artifact_error,
        },
    }
    write_json(run_dir / "run_summary.json", summary)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the SATIM engine protocol interface")
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="Run SATIM from a manifest or input bundle")
    run.add_argument("--manifest", help="SATIM manifest YAML/JSON")
    run.add_argument("--input", help="Input directory or zip bundle to autodetect")
    run.add_argument("--output", required=True, help="Output run directory")
    run.add_argument("--strict", action="store_true", help="Fail on missing required L1-L3 inputs")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.print_help()
        return 2
    if not args.manifest and not args.input:
        parser.error("one of --manifest or --input is required")

    manifest = load_manifest(args.manifest) if args.manifest else manifest_from_input(args.input, args.output)
    if args.strict:
        manifest = SATIMEngineManifest(
            schema_version=manifest.schema_version,
            run_id=manifest.run_id,
            input_profile=manifest.input_profile,
            inputs=manifest.inputs,
            options={**manifest.options, "strict": True},
            outputs={**manifest.outputs, "run_dir": Path(args.output).expanduser().resolve()},
            source_manifest=manifest.source_manifest,
        )
    elif args.output:
        manifest = SATIMEngineManifest(
            schema_version=manifest.schema_version,
            run_id=manifest.run_id,
            input_profile=manifest.input_profile,
            inputs=manifest.inputs,
            options=manifest.options,
            outputs={**manifest.outputs, "run_dir": Path(args.output).expanduser().resolve()},
            source_manifest=manifest.source_manifest,
        )

    summary = run_satim_engine(manifest, args.output)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
