import os
import logging

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    '.csv':     'csv',
    '.shp':     'vector',
    '.gpkg':    'vector',
    '.geojson': 'vector',
    '.json':    'vector',
    '.kml':     'vector',
    '.tif':     'raster',
    '.tiff':    'raster',
    '.zip':     'archive',
    '.tar':     'archive',
    '.gz':      'archive',
}


def detect_format(filepath: str) -> str:
    """Detect the file format from the extension.

    Returns one of: 'csv', 'vector', 'raster', 'archive', 'unknown'.
    """
    _, ext = os.path.splitext(filepath.lower())
    fmt = SUPPORTED_EXTENSIONS.get(ext, 'unknown')
    logger.debug(f"Detected format for '{filepath}': {fmt}")
    return fmt


def scan_directory(directory: str) -> list:
    """Recursively scan a directory and return (filepath, format) tuples.

    Only returns files whose format is recognised (not 'unknown').
    """
    results = []

    if not os.path.isdir(directory):
        logger.warning(f"Directory does not exist: {directory}")
        return results

    for root, dirs, files in os.walk(directory):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for filename in files:
            if filename.startswith('.'):
                continue
            filepath = os.path.join(root, filename)
            fmt = detect_format(filepath)
            if fmt != 'unknown':
                results.append((filepath, fmt))

    logger.info(f"Found {len(results)} supported files in '{directory}'")
    return results
