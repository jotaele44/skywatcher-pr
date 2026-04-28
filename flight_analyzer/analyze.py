"""
CLI entry point for FlightRadar24 screenshot flight-purpose classifier.

Usage:
    python -m flight_analyzer.analyze \\
        --input  /path/to/screenshots \\
        --output results.csv \\
        --openai-key sk-... \\
        [--recursive] \\
        [--flagged-only] \\
        [--verbose]

Environment variable OPENAI_API_KEY is used as fallback if --openai-key is omitted.

--flagged-only writes a second CSV (stem.flagged.csv) containing only rows where
purpose_label is surveillance_recon, military_law_enforcement, or search_rescue.
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from .classifier import classify_flight
from .ocr_extractor import extract_text
from .output import build_row, open_csv, write_error_row

_IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif'}

_FLAGGED_LABELS = {'surveillance_recon', 'military_law_enforcement', 'search_rescue'}
_EASYOCR_CACHE = Path.home() / '.EasyOCR' / 'model'


def _collect_images(input_dir: str, recursive: bool) -> list:
    """Return sorted list of image paths under *input_dir*."""
    root = Path(input_dir)
    if not root.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_dir}")

    pattern = '**/*' if recursive else '*'
    paths = sorted(
        p for p in root.glob(pattern)
        if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES
    )
    return paths


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog='python -m flight_analyzer.analyze',
        description='Classify flight purpose from FlightRadar24 screenshots.',
    )
    parser.add_argument(
        '--input', '-i', required=True,
        help='Directory containing screenshot images.',
    )
    parser.add_argument(
        '--output', '-o', default='flight_analysis.csv',
        help='Output CSV file path (default: flight_analysis.csv).',
    )
    parser.add_argument(
        '--openai-key', default=None,
        help='OpenAI API key. Falls back to OPENAI_API_KEY environment variable.',
    )
    parser.add_argument(
        '--recursive', '-r', action='store_true',
        help='Scan subdirectories recursively.',
    )
    parser.add_argument(
        '--flagged-only', '-f', action='store_true',
        help=(
            'Also write a <output>.flagged.csv containing only surveillance_recon, '
            'military_law_enforcement, and search_rescue rows.'
        ),
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Print per-file progress and results.',
    )
    return parser.parse_args(argv)


def run(argv=None) -> int:
    args = _parse_args(argv)

    api_key = args.openai_key or os.environ.get('OPENAI_API_KEY', '')
    if not api_key:
        print('ERROR: OpenAI API key required. Use --openai-key or set OPENAI_API_KEY.',
              file=sys.stderr)
        return 1

    try:
        images = _collect_images(args.input, args.recursive)
    except NotADirectoryError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1

    if not images:
        print(f'No image files found in: {args.input}', file=sys.stderr)
        return 1

    if not _EASYOCR_CACHE.exists():
        print('Note: EasyOCR model weights (~1.5 GB) will be downloaded on first run.')

    print(f'Found {len(images)} image(s). Writing results to: {args.output}')

    # Optionally open a second CSV for flagged rows only
    flagged_path = None
    flagged_fh = flagged_writer = None
    if args.flagged_only:
        p = Path(args.output)
        flagged_path = str(p.with_name(p.stem + '.flagged' + p.suffix))
        flagged_fh, flagged_writer = open_csv(flagged_path)
        print(f'Flagged-only output : {flagged_path}')

    label_counts: Counter = Counter()
    flagged_count = 0
    error_count = 0

    fh, writer = open_csv(args.output)

    try:
        for idx, img_path in enumerate(images, start=1):
            filename = img_path.name
            prefix = f'[{idx}/{len(images)}] {filename}'

            # --- OCR step ---
            try:
                ocr_fields = extract_text(str(img_path))
            except Exception as exc:
                msg = f'OCR failed: {exc}'
                print(f'{prefix}  ERROR  {msg}', file=sys.stderr)
                write_error_row(writer, filename, msg)
                error_count += 1
                continue

            # --- Classification step ---
            try:
                classification = classify_flight(str(img_path), ocr_fields, api_key)
            except RuntimeError as exc:
                msg = str(exc)
                print(f'{prefix}  ERROR  {msg}', file=sys.stderr)
                write_error_row(writer, filename, msg)
                error_count += 1
                continue

            row = build_row(filename, ocr_fields, classification)
            writer.writerow(row)

            label = classification['purpose_label']
            conf = classification['confidence']
            label_counts[label] += 1

            if label in _FLAGGED_LABELS and flagged_writer is not None:
                flagged_writer.writerow(row)
                flagged_count += 1

            if args.verbose:
                flag_marker = '  [FLAGGED]' if label in _FLAGGED_LABELS else ''
                print(f'{prefix}  {label}  (conf={conf:.2f})  '
                      f'route={classification["route_shape"]}{flag_marker}')
            else:
                print(f'{prefix}  →  {label}')

    finally:
        fh.close()
        if flagged_fh:
            flagged_fh.close()

    # Summary
    total = len(images)
    processed = total - error_count
    print(f'\n--- Summary ---')
    print(f'Processed : {processed}/{total}  ({error_count} error(s))')
    print(f'Output    : {args.output}')
    if flagged_path:
        print(f'Flagged   : {flagged_count} row(s) → {flagged_path}')
    print()
    for label, count in sorted(label_counts.items(), key=lambda x: -x[1]):
        flag = ' *' if label in _FLAGGED_LABELS else ''
        bar = '#' * count
        print(f'  {label:<30s}  {count:>3d}  {bar}{flag}')

    return 0 if error_count < total else 1


def main():
    sys.exit(run())


if __name__ == '__main__':
    main()
