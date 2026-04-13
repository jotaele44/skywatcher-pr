import tempfile
import logging

from core.ingest.detect import detect_format
from core.ingest.loaders.csv_loader import load_csv
from core.ingest.loaders.vector_loader import load_vector
from core.ingest.loaders.raster_loader import load_raster
from core.ingest.loaders.archive_extractor import extract_archive
from core.ingest.registry import register_loaded_file

logger = logging.getLogger(__name__)


def dispatch_file(filepath: str, extracted_dir: str = None) -> list:
    """Dispatch a file to the appropriate loader.

    Returns a list of DataFrames produced by loading the file.
    Archives are recursively dispatched after extraction.
    """
    fmt = detect_format(filepath)
    dataframes = []

    if fmt == 'csv':
        df = load_csv(filepath)
        register_loaded_file(filepath, fmt, len(df))
        dataframes.append(df)

    elif fmt == 'vector':
        df = load_vector(filepath)
        register_loaded_file(filepath, fmt, len(df))
        dataframes.append(df)

    elif fmt == 'raster':
        df = load_raster(filepath)
        register_loaded_file(filepath, fmt, len(df))
        dataframes.append(df)

    elif fmt == 'archive':
        if extracted_dir is None:
            extracted_dir = tempfile.mkdtemp(prefix='pr_intel_archive_')
        extracted_files = extract_archive(filepath, extracted_dir)
        register_loaded_file(filepath, fmt, len(extracted_files))
        for extracted_filepath in extracted_files:
            sub_dfs = dispatch_file(extracted_filepath, extracted_dir)
            dataframes.extend(sub_dfs)

    else:
        logger.warning(f"Skipping unsupported file format '{fmt}': {filepath}")

    return dataframes
