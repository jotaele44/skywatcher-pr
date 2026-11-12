"""FAEI-V1 screenshot-only fixture integrity and non-promotion tests.

No network access; no FAA, flight-track or mission assertion is made.
"""
from __future__ import annotations

import json
import re
import unittest
from datetime import datetime
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures/faei/n852vb_oct2026_screenshots.v1.json"
SHA = re.compile(r"^[0-9a-f]{64}$")
PROHIBITED = {
    "rendered_map_track_is_raw_trajectory",
    "seven_dates_implies_seven_flights",
    "registered_owner_is_current_operator",
    "same_contract_region_proves_airframe_assignment",
    "maritime_track_is_uap_mission",
    "low_speed_implies_hover_or_landing",
}


class FAEIScreenshotFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_scoped_denominator_and_unique_manifestations(self) -> None:
        files = self.data["files"]
        self.assertEqual(len(files), self.data["denominators"]["uploaded_screenshots"])
        self.assertEqual(len(files), 5)
        self.assertEqual(len({f["name"] for f in files}), len(files))
        self.assertEqual(len({f["sha256"] for f in files}), len(files))
        for file in files:
            self.assertRegex(file["sha256"], SHA)
            self.assertGreater(file["bytes"], 0)

    def test_dated_ui_events_do_not_prove_distinct_sessions(self) -> None:
        dates = set()
        for file in self.data["files"]:
            if file["view"] is not None:
                dt = datetime.fromisoformat(file["view"])
                self.assertEqual(dt.utcoffset().total_seconds(), -4 * 3600)
                dates.add(dt.date().isoformat())
            dates.update(file.get("listed_dates", []))
        self.assertEqual(len(dates), 7)
        self.assertEqual(self.data["denominators"]["dated_calendar_entries_visible"], 7)
        self.assertEqual(self.data["denominators"]["distinct_flight_sessions"], "UNKNOWN")
        self.assertEqual(self.data["denominators"]["raw_telemetry_points"], "UNKNOWN")

    def test_contract_and_mission_not_promoted(self) -> None:
        self.assertEqual(self.data["denominators"]["aircraft_contract_direct_assignments"], 0)
        self.assertEqual(self.data["certification"], "WITHHELD")
        self.assertEqual(self.data["aircraft_claim_status"], "SCREENSHOT_ASSERTION_ONLY")
        self.assertEqual(set(self.data["must_not_certify"]), PROHIBITED)
        self.assertEqual(self.data["status"], "AUDIT_ONLY")

    def test_fixture_identity_fields_are_just_observations(self) -> None:
        obs = self.data["observed_identifiers"]
        self.assertEqual(obs["registration"], "N852VB")
        self.assertEqual(obs["mode_s"], "ABB0A3")
        self.assertEqual(obs["serial"], "VB-200147")
        self.assertEqual(obs["callsign"], "BATMAN47")
        self.assertEqual(obs["manufacturer_and_model_external_confirmation"], "OPEN_IN_THIS_FIXTURE")


if __name__ == "__main__":
    unittest.main()
