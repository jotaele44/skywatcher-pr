import pandas as pd
import logging

logger = logging.getLogger(__name__)


def validate_corridors(df: pd.DataFrame, G=None) -> dict:
    """Validate the spatial corridor DataFrame for completeness.

    Returns a dict with counts of invalid/missing rows and an overall
    validation_passed flag.
    """
    results = {
        'total_rows':        len(df),
        'valid_rows':        0,
        'invalid_rows':      0,
        'missing_lat':       0,
        'missing_lon':       0,
        'missing_cell_id':   0,
        'duplicate_latlon':  0,
        'validation_passed': False,
    }

    if len(df) == 0:
        logger.warning("validate_corridors: empty DataFrame")
        results['validation_passed'] = True
        return results

    results['missing_lat']     = int(df['lat'].isna().sum()) if 'lat' in df.columns else len(df)
    results['missing_lon']     = int(df['lon'].isna().sum()) if 'lon' in df.columns else len(df)
    results['missing_cell_id'] = int(df['cell_id'].isna().sum()) if 'cell_id' in df.columns else 0

    if 'lat' in df.columns and 'lon' in df.columns:
        results['duplicate_latlon'] = int(df.duplicated(subset=['lat', 'lon']).sum())

    results['invalid_rows']      = results['missing_lat'] + results['missing_lon']
    results['valid_rows']        = results['total_rows'] - results['invalid_rows']
    results['validation_passed'] = results['invalid_rows'] == 0

    logger.info(
        f"Corridor validation: {results['valid_rows']}/{results['total_rows']} valid rows"
        f" (passed={results['validation_passed']})"
    )
    return results


def report_validation(results: dict) -> None:
    """Print a formatted validation report to stdout."""
    status = "PASSED" if results.get('validation_passed') else "FAILED"
    print("\n=== CORRIDOR VALIDATION REPORT ===")
    for key, value in results.items():
        print(f"  {key:<26}: {value}")
    print(f"  {'STATUS':<26}: {status}")
    print("=" * 40)
