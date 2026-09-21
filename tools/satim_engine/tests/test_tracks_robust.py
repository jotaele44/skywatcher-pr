import pandas as pd
import pytest

from satim_engine.tracks import NonTrackCSV, parse_csv_track, parse_kml_coordinates


def test_parse_lat_lon_aliases(tmp_path):
    f = tmp_path / "track.csv"
    f.write_text("Y,X,velocity\n18.1,-66.1,120\n")
    df = parse_csv_track(str(f))
    assert len(df) == 1
    assert float(df.iloc[0].latitude) == 18.1


def test_parse_fr24_position_schema(tmp_path):
    f = tmp_path / "fr24.csv"
    f.write_text(
        "Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction\n"
        '1766761782,2025-12-26T15:09:42Z,N540DB,"18.338324,-65.651604",250,35,333\n'
    )
    df = parse_csv_track(str(f))
    assert len(df) == 1
    assert float(df.iloc[0].latitude) == pytest.approx(18.338324)
    assert float(df.iloc[0].longitude) == pytest.approx(-65.651604)
    assert float(df.iloc[0].altitude) == 250
    assert float(df.iloc[0].speed) == 35
    assert float(df.iloc[0].heading) == 333
    assert df.iloc[0].callsign == "N540DB"


def test_parse_fr24_position_after_preamble(tmp_path):
    f = tmp_path / "preamble.csv"
    preamble = "\n".join(f"metadata row {i}" for i in range(75))
    f.write_text(
        preamble
        + "\nTimestamp,UTC,Callsign,Position,Altitude,Speed,Direction\n"
        + '1766761782,2025-12-26T15:09:42Z,N540DB,"18.338324,-65.651604",250,35,333\n'
    )
    df = parse_csv_track(str(f))
    assert len(df) == 1
    assert float(df.iloc[0].latitude) == pytest.approx(18.338324)


def test_parse_semicolon_split_coordinates(tmp_path):
    f = tmp_path / "semicolon.csv"
    f.write_text("time;latitude;longitude;speed\n2026-01-01T00:00:00Z;18.1;-66.1;120\n")
    df = parse_csv_track(str(f))
    assert len(df) == 1
    assert float(df.iloc[0].longitude) == pytest.approx(-66.1)


def test_parse_segment_table_as_ordered_endpoints(tmp_path):
    f = tmp_path / "segments.csv"
    f.write_text(
        "Mission_ID,Hash,Seg_ID,Start_Lat,Start_Lon,End_Lat,End_Lon,Len_m,Bearing_deg\n"
        "M1,abc,S1,18.1,-66.1,18.2,-66.2,1000,225\n"
    )
    df = parse_csv_track(str(f))
    assert len(df) == 2
    assert list(df.source_geometry) == ["segment_start", "segment_end"]
    assert float(df.iloc[0].latitude) == pytest.approx(18.1)
    assert float(df.iloc[1].longitude) == pytest.approx(-66.2)


def test_fr24_empty_track_is_not_header_failure(tmp_path):
    f = tmp_path / "empty.csv"
    f.write_text("Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction\n")
    with pytest.raises(NonTrackCSV, match="Empty track"):
        parse_csv_track(str(f))


def test_invalid_fr24_position_rows_fail_closed(tmp_path):
    f = tmp_path / "bad.csv"
    f.write_text(
        "Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction\n"
        '1,2026-01-01T00:00:00Z,N1,"181,-200",100,10,90\n'
    )
    with pytest.raises(NonTrackCSV, match="Empty track"):
        parse_csv_track(str(f))


def test_nontrack_csv_is_classified(tmp_path):
    f = tmp_path / "not_track.csv"
    f.write_text("name,value\na,1\n")
    with pytest.raises(NonTrackCSV):
        parse_csv_track(str(f))


def test_kml_point_lon_lat_alt_order(tmp_path):
    f = tmp_path / "point.kml"
    f.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><Point>'
        "<coordinates>-66.100891,18.456472,250</coordinates>"
        "</Point></Placemark></kml>"
    )
    df = parse_kml_coordinates(str(f))
    assert len(df) == 1
    assert float(df.iloc[0].latitude) == pytest.approx(18.456472)
    assert float(df.iloc[0].longitude) == pytest.approx(-66.100891)
    assert float(df.iloc[0].altitude) == pytest.approx(250)


def test_kml_linestring_without_point(tmp_path):
    f = tmp_path / "line.kml"
    f.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><LineString>'
        "<coordinates>-66.1,18.1,100 -66.2,18.2,200</coordinates>"
        "</LineString></Placemark></kml>"
    )
    df = parse_kml_coordinates(str(f))
    assert len(df) == 2


def test_kml_gx_track(tmp_path):
    f = tmp_path / "gx.kml"
    f.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2" '
        'xmlns:gx="http://www.google.com/kml/ext/2.2"><Placemark><gx:Track>'
        "<when>2026-01-01T00:00:00Z</when><gx:coord>-66.1 18.1 100</gx:coord>"
        "<when>2026-01-01T00:01:00Z</when><gx:coord>-66.2 18.2 200</gx:coord>"
        "</gx:Track></Placemark></kml>"
    )
    df = parse_kml_coordinates(str(f))
    assert len(df) == 2
    assert pd.notna(df.iloc[0].timestamp)


def test_metadata_only_kml_is_empty_track(tmp_path):
    f = tmp_path / "empty.kml"
    f.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        "<name>metadata only</name></Document></kml>"
    )
    with pytest.raises(ValueError, match="Empty track"):
        parse_kml_coordinates(str(f))
