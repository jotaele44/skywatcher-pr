from satim_engine.inventory import classify
from pathlib import Path

def test_classify_track():
    assert classify(Path("x.csv")) == "track_candidate"
    assert classify(Path("x.kml")) == "track_candidate"

def test_classify_visual():
    assert classify(Path("x.pdf")) == "visual_candidate"
    assert classify(Path("x.jpg")) == "visual_candidate"
