from pathlib import Path

from tools.gatim.core.normalizer import extract_coords, normalize_many

FIXTURES = Path(__file__).parent / "fixtures" / "sanitized_seed"


def test_extract_decimal_coordinates():
    lat, lon, status, _ = extract_coords("https://www.google.com/maps/search/18.0244757,-66.6632832")
    assert status == "direct"
    assert lat == "18.0244757"
    assert lon == "-66.6632832"


def test_extract_dms_coordinates():
    lat, lon, status, _ = extract_coords("29°40'00.0\"N 65°35'00.0\"W")
    assert status == "direct"
    assert abs(float(lat) - 29.6666667) < 0.00001
    assert abs(float(lon) + 65.5833333) < 0.00001


def test_needs_geocode_status():
    rows = normalize_many([FIXTURES / "recon.csv"])
    assert rows[0].coord_status == "needs_geocode"
