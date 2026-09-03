from pathlib import Path

from satim_engine.inventory import classify


def test_classify_track():
    assert classify(Path("x.csv")) == "track_candidate"
    assert classify(Path("x.kml")) == "track_candidate"

def test_classify_visual():
    assert classify(Path("x.pdf")) == "visual_candidate"
    assert classify(Path("x.jpg")) == "visual_candidate"
