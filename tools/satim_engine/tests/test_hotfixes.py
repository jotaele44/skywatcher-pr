import hashlib
import zipfile
from pathlib import Path

from satim_engine.graph import build_graph_from_ledgers
from satim_engine.inventory import extract_zips, build_manifest
from satim_engine.tracks import parse_gpx_coordinates, parse_track_file

import pandas as pd


def test_gpx_parser_dispatch(tmp_path):
    f = tmp_path / "track.gpx"
    f.write_text("""<?xml version='1.0'?><gpx><trk><trkseg><trkpt lat='18.4' lon='-66.1'><ele>10</ele><time>2026-01-01T00:00:00Z</time></trkpt></trkseg></trk></gpx>""")
    df = parse_track_file(str(f))
    assert len(df) == 1
    assert float(df.iloc[0].latitude) == 18.4
    assert float(df.iloc[0].longitude) == -66.1


def test_graph_ids_are_stable():
    df = pd.DataFrame([{"source":"a.csv", "latitude":18.4, "longitude":-66.1, "verification_score":90}])
    n1, e1 = build_graph_from_ledgers(df)
    n2, e2 = build_graph_from_ledgers(df)
    assert n1.node_id.tolist() == n2.node_id.tolist()
    assert e1.target.tolist() == e2.target.tolist()


def test_extract_zips_clears_stale_files(tmp_path):
    inp = tmp_path / "input"
    out = tmp_path / "out"
    inp.mkdir()
    z = inp / "sample.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("track.csv", "lat,lon\n18.4,-66.1\n")
    extract_zips(str(inp), str(out))
    stale = out / "extracted" / "sample" / "stale.csv"
    stale.write_text("lat,lon\n0,0\n")
    extract_zips(str(inp), str(out))
    manifest = build_manifest(out / "extracted")
    assert not manifest.path.astype(str).str.contains("stale.csv").any()
