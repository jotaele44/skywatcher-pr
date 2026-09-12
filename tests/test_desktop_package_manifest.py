from pathlib import Path


def test_desktop_bundle_includes_core_runtime_and_evidence() -> None:
    spec = Path("desktop/pyinstaller.spec").read_text(encoding="utf-8")

    for required in ("collect_submodules", '"configs"', '"data/geo"', '"data/rlsm"'):
        assert required in spec
