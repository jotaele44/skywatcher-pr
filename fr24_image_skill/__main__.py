from __future__ import annotations

import argparse
from pathlib import Path

from .orchestrator import AnalysisMode, RunOptions, run_analysis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Skywatcher FR24 two-stage image analysis")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run the two-stage workflow")
    run_parser.add_argument("input", type=Path)
    run_parser.add_argument("--output-dir", type=Path, required=True)
    run_parser.add_argument("--mode", choices=[mode.value for mode in AnalysisMode], default=AnalysisMode.STANDARD.value)

    # The remaining four have been declared in the skill's input.schema.json since it was
    # written but were never reachable from the command line, so the documented contract
    # and the actual interface disagreed. Defaults match the schema's.
    run_parser.add_argument(
        "--skip-stage-1",
        dest="execute_stage_1",
        action="store_false",
        help="Skip flight-evidence extraction. Stage 2 consumes stage 1's frozen output, so this also requires --skip-stage-2.",
    )
    run_parser.add_argument(
        "--skip-stage-2",
        dest="execute_stage_2",
        action="store_false",
        help="Skip SATIM imagery classification and stop after stage 1.",
    )
    run_parser.add_argument(
        "--external-verification",
        choices=["none", "provided_only", "acquire_when_available"],
        default="provided_only",
    )
    run_parser.add_argument(
        "--target-registration-rmse-m",
        type=float,
        default=10.0,
        help="Georegistration accuracy target in metres; must be greater than zero.",
    )
    run_parser.add_argument(
        "--output-geometry",
        choices=["none", "pixel_space", "geojson"],
        default="geojson",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "run":
        try:
            options = RunOptions(
                mode=AnalysisMode(args.mode),
                execute_stage_1=args.execute_stage_1,
                execute_stage_2=args.execute_stage_2,
                external_verification=args.external_verification,
                target_registration_rmse_m=args.target_registration_rmse_m,
                output_geometry=args.output_geometry,
            )
        except ValueError as exc:
            # Refuse an incoherent combination up front rather than producing a partial
            # run that looks complete.
            print(f"invalid options: {exc}")
            return 2
        run = run_analysis(args.input, args.output_dir, options=options)
        print(f"{run.run_id}: complete -> {run.output_dir}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
