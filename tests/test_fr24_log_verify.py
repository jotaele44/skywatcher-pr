"""Tests for fr24.log_verify — replay-aware flight-log verification."""

from datetime import date

import pytest

from fr24.log_verify import (
    extract_replay_date,
    normalize_tail,
    true_flight_date,
)

CAPTURE = date(2025, 10, 17)


class TestNormalizeTail:
    def test_nickname_stripped(self):
        assert normalize_tail('N196DM (“BlueBoy”)') == "N196DM"

    def test_plain(self):
        assert normalize_tail(" n999zy ") == "N999ZY"

    def test_empty(self):
        assert normalize_tail(None) is None
        assert normalize_tail("—") is None


class TestExtractReplayDate:
    def test_standard_bar(self):
        text = "REG. N999ZY ... Sun, Sep 28, 2025 | 9:28 AM UTC -04:00"
        assert extract_replay_date(text, CAPTURE) == date(2025, 9, 28)

    def test_pre_log_period_no_floor(self):
        # Regression: Jan 2025 replays viewed in Oct 2025 must parse (audit
        # 2026-06-03 found four mis-attributed flights from a floor at May 2025).
        text = "Fri, Jan 17, 2025 | 11:40 AM"
        assert extract_replay_date(text, CAPTURE) == date(2025, 1, 17)

    def test_future_date_rejected_as_noise(self):
        text = "Sat, Dec 20, 2025"
        assert extract_replay_date(text, CAPTURE) is None

    def test_live_view_no_bar(self):
        assert extract_replay_date("Departed 00:15 ago REG. N407PR", CAPTURE) is None

    def test_ocr_case_and_punct_tolerance(self):
        text = "WED. SEP 3 2025 timeline"
        assert extract_replay_date(text, CAPTURE) == date(2025, 9, 3)

    def test_invalid_calendar_date(self):
        assert extract_replay_date("Mon, Feb 30, 2025", CAPTURE) is None


class TestTrueFlightDate:
    def test_replay_shifts_date(self):
        flight, is_replay = true_flight_date(
            "2025-10-17T00:58:04-04:00", "Thu, Oct 16, 2025 2:49 PM"
        )
        assert flight == date(2025, 10, 16)
        assert is_replay is True

    def test_same_day_replay_keeps_date(self):
        flight, is_replay = true_flight_date(
            "2025-09-28T10:15:30-04:00", "Sun, Sep 28, 2025 9:28 AM"
        )
        assert flight == date(2025, 9, 28)
        assert is_replay is True

    def test_live_keeps_capture_date(self):
        flight, is_replay = true_flight_date("2025-10-11T09:44:41-04:00", "")
        assert flight == date(2025, 10, 11)
        assert is_replay is False


class TestVerifyEndToEnd:
    @pytest.fixture()
    def workspace(self, tmp_path):
        import openpyxl

        obs = tmp_path / "observations.csv"
        obs.write_text(
            "filename,filename_ts,registration,identity_status,raw_excerpt\n"
            # live obs on Oct 11 → confirms log entry of Oct 11
            "a.png,2025-10-11T09:44:41-04:00,N407PR,confirmed,Departed 00:09 ago\n"
            # replay viewed Oct 17 of an Oct 16 flight → confirms Oct 16 entry
            'b.png,2025-10-17T00:58:04-04:00,N999ZY,confirmed,"Thu, Oct 16, 2025"\n'
            # replay viewed Oct 17 of a pre-log Jan 17 flight → pre-log flag
            'c.png,2025-10-17T17:54:15-04:00,N196DM,recovered,"Fri, Jan 17, 2025"\n',
            encoding="utf-8",
        )

        log = tmp_path / "log.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "October"
        ws.append(["FN", "UF", "Date (AST)", "Time", "Tail / Callsign",
                   "Operator", "Route / POI Chain", "Behavior Notes", "Confidence"])
        ws.append(["FN-1", "UF-1", "2025-10-11", "09:40", "N407PR", "?", "", "", "High"])
        ws.append(["FN-2", "UF-2", "2025-10-16", "14:12", "N999ZY", "?", "", "", "High"])
        ws.append(["FN-3", "UF-3", "2025-10-18", "08:00", "N76LD", "?", "", "", "Low"])
        wb.save(log)
        return log, obs

    def test_verify_matches_and_flags(self, workspace):
        from fr24.log_verify import verify

        log, obs = workspace
        result = verify([log], obs, log_period_start="2025-05-03")

        confirmed_fns = {e["fn"] for e in result["confirmed"]}
        unconfirmed_fns = {e["fn"] for e in result["unconfirmed"]}
        assert confirmed_fns == {"FN-1", "FN-2"}
        assert unconfirmed_fns == {"FN-3"}

        # the Oct-16 confirmation must come from a replay observation
        fn2 = next(e for e in result["confirmed"] if e["fn"] == "FN-2")
        assert fn2["replay_obs_count"] == 1

        pre_log = {(p["flight_date"], p["tail"]) for p in result["pre_log_replays"]}
        assert ("2025-01-17", "N196DM") in pre_log
