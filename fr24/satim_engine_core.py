"""Core implementation for the SATIM engine protocol runner."""

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
from .calibration.models import LayerCalibrationResult, merge_layer_reports, write_json
from .calibration.readiness_adapter import satim_report_to_legacy_calibration

try:  # pragma: no cover
    from satim_calibration import load_calibration_set, score_calibration_set
except Exception:  # pragma: no cover
    load_calibration_set = None  # type: ignore[assignment]
    score_calibration_set = None  # type: ignore[assignment]

try:  # pragma: no cover
    from scripts.validate_satim_calibration import validate_set as validate_calibration_packet_set
except Exception:  # pragma: no cover
    validate_calibration_packet_set = None  # type: ignore[assignment]

MANIFEST_SCHEMA_VERSION = "satim.engine.input.v1"
RUN_SCHEMA_VERSION = "satim.engine.run.v1"
BASE_REQUIRED_LAYERS = {"L1_ui_segmenter", "L2_route_extractor", "L3_vision_ocr"}

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
    root_path = Path(root).expanduser().resolve()
    for name in ("satim_manifest.yaml", "satim_manifest.yml", "satim_manifest.json"):
        candidate = root_path / name
        if candidate.is_file():
            return candidate
    return None


def prepare_input_root(input_path: str | Path, output_dir: str | Path) -> Path:
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
    root = prepare_input_root(input_path, output_dir)
    manifest_path = find_manifest(root)
    if manifest_path:
        return load_manifest(manifest_path)
    return SATIMEngineManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        run_id=Path(root).name or "satim_run",
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
    if validate_calibration_packet_set is None:
        return {
            "status": "SKIPPED",
            "errors": ["scripts.validate_satim_calibration.validate_set is unavailable"],
            "warnings": [],
        }
    errors, warnings = validate_calibration_packet_set(set_dir)
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "warnings": warnings}


def score_calibration_packet(set_dir: Path) -> dict[str, Any] | None:
    if load_calibration_set is None or score_calibration_set is None:
        return None
    try:
        return score_calibration_set(load_calibration_set(set_dir))
    except Exception as exc:
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
    inputs: list[dict[str, Any]] = []
    for key, path in sorted(manifest.inputs.items()):
        if not path.exists():
            inputs.append({"name": key, "path": str(path), "exists": False})
        elif path.is_dir():
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
    if bool(manifest.options.get("include_l5", True)):
        missing = _require_or_missing(manifest, "L5_tile_seam_shadow", {"l5_candidates_csv": l5_candidates})
        l5_payload = missing_layer("L5_tile_seam_shadow", missing) if missing else calibrate_l5(str(l5_candidates))
        layer_paths.append(_write_layer("L5_tile_seam_shadow", l5_payload, layers_dir))

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

    write_json(run_dir / "provenance.json", build_provenance(manifest))
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
    if args.strict or args.output:
        manifest = SATIMEngineManifest(
            schema_version=manifest.schema_version,
            run_id=manifest.run_id,
            input_profile=manifest.input_profile,
            inputs=manifest.inputs,
            options={**manifest.options, "strict": True} if args.strict else manifest.options,
            outputs={**manifest.outputs, "run_dir": Path(args.output).expanduser().resolve()},
            source_manifest=manifest.source_manifest,
        )

    print(json.dumps(run_satim_engine(manifest, args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
