import zipfile
import tarfile
import os
import tempfile
import logging

logger = logging.getLogger(__name__)


def extract_archive(filepath: str, output_dir: str = None) -> list:
    """Extract a ZIP or TAR archive and return list of extracted file paths.

    Creates a temporary directory if output_dir is not provided.
    Returns only file paths (not directories).
    """
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix='pr_intel_extract_')

    os.makedirs(output_dir, exist_ok=True)
    extracted_files = []

    try:
        if zipfile.is_zipfile(filepath):
            with zipfile.ZipFile(filepath, 'r') as zf:
                zf.extractall(output_dir)
                extracted_files = [
                    os.path.join(output_dir, name)
                    for name in zf.namelist()
                    if not name.endswith('/')
                ]
            logger.info(f"Extracted ZIP {filepath}: {len(extracted_files)} files to {output_dir}")

        elif tarfile.is_tarfile(filepath):
            with tarfile.open(filepath, 'r:*') as tf:
                tf.extractall(output_dir)
                extracted_files = [
                    os.path.join(output_dir, member.name)
                    for member in tf.getmembers()
                    if member.isfile()
                ]
            logger.info(f"Extracted TAR {filepath}: {len(extracted_files)} files to {output_dir}")

        else:
            logger.warning(f"Unrecognised archive format: {filepath}")

    except Exception as e:
        logger.error(f"Failed to extract archive {filepath}: {e}")
        raise

    return extracted_files
