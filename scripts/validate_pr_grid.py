#!/usr/bin/env python3
import argparse, csv, hashlib, sys
from pathlib import Path

COLUMNS = ['Cell_ID','Row_Index','Column_Index','Pixel_X_Min','Pixel_Y_Min','Pixel_X_Max','Pixel_Y_Max','Centroid_X','Centroid_Y','Dark_Pixel_Count','Total_Pixel_Count','Land_Pixel_Ratio','Classification']
SHA = '17733f3f18c8a644e31c1eb25fb27b73b4bf353c6de57d5203c4311e05d64483'
CLASSES = {'Water_or_Empty','Gridline_Dominant','Coastline_or_Land'}

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--grid', default='registry/spatial/pr_grid_full_cell_index_saturated.csv')
    p.add_argument('--require-sha', action='store_true')
    a = p.parse_args()
    path = Path(a.grid)
    errors = []
    if not path.exists():
        errors.append(f'missing grid CSV: {path}')
    else:
        seen, rows, cols = set(), set(), set()
        with path.open('r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != COLUMNS:
                errors.append('unexpected columns')
            count = 0
            for row in reader:
                count += 1
                seen.add(row.get('Cell_ID',''))
                rows.add(int(row['Row_Index']))
                cols.add(int(row['Column_Index']))
                if row.get('Classification') not in CLASSES:
                    errors.append('unexpected classification')
                    break
        if count != 98304: errors.append('unexpected row count')
        if len(seen) != 98304: errors.append('unexpected unique Cell_ID count')
        if rows != set(range(256)): errors.append('row coverage failed')
        if cols != set(range(384)): errors.append('column coverage failed')
        if a.require_sha and sha(path) != SHA: errors.append('unexpected SHA-256')
    if errors:
        print('[FAIL] PR baseline grid validation failed', file=sys.stderr)
        for e in errors: print(f' - {e}', file=sys.stderr)
        return 1
    print('[OK] PR baseline grid validation passed')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
