from satim_engine.config import load_config


def test_load_config_defaults_to_packaged_yaml():
    config = load_config()
    assert config["pairing"]["time_window_minutes"] == 30
    assert config["pairing"]["spatial_threshold_meters"] == 1500
    assert config["pairing"]["confidence_threshold_promote"] == 80
    assert config["scoring"]["verified"] == 95
    assert config["scoring"]["high_confidence"] == 80
    assert config["scoring"]["approximate"] == 60


def test_load_config_accepts_override_path(tmp_path):
    override = tmp_path / "custom.yml"
    override.write_text("pairing:\n  time_window_minutes: 5\n  spatial_threshold_meters: 10\n  confidence_threshold_promote: 50\nscoring:\n  verified: 90\n  high_confidence: 70\n  approximate: 50\n")
    config = load_config(override)
    assert config["pairing"]["time_window_minutes"] == 5
    assert config["scoring"]["verified"] == 90
