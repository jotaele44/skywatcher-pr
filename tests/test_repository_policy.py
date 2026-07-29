import stat
import zipfile
from pathlib import Path

from skywatcher.core.repository_export import export
from skywatcher.core.repository_policy import hygiene_violations


def test_hygiene_covers_generated_classes():
    paths = [
        "build/x",
        "dist/a.whl",
        "pkg.egg-info/PKG-INFO",
        "coverage.xml",
        "reports/maintenance/x.json",
    ]
    assert hygiene_violations(paths) == sorted(paths)


def test_export_preserves_executable_mode(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "source.zip"
    export(root, output)
    with zipfile.ZipFile(output) as archive:
        mode = (archive.getinfo("PRII-SKYWATCHER.sh").external_attr >> 16) & 0o777
    assert mode & stat.S_IXUSR
