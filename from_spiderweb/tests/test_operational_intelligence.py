"""Tests for operational_intelligence: Alert, AlertEngine, ReportGenerator."""

import sqlite3
from datetime import datetime

import pytest

from pipeline.operational_intelligence import (
    Alert,
    AlertCategory,
    AlertEngine,
    AlertSeverity,
    ReportGenerator,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_db(tmp_path):
    db = str(tmp_path / "oi_test.db")
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS flights (
            flight_id TEXT PRIMARY KEY, callsign TEXT,
            takeoff_time TEXT, flight_duration_minutes INTEGER,
            origin_airport TEXT, destination_airport TEXT,
            max_altitude_ft INTEGER, avg_speed_mph REAL, mission_type TEXT
        );
        CREATE TABLE IF NOT EXISTS alerts (
            alert_id TEXT PRIMARY KEY, flight_id TEXT, callsign TEXT,
            category TEXT, severity TEXT, title TEXT, description TEXT,
            evidence TEXT, timestamp TEXT, recommended_action TEXT,
            auto_resolved INTEGER DEFAULT 0, acknowledged INTEGER DEFAULT 0,
            acknowledged_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS validation_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_id TEXT, check_type TEXT, passed INTEGER,
            description TEXT, details TEXT, validated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS extraction_confidence (
            id TEXT PRIMARY KEY, image_filename TEXT, field_name TEXT,
            extracted_value TEXT, ocr_confidence REAL, validation_score REAL,
            consistency_score REAL, combined_confidence REAL,
            extraction_method TEXT, recorded_at TEXT
        );
        CREATE TABLE IF NOT EXISTS cluster_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_id TEXT, cluster_label TEXT
        );
    """)
    conn.commit()
    conn.close()
    return db


def _alert(**kw):
    defaults = dict(
        alert_id="T001", flight_id="F001", callsign="N5854Z",
        category=AlertCategory.UNKNOWN_AIRCRAFT, severity=AlertSeverity.MEDIUM,
        title="Test", description="Test desc", evidence=["e1"],
        timestamp="2024-03-15T08:00:00", recommended_action="Monitor",
    )
    defaults.update(kw)
    return Alert(**defaults)


# ── Alert ─────────────────────────────────────────────────────────────────────

def test_alert_to_dict_has_required_keys():
    d = _alert().to_dict()
    for key in ["alert_id", "flight_id", "callsign", "category", "severity",
                "title", "description", "evidence", "timestamp",
                "recommended_action", "auto_resolved"]:
        assert key in d


def test_alert_to_dict_serializes_enums_as_strings():
    d = _alert(category=AlertCategory.EXTENDED_OPERATION,
               severity=AlertSeverity.HIGH).to_dict()
    assert isinstance(d["category"], str)
    assert isinstance(d["severity"], str)


def test_alert_evidence_is_list():
    d = _alert(evidence=["a", "b"]).to_dict()
    assert isinstance(d["evidence"], list)


# ── AlertEngine ───────────────────────────────────────────────────────────────

def test_known_callsign_no_unknown_alert(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    flight = {"flight_id": "F1", "callsign": "N5854Z",
              "takeoff_time": "2024-03-15T09:00:00", "flight_duration_minutes": 90}
    alerts = engine.evaluate_flight(flight, [], [])
    assert AlertCategory.UNKNOWN_AIRCRAFT not in [a.category for a in alerts]


def test_unknown_callsign_generates_alert(tmp_path):
    db = _make_db(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO flights VALUES ('F2','ZZZUNKNOWN','2024-03-15T09:00:00',30,null,null,null,null,null)"
    )
    conn.commit()
    conn.close()
    engine = AlertEngine(db)
    flight = {"flight_id": "F2", "callsign": "ZZZUNKNOWN",
              "takeoff_time": "2024-03-15T09:00:00", "flight_duration_minutes": 30}
    alerts = engine.evaluate_flight(flight, [], [])
    assert AlertCategory.UNKNOWN_AIRCRAFT in [a.category for a in alerts]


def test_extended_operation_alert_generated(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    flight = {"flight_id": "F3", "callsign": "ZTEST",
              "takeoff_time": "2024-03-15T09:00:00", "flight_duration_minutes": 400}
    alerts = engine.evaluate_flight(flight, [], [])
    assert AlertCategory.EXTENDED_OPERATION in [a.category for a in alerts]


def test_extended_operation_not_triggered_for_short_flight(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    flight = {"flight_id": "F4", "callsign": "ZTEST",
              "takeoff_time": "2024-03-15T09:00:00", "flight_duration_minutes": 60}
    alerts = engine.evaluate_flight(flight, [], [])
    assert AlertCategory.EXTENDED_OPERATION not in [a.category for a in alerts]


def test_night_operation_alert_for_known_non_night_operator(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    flight = {"flight_id": "F5", "callsign": "N5854Z",
              "takeoff_time": "2024-03-15T02:00:00", "flight_duration_minutes": 60}
    alerts = engine.evaluate_flight(flight, [], [])
    assert AlertCategory.NIGHT_OPERATION in [a.category for a in alerts]


def test_daytime_operation_no_night_alert(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    flight = {"flight_id": "F6", "callsign": "N5854Z",
              "takeoff_time": "2024-03-15T10:00:00", "flight_duration_minutes": 60}
    alerts = engine.evaluate_flight(flight, [], [])
    assert AlertCategory.NIGHT_OPERATION not in [a.category for a in alerts]


def test_restricted_airspace_alert_from_anomaly(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    flight = {"flight_id": "F7", "callsign": "N5854Z",
              "takeoff_time": "2024-03-15T09:00:00", "flight_duration_minutes": 60}
    anomalies = [{"type": "restricted_airspace_entry", "infrastructure": "MCAS Borinquen"}]
    alerts = engine.evaluate_flight(flight, [], anomalies)
    assert AlertCategory.RESTRICTED_AIRSPACE in [a.category for a in alerts]


def test_save_alerts_persists_to_db(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    a = _alert(alert_id="SAVE_001", flight_id="F", callsign="X")
    engine.save_alerts([a])
    conn = sqlite3.connect(db)
    count = conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE alert_id='SAVE_001'"
    ).fetchone()[0]
    conn.close()
    assert count == 1


def test_save_alerts_idempotent(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    a = _alert(alert_id="IDEM_001")
    engine.save_alerts([a])
    engine.save_alerts([a])
    conn = sqlite3.connect(db)
    count = conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE alert_id='IDEM_001'"
    ).fetchone()[0]
    conn.close()
    assert count == 1


def test_alerts_sorted_by_severity(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    flight = {"flight_id": "F8", "callsign": "ZTEST",
              "takeoff_time": "2024-03-15T02:00:00", "flight_duration_minutes": 400}
    alerts = engine.evaluate_flight(flight, [], [])
    # Multiple alerts generated — first should be highest severity
    if len(alerts) >= 2:
        sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
        for i in range(len(alerts) - 1):
            assert (sev_order.get(alerts[i].severity.value, 99) <=
                    sev_order.get(alerts[i+1].severity.value, 99))


# ── ReportGenerator ───────────────────────────────────────────────────────────

def test_daily_report_returns_string(tmp_path):
    rg = ReportGenerator(_make_db(tmp_path))
    assert isinstance(rg.daily_report(), str)


def test_daily_report_contains_header(tmp_path):
    rg = ReportGenerator(_make_db(tmp_path))
    assert "DAILY OPERATIONAL REPORT" in rg.daily_report()


def test_daily_report_counts_flights(tmp_path):
    db = _make_db(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO flights VALUES "
        "('F1','N5854Z','2024-03-15T09:00:00',60,'SJU','PSE',3500,120.0,'INFRA')"
    )
    conn.commit()
    conn.close()
    rg = ReportGenerator(db)
    report = rg.daily_report(datetime(2024, 3, 15))
    assert "Total flights:" in report


def test_aircraft_profile_report_returns_string(tmp_path):
    rg = ReportGenerator(_make_db(tmp_path))
    report = rg.aircraft_profile_report("N5854Z")
    assert isinstance(report, str)
    assert "N5854Z" in report


# ── Phase 5: AlertEngine new methods ─────────────────────────────────────────

def test_get_active_alerts_returns_list(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    alerts = engine.get_active_alerts()
    assert isinstance(alerts, list)


def test_get_active_alerts_excludes_acknowledged(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    flight = {"flight_id": "FLT_X", "callsign": "XTEST"}
    generated = engine._rule_unknown_aircraft(flight)
    engine.save_alerts(generated)
    assert len(engine.get_active_alerts()) >= 1
    alert_id = generated[0].alert_id
    engine.acknowledge_alert(alert_id)
    active = [a for a in engine.get_active_alerts() if a["alert_id"] == alert_id]
    assert len(active) == 0


def test_acknowledge_alert_returns_true(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    flight = {"flight_id": "FLT_ACK", "callsign": "ACKTEST"}
    alerts = engine._rule_unknown_aircraft(flight)
    engine.save_alerts(alerts)
    result = engine.acknowledge_alert(alerts[0].alert_id)
    assert result is True


def test_acknowledge_nonexistent_alert_returns_false(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    assert engine.acknowledge_alert("no-such-id") is False


def test_auto_resolve_stale_alerts_returns_int(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    resolved = engine.auto_resolve_stale_alerts(days=7)
    assert isinstance(resolved, int)
    assert resolved >= 0


def test_auto_resolve_resolves_old_alert(tmp_path):
    import sqlite3 as _sqlite3
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    flight = {"flight_id": "FLT_OLD", "callsign": "OLDTEST"}
    alerts = engine._rule_unknown_aircraft(flight)
    engine.save_alerts(alerts)
    # Backdate the alert timestamp to 10 days ago
    conn = _sqlite3.connect(db)
    from datetime import timedelta
    old_ts = (datetime(2020, 1, 1)).isoformat()
    conn.execute("UPDATE alerts SET timestamp=? WHERE alert_id=?",
                 (old_ts, alerts[0].alert_id))
    conn.commit()
    conn.close()
    resolved = engine.auto_resolve_stale_alerts(days=7)
    assert resolved >= 1


def test_is_duplicate_false_when_no_prior_alert(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    assert engine.is_duplicate("NO_FLIGHT", "Unknown/Unidentified Aircraft") is False


def test_is_duplicate_true_after_save(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    flight = {"flight_id": "FLT_DUP", "callsign": "DUPTEST"}
    alerts = engine._rule_unknown_aircraft(flight)
    engine.save_alerts(alerts)
    assert engine.is_duplicate("FLT_DUP", "Unknown/Unidentified Aircraft") is True


def test_export_alerts_json_creates_file(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    flight = {"flight_id": "FLT_EXP", "callsign": "EXPTEST"}
    engine.save_alerts(engine._rule_unknown_aircraft(flight))
    out = str(tmp_path / "alerts.json")
    count = engine.export_alerts_json(out, days=30)
    assert isinstance(count, int)
    import json
    data = json.loads(open(out).read())
    assert "alerts" in data
    assert "exported_at" in data


# ── Phase 5: ReportGenerator new methods ─────────────────────────────────────

def test_severity_breakdown_returns_dict(tmp_path):
    db = _make_db(tmp_path)
    rg = ReportGenerator(db)
    result = rg.severity_breakdown(days=30)
    assert isinstance(result, dict)


def test_severity_breakdown_counts_match_alerts(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    flight = {"flight_id": "FLT_SB", "callsign": "SBTEST"}
    engine.save_alerts(engine._rule_unknown_aircraft(flight))
    rg = ReportGenerator(db)
    breakdown = rg.severity_breakdown(days=30)
    total = sum(breakdown.values())
    assert total >= 1


def test_top_callsigns_by_alert_count_returns_list(tmp_path):
    db = _make_db(tmp_path)
    rg = ReportGenerator(db)
    result = rg.top_callsigns_by_alert_count(days=30)
    assert isinstance(result, list)


def test_top_callsigns_has_callsign_key(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    flight = {"flight_id": "FLT_TC", "callsign": "TCTEST"}
    engine.save_alerts(engine._rule_unknown_aircraft(flight))
    rg = ReportGenerator(db)
    results = rg.top_callsigns_by_alert_count(days=30)
    assert len(results) >= 1
    assert "callsign" in results[0]
    assert "alert_count" in results[0]


def test_weekly_report_returns_string(tmp_path):
    rg = ReportGenerator(_make_db(tmp_path))
    report = rg.weekly_report()
    assert isinstance(report, str)
    assert "WEEKLY" in report


# ── Phase 10: Observability ───────────────────────────────────────────────────

def test_get_alert_stats_returns_dict(tmp_path):
    engine = AlertEngine(_make_db(tmp_path))
    stats = engine.get_alert_stats()
    assert isinstance(stats, dict)
    assert "total" in stats
    assert "by_severity" in stats
    assert "by_category" in stats


def test_get_alert_stats_counts_saved_alerts(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    now = datetime.utcnow().isoformat()
    engine.save_alerts([
        _alert(alert_id="A1", severity=AlertSeverity.MEDIUM,
               category=AlertCategory.UNUSUAL_BEHAVIOR, timestamp=now),
        _alert(alert_id="A2", severity=AlertSeverity.HIGH,
               category=AlertCategory.RESTRICTED_AIRSPACE, timestamp=now),
    ])
    stats = engine.get_alert_stats()
    assert stats["total"] == 2


def test_get_alert_stats_acknowledged_count(tmp_path):
    db = _make_db(tmp_path)
    engine = AlertEngine(db)
    now = datetime.utcnow().isoformat()
    engine.save_alerts([_alert(alert_id="B1", timestamp=now)])
    alerts = engine.get_active_alerts()
    engine.acknowledge_alert(alerts[0]["alert_id"])
    stats = engine.get_alert_stats()
    assert stats["acknowledged"] == 1


def test_get_alert_stats_zero_when_empty(tmp_path):
    engine = AlertEngine(_make_db(tmp_path))
    stats = engine.get_alert_stats()
    assert stats["total"] == 0
    assert stats["acknowledged"] == 0
