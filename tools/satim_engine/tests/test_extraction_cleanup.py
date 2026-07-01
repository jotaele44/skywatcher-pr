import zipfile
from pathlib import Path
from satim_engine.inventory import extract_zips, build_manifest


def test_extract_zips_clears_stale_files(tmp_path):
    input_dir = tmp_path / "input"
    out_dir = tmp_path / "out"
    input_dir.mkdir()
    z = input_dir / "batch.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("track.csv", "lat,lon\n18.1,-66.1\n")
    extracted = extract_zips(str(input_dir), str(out_dir))
    stale = extracted / "batch" / "stale.csv"
    stale.write_text("lat,lon\n0,0\n")
    extracted = extract_zips(str(input_dir), str(out_dir))
    manifest = build_manifest(extracted)
    assert not any("stale.csv" in p for p in manifest.path)
