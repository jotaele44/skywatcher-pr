"""FR24 temporal-wave exporter test (skywatcher-owned half).

The companion guardrail tests that assert the *spiderweb* static dashboard
(`dashboard/dashboard.html`, `scripts/export_static_dashboard.py`) does not
bundle the temporal-wave overlay remain in spiderweb-pr, where the dashboard
lives. Only the FR24 exporter check — which exercises a migrated fr24/ module —
belongs here.
"""

from __future__ import annotations

from pathlib import Path


def test_temporal_wave_exporter_can_still_generate_reference_artifact():
    exporter = Path("fr24/temporal_wave_dashboard_data.py").read_text(encoding="utf-8")

    assert "fr24_temporal_wave_dashboard.json" in exporter
    assert "TEMPORAL_DASHBOARD_DATA_VERSION" in exporter
    assert "candidate_only_no_auto_confirmation" in exporter
    assert "temporal_wave_candidate" in exporter
