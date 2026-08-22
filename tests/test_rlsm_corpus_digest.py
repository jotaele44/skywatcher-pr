from __future__ import annotations

from pathlib import Path

from PIL import Image

from fr24 import rlsm_corpus_ingest as corpus


def test_identical_rerun_keeps_same_corpus_digest(tmp_path: Path) -> None:
    baseline = tmp_path / "data" / "FR24_baseline"
    archives = tmp_path / "data" / "FR24_archives"
    database = tmp_path / "data" / "rlsm" / "test.sqlite"
    output = tmp_path / "outputs" / "rlsm_corpus"
    image_path = baseline / "2026-08" / "capture.png"
    image_path.parent.mkdir(parents=True)
    archives.mkdir(parents=True)
    Image.new("RGB", (16, 16), (20, 30, 40)).save(image_path)

    first = corpus.run(
        db_path=database,
        repo_root=tmp_path,
        baseline=baseline,
        archive_roots=[archives],
        output_dir=output,
    )
    second = corpus.run(
        db_path=database,
        repo_root=tmp_path,
        baseline=baseline,
        archive_roots=[archives],
        output_dir=output,
    )

    assert first["status"] == "PASS"
    assert second["status"] == "PASS"
    assert second["corpus_digest"] == first["corpus_digest"]
