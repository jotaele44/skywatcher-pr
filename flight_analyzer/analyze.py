"""
CLI entry point for FlightRadar24 screenshot flight-purpose classifier.

Usage:
    python -m flight_analyzer.analyze \\
        --input  /path/to/screenshots \\
        --output results.csv \\
        --openai-key sk-... \\
        [--recursive] \\
        [--flagged-only] \\
        [--resume] \\
        [--workers N] \\
        [--dry-run] \\
        [--verbose]

Environment variable OPENAI_API_KEY is used as fallback if --openai-key is omitted.

--flagged-only  Writes a second CSV (stem.flagged.csv) containing only rows where
                purpose_label is surveillance_recon, military_law_enforcement, or
                search_rescue.
--resume        Skip images whose filename already appears in the output CSV.
--workers N     Process N images concurrently (default 1 = sequential).
--dry-run       Run OCR only; skip the GPT-4o API call. Writes OCR fields to CSV
                with classification columns left blank.
"""

import argparse
import csv
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .classifier import classify_flight
from .fallback_classifier import classify_fallback
from .ocr_extractor import extract_text
from .output import CSV_COLUMNS, build_row, open_csv, write_error_row

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
        '--resume', action='store_true',
        help='Skip images whose filename already appears in the output CSV.',
    )
    parser.add_argument(
        '--workers', '-w', type=int, default=1, metavar='N',
        help='Number of concurrent worker threads (default: 1).',
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Run OCR only; skip GPT-4o call. Classification columns will be blank.',
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Print per-file progress and results.',
    )
    return parser.parse_args(argv)


def _load_already_processed(output_path: str) -> set:
    """Return set of filenames already present in an existing output CSV."""
    p = Path(output_path)
    if not p.exists():
        return set()
    try:
        with open(p, newline='', encoding='utf-8') as f:
            return {row['filename'] for row in csv.DictReader(f) if row.get('filename')}
    except Exception:
        return set()


def _process_one(img_path: Path, api_key: str, dry_run: bool) -> tuple:
    """
    Process a single image: OCR then (optionally) classify.
    Returns (filename, row_dict | None, error_msg | None).
    """
    filename = img_path.name
    try:
        ocr_fields = extract_text(str(img_path))
    except Exception as exc:
        return filename, None, f'OCR failed: {exc}'

    if dry_run:
        row = build_row(filename, ocr_fields, {})
        return filename, row, None

    try:
        classification = classify_flight(str(img_path), ocr_fields, api_key)
    except RuntimeError as exc:
        # API unavailable after retries — fall back to rule-based classification
        classification = classify_fallback(ocr_fields)
        classification['reasoning'] = (
            f'[API error: {exc}] ' + classification.get('reasoning', '')
        )

    row = build_row(filename, ocr_fields, classification)
    return filename, row, None


def run(argv=None) -> int:
    args = _parse_args(argv)

    api_key = args.openai_key or os.environ.get('OPENAI_API_KEY', '')
    if not api_key and not args.dry_run:
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

    # --resume: skip already-processed files
    skipped = 0
    if args.resume:
        already_done = _load_already_processed(args.output)
        if already_done:
            before = len(images)
            images = [p for p in images if p.name not in already_done]
            skipped = before - len(images)
            print(f'Resume: skipping {skipped} already-processed file(s).')
        if not images:
            print('All images already processed. Nothing to do.')
            return 0

    if not _EASYOCR_CACHE.exists():
        print('Note: EasyOCR model weights (~1.5 GB) will be downloaded on first run.')

    mode = 'dry-run (OCR only)' if args.dry_run else f'workers={args.workers}'
    print(f'Found {len(images)} image(s)  [{mode}]. Writing results to: {args.output}')

    # Optionally open a second CSV for flagged rows
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
    total = len(images)

    # Open output CSV in append mode when resuming, write mode otherwise
    open_mode = 'a' if (args.resume and Path(args.output).exists()) else 'w'
    if open_mode == 'a':
        fh = open(args.output, 'a', newline='', encoding='utf-8')
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction='ignore')
    else:
        fh, writer = open_csv(args.output)

    try:
        if args.workers > 1:
            futures = {}
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                for img_path in images:
                    fut = executor.submit(_process_one, img_path, api_key, args.dry_run)
                    futures[fut] = img_path

            # Collect in completion order
            results = []
            done_count = 0
            for fut in as_completed(futures):
                done_count += 1
                filename, row, err = fut.result()
                results.append((filename, row, err))
                print(f'[{done_count}/{total}] {filename}  → '
                      f'{"ERROR" if err else row.get("purpose_label", "ocr-only")}')

            # Write in original image order for deterministic output
            name_to_result = {fn: (r, e) for fn, r, e in results}
            for img_path in images:
                fn = img_path.name
                row, err = name_to_result[fn]
                if err:
                    write_error_row(writer, fn, err)
                    error_count += 1
                else:
                    writer.writerow(row)
                    label = row.get('purpose_label', '')
                    if label:
                        label_counts[label] += 1
                    if label in _FLAGGED_LABELS and flagged_writer:
                        flagged_writer.writerow(row)
                        flagged_count += 1
        else:
            for idx, img_path in enumerate(images, start=1):
                filename, row, err = _process_one(img_path, api_key, args.dry_run)
                prefix = f'[{idx}/{total}] {filename}'

                if err:
                    print(f'{prefix}  ERROR  {err}', file=sys.stderr)
                    write_error_row(writer, filename, err)
                    error_count += 1
                    continue

                writer.writerow(row)
                label = row.get('purpose_label', '')
                if label:
                    label_counts[label] += 1

                if label in _FLAGGED_LABELS and flagged_writer is not None:
                    flagged_writer.writerow(row)
                    flagged_count += 1

                if args.verbose:
                    flag_marker = '  [FLAGGED]' if label in _FLAGGED_LABELS else ''
                    conf = row.get('confidence', '')
                    shape = row.get('route_shape', '')
                    print(f'{prefix}  {label}  (conf={conf})  route={shape}{flag_marker}')
                else:
                    print(f'{prefix}  →  {label or "ocr-only"}')
    finally:
        fh.close()
        if flagged_fh:
            flagged_fh.close()

    processed = total - error_count
    print(f'\n--- Summary ---')
    print(f'Processed : {processed}/{total}  ({error_count} error(s))'
          + (f'  skipped {skipped}' if skipped else ''))
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
