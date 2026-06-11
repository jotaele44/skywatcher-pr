"""
PHASE 4: OPERATIONAL INTELLIGENCE PLATFORM

Transforms: "Scored missions + GIS correlation"
       → "Actionable operational intelligence"

Components:
1. AlertEngine        — Rule-based triggers on anomalies, restrictions, patterns
2. ReportGenerator    — Automated daily/weekly operational summaries
3. OperationalDashboardData — Backend data layer for Phase 4 dashboard
"""

import sqlite3
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from enum import Enum


# ============================================================================
# ALERT SYSTEM
# ============================================================================

class AlertSeverity(Enum):
    INFO     = "INFO"
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


class AlertCategory(Enum):
    RESTRICTED_AIRSPACE  = "Restricted Airspace Entry"
    UNUSUAL_BEHAVIOR     = "Unusual Flight Behavior"
    INFRASTRUCTURE_PROX  = "Critical Infrastructure Proximity"
    UNKNOWN_AIRCRAFT     = "Unknown/Unidentified Aircraft"
    TEMPORAL_ANOMALY     = "Temporal Anomaly (Physics Violation)"
    PATTERN_DEVIATION    = "Pattern Deviation from Historical Norm"
    EXTENDED_OPERATION   = "Extended Operation (Possible Emergency)"
    NEW_AIRCRAFT         = "Previously Unseen Aircraft"
    NIGHT_OPERATION      = "Night Operation (Non-Emergency Operator)"
    CLUSTER_DEVIATION    = "Behavioral Cluster Deviation"


@dataclass
class Alert:
    alert_id: str
    flight_id: str
    callsign: str
    category: AlertCategory
    severity: AlertSeverity
    title: str
    description: str
    evidence: List[str]
    timestamp: str
    recommended_action: str
    auto_resolved: bool = False

    def to_dict(self) -> Dict:
        return {
            "alert_id": self.alert_id,
            "flight_id": self.flight_id,
            "callsign": self.callsign,
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "evidence": self.evidence,
            "timestamp": self.timestamp,
            "recommended_action": self.recommended_action,
            "auto_resolved": self.auto_resolved,
        }


class AlertEngine:
    def __init__(self, db_path: str = str(Path.home() / "flight_database.db")):
        self.db_path = db_path
        self._init_alert_tables()

    def _init_alert_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                alert_id TEXT PRIMARY KEY,
                flight_id TEXT,
                callsign TEXT,
                category TEXT,
                severity TEXT,
                title TEXT,
                description TEXT,
                evidence TEXT,
                timestamp TEXT,
                recommended_action TEXT,
                auto_resolved INTEGER DEFAULT 0,
                acknowledged INTEGER DEFAULT 0,
                acknowledged_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

    def evaluate_flight(self, flight: Dict, track_points: List[Dict],
                        anomalies: List[Dict]) -> List[Alert]:
        alerts = []
        alerts += self._rule_restricted_airspace(flight, anomalies)
        alerts += self._rule_unknown_aircraft(flight)
        alerts += self._rule_night_operation(flight)
        alerts += self._rule_extended_operation(flight)
        alerts += self._rule_infrastructure_proximity(flight, anomalies)
        alerts += self._rule_physics_violation(flight)
        alerts += self._rule_new_aircraft(flight)
        alerts += self._rule_low_confidence_extraction(flight)

        severity_order = {
            AlertSeverity.CRITICAL: 0, AlertSeverity.HIGH: 1,
            AlertSeverity.MEDIUM: 2, AlertSeverity.LOW: 3, AlertSeverity.INFO: 4,
        }
        alerts.sort(key=lambda a: severity_order[a.severity])
        return alerts

    def _rule_restricted_airspace(self, flight: Dict, anomalies: List[Dict]) -> List[Alert]:
        restricted = [a for a in anomalies
                      if a.get("type") == "restricted_airspace_entry" or
                         "restricted" in (a.get("infrastructure") or "").lower()]
        if not restricted:
            return []
        callsign = flight.get("callsign", "UNKNOWN")
        return [Alert(
            alert_id=f"RESTR_{flight['flight_id']}_{datetime.utcnow().strftime('%H%M%S')}",
            flight_id=flight.get("flight_id", ""),
            callsign=callsign,
            category=AlertCategory.RESTRICTED_AIRSPACE,
            severity=AlertSeverity.HIGH,
            title=f"{callsign} entered restricted airspace",
            description=f"Flight tracked within {len(restricted)} restricted zone(s)",
            evidence=[f"Near: {r.get('infrastructure', 'restricted zone')}" for r in restricted],
            timestamp=datetime.utcnow().isoformat(),
            recommended_action="Verify aircraft authorization. Cross-reference with FAA NOTAM.",
        )]

    def _rule_unknown_aircraft(self, flight: Dict) -> List[Alert]:
        known = ["N5854Z", "C6062", "N767PD", "N684JB"]
        callsign = flight.get("callsign", "")
        if any(k in callsign for k in known):
            return []
        return [Alert(
            alert_id=f"UNKN_{flight['flight_id']}",
            flight_id=flight.get("flight_id", ""),
            callsign=callsign,
            category=AlertCategory.UNKNOWN_AIRCRAFT,
            severity=AlertSeverity.MEDIUM,
            title=f"Unknown aircraft: {callsign}",
            description="Aircraft not in known operator database",
            evidence=[f"Callsign {callsign} has no registered operator profile"],
            timestamp=datetime.utcnow().isoformat(),
            recommended_action="Research N-number via FAA registry. Add operator profile if legitimate.",
        )]

    def _rule_night_operation(self, flight: Dict) -> List[Alert]:
        non_night_ops = ["N5854Z", "N684JB"]
        callsign = flight.get("callsign", "")
        if not any(n in callsign for n in non_night_ops):
            return []
        try:
            dt = datetime.fromisoformat(flight.get("takeoff_time", ""))
            hour = dt.hour
        except Exception:
            return []
        if 7 <= hour <= 19:
            return []
        return [Alert(
            alert_id=f"NIGHT_{flight['flight_id']}",
            flight_id=flight.get("flight_id", ""),
            callsign=callsign,
            category=AlertCategory.NIGHT_OPERATION,
            severity=AlertSeverity.LOW,
            title=f"{callsign} operating at night ({hour:02d}:00)",
            description="Non-emergency operator active outside typical hours",
            evidence=[f"Departure at hour {hour:02d}:00 UTC"],
            timestamp=datetime.utcnow().isoformat(),
            recommended_action="Confirm emergency or special operation. Update operator profile if pattern.",
        )]

    def _rule_extended_operation(self, flight: Dict) -> List[Alert]:
        duration = flight.get("flight_duration_minutes", 0) or 0
        callsign = flight.get("callsign", "")
        if duration <= 360:
            return []
        return [Alert(
            alert_id=f"EXTD_{flight['flight_id']}",
            flight_id=flight.get("flight_id", ""),
            callsign=callsign,
            category=AlertCategory.EXTENDED_OPERATION,
            severity=AlertSeverity.MEDIUM,
            title=f"{callsign} extended operation: {duration} minutes",
            description="Flight duration exceeds typical operational envelope",
            evidence=[f"Duration: {duration} minutes ({duration/60:.1f} hours)"],
            timestamp=datetime.utcnow().isoformat(),
            recommended_action="Verify no emergency situation. Check fuel/range constraints.",
        )]

    def _rule_infrastructure_proximity(self, flight: Dict,
                                       anomalies: List[Dict]) -> List[Alert]:
        critical = [a for a in anomalies
                    if (a.get("distance_nm") or 99) < 1.0 and
                       a.get("type") in ["power_substation", "restricted_airspace"]]
        if not critical:
            return []
        callsign = flight.get("callsign", "")
        closest = min(critical, key=lambda a: a.get("distance_nm") or 99)
        return [Alert(
            alert_id=f"INFRA_{flight['flight_id']}",
            flight_id=flight.get("flight_id", ""),
            callsign=callsign,
            category=AlertCategory.INFRASTRUCTURE_PROX,
            severity=AlertSeverity.MEDIUM,
            title=f"{callsign} within 1nm of critical infrastructure",
            description=f"Closest approach: {closest.get('infrastructure', 'facility')}",
            evidence=[f"{a.get('infrastructure','?')}: {(a.get('distance_nm') or 0):.2f} nm"
                      for a in critical],
            timestamp=datetime.utcnow().isoformat(),
            recommended_action="Verify operational authorization. Log for infrastructure security.",
        )]

    def _rule_physics_violation(self, flight: Dict) -> List[Alert]:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM validation_results WHERE flight_id = ? AND passed = 0",
                (flight.get("flight_id", ""),)
            )
            count = cursor.fetchone()[0]
            conn.close()
        except Exception:
            return []
        if count == 0:
            return []
        callsign = flight.get("callsign", "")
        return [Alert(
            alert_id=f"PHYS_{flight['flight_id']}",
            flight_id=flight.get("flight_id", ""),
            callsign=callsign,
            category=AlertCategory.TEMPORAL_ANOMALY,
            severity=AlertSeverity.LOW,
            title=f"{callsign}: {count} physics validation failures",
            description="Track points failed physical plausibility checks",
            evidence=[f"{count} points flagged for impossible motion"],
            timestamp=datetime.utcnow().isoformat(),
            recommended_action="Review raw screenshots for OCR corruption. Re-extract if needed.",
        )]

    def _rule_new_aircraft(self, flight: Dict) -> List[Alert]:
        callsign = flight.get("callsign", "")
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM flights WHERE callsign = ?", (callsign,))
            count = cursor.fetchone()[0]
            conn.close()
        except Exception:
            return []
        if count > 1:
            return []
        return [Alert(
            alert_id=f"NEW_{flight['flight_id']}",
            flight_id=flight.get("flight_id", ""),
            callsign=callsign,
            category=AlertCategory.NEW_AIRCRAFT,
            severity=AlertSeverity.INFO,
            title=f"New aircraft in airspace: {callsign}",
            description="First-time observation of this callsign",
            evidence=[f"No prior flights from {callsign} in database"],
            timestamp=datetime.utcnow().isoformat(),
            recommended_action="Research aircraft registration. Create operator profile.",
        )]

    def _rule_low_confidence_extraction(self, flight: Dict) -> List[Alert]:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT AVG(combined_confidence)
                FROM extraction_confidence
                WHERE image_filename LIKE ?
            ''', (f"%{flight.get('callsign', '')}%",))
            row = cursor.fetchone()
            conn.close()
            avg_confidence = row[0] if row and row[0] else None
        except Exception:
            return []
        if avg_confidence is None or avg_confidence >= 0.75:
            return []
        callsign = flight.get("callsign", "")
        return [Alert(
            alert_id=f"CONF_{flight['flight_id']}",
            flight_id=flight.get("flight_id", ""),
            callsign=callsign,
            category=AlertCategory.TEMPORAL_ANOMALY,
            severity=AlertSeverity.LOW,
            title=f"{callsign}: Low extraction confidence ({avg_confidence:.0%})",
            description="OCR confidence below acceptable threshold",
            evidence=[f"Average confidence: {avg_confidence:.2%}"],
            timestamp=datetime.utcnow().isoformat(),
            recommended_action="Manually verify extracted data against source screenshots.",
        )]

    def save_alerts(self, alerts: List[Alert]):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        for alert in alerts:
            d = alert.to_dict()
            cursor.execute('''
                INSERT OR IGNORE INTO alerts
                (alert_id, flight_id, callsign, category, severity, title,
                 description, evidence, timestamp, recommended_action)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                d["alert_id"], d["flight_id"], d["callsign"],
                d["category"], d["severity"], d["title"],
                d["description"], json.dumps(d["evidence"]),
                d["timestamp"], d["recommended_action"],
            ))
        conn.commit()
        conn.close()

    def get_active_alerts(self, limit: int = 100) -> List[Dict]:
        """Return unresolved, unacknowledged alerts ordered by severity then time."""
        severity_order = "CASE severity " \
            "WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 " \
            "WHEN 'LOW' THEN 3 ELSE 4 END"
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                f"SELECT * FROM alerts WHERE acknowledged=0 AND auto_resolved=0 "
                f"ORDER BY {severity_order}, timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def acknowledge_alert(self, alert_id: str, notes: str = "") -> bool:
        """Mark a single alert as acknowledged. Returns True if a row was updated."""
        conn = sqlite3.connect(self.db_path)
        try:
            affected = conn.execute(
                "UPDATE alerts SET acknowledged=1, acknowledged_at=? "
                "WHERE alert_id=?",
                (datetime.utcnow().isoformat(), alert_id),
            ).rowcount
            conn.commit()
        except Exception:
            affected = 0
        finally:
            conn.close()
        return affected > 0

    def auto_resolve_stale_alerts(self, days: int = 7) -> int:
        """Mark unacknowledged alerts older than *days* as auto_resolved.

        Returns the count of alerts resolved.
        """
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            affected = conn.execute(
                "UPDATE alerts SET auto_resolved=1 "
                "WHERE acknowledged=0 AND auto_resolved=0 AND timestamp < ?",
                (cutoff,),
            ).rowcount
            conn.commit()
        except Exception:
            affected = 0
        finally:
            conn.close()
        return affected

    def is_duplicate(self, flight_id: str, category: str,
                     within_hours: int = 24) -> bool:
        """Return True if an alert with the same (flight_id, category) was saved
        within the last *within_hours* hours."""
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(hours=within_hours)).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT 1 FROM alerts WHERE flight_id=? AND category=? AND timestamp >= ? LIMIT 1",
                (flight_id, category, cutoff),
            ).fetchone()
        except Exception:
            row = None
        finally:
            conn.close()
        return row is not None

    def export_alerts_json(self, output_path: str, days: int = 7) -> int:
        """Export alerts from the last *days* days to a JSON file.

        Returns the number of alerts written.
        """
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE timestamp >= ? ORDER BY timestamp DESC",
                (cutoff,),
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()

        alerts = []
        for r in rows:
            d = dict(r)
            try:
                d["evidence"] = json.loads(d.get("evidence") or "[]")
            except Exception:
                pass
            alerts.append(d)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(
            json.dumps({"exported_at": datetime.utcnow().isoformat(), "alerts": alerts}, indent=2),
            encoding="utf-8",
        )
        return len(alerts)

    def get_alert_stats(self, days: int = 30) -> Dict[str, Any]:
        """Return summary statistics for alerts in the last *days* days."""
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT severity, category, acknowledged, auto_resolved "
                "FROM alerts WHERE timestamp >= ?",
                (cutoff,),
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()

        total = len(rows)
        by_severity: Dict[str, int] = {}
        by_category: Dict[str, int] = {}
        acknowledged = 0
        auto_resolved = 0

        for r in rows:
            sev = r["severity"] or "unknown"
            cat = r["category"] or "unknown"
            by_severity[sev] = by_severity.get(sev, 0) + 1
            by_category[cat] = by_category.get(cat, 0) + 1
            if r["acknowledged"]:
                acknowledged += 1
            if r["auto_resolved"]:
                auto_resolved += 1

        return {
            "total":        total,
            "by_severity":  by_severity,
            "by_category":  by_category,
            "acknowledged": acknowledged,
            "auto_resolved": auto_resolved,
            "days":         days,
        }


# ============================================================================
# REPORT GENERATOR
# ============================================================================

class ReportGenerator:
    def __init__(self, db_path: str = str(Path.home() / "flight_database.db")):
        self.db_path = db_path

    def daily_report(self, date: datetime = None) -> str:
        if date is None:
            date = datetime.utcnow()
        date_str = date.strftime("%Y-%m-%d")
        start = f"{date_str}T00:00:00"
        end   = f"{date_str}T23:59:59"

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM flights WHERE takeoff_time BETWEEN ? AND ? ORDER BY takeoff_time",
            (start, end)
        )
        flights = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            "SELECT severity, COUNT(*) as count FROM alerts WHERE timestamp BETWEEN ? AND ? GROUP BY severity",
            (start, end)
        )
        alert_summary = {r["severity"]: r["count"] for r in cursor.fetchall()}

        cursor.execute('''
            SELECT callsign, COUNT(*) as flights,
                   SUM(flight_duration_minutes) as total_min,
                   MAX(max_altitude_ft) as peak_alt
            FROM flights WHERE takeoff_time BETWEEN ? AND ?
            GROUP BY callsign
        ''', (start, end))
        by_operator = [dict(r) for r in cursor.fetchall()]
        conn.close()

        lines = [
            "╔" + "═" * 68 + "╗",
            "║" + f"  DAILY OPERATIONAL REPORT — {date_str}".center(68) + "║",
            "╚" + "═" * 68 + "╝",
            "",
            "  FLIGHT ACTIVITY",
            "  ─────────────────────────────────────────────",
            f"  Total flights:     {len(flights)}",
        ]
        for op in by_operator:
            hours = (op.get("total_min") or 0) / 60
            lines.append(
                f"  {op['callsign']:<12}  {op['flights']} flights  "
                f"{hours:.1f}h  Peak: {op.get('peak_alt', 0):,} ft"
            )

        lines += ["", "  ALERTS", "  ─────────────────────────────────────────────"]
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            count = alert_summary.get(sev, 0)
            if count:
                lines.append(f"  {sev:<12} {count}")
        if not any(alert_summary.values()):
            lines.append("  No alerts generated today")

        lines += [
            "", "  FLIGHT LOG",
            "  ─────────────────────────────────────────────",
            f"  {'Callsign':<10} {'Dep':<6} {'Route':<12} {'Dur':<8} {'Mission'}",
            f"  {'─'*10} {'─'*6} {'─'*12} {'─'*8} {'─'*25}",
        ]
        for f in flights:
            dep_time = (f.get("takeoff_time") or "")[-8:][:5] or "N/A"
            route = f"{f.get('origin_airport','?')}→{f.get('destination_airport','?')}"
            dur = f"{f.get('flight_duration_minutes', 0)}m"
            mission = (f.get("mission_type") or "Unknown")[:25]
            lines.append(f"  {f.get('callsign','?'):<10} {dep_time:<6} {route:<12} {dur:<8} {mission}")

        lines += ["", "═" * 70]
        return "\n".join(lines)

    def aircraft_profile_report(self, callsign: str) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT COUNT(*) as total,
                   SUM(flight_duration_minutes) as total_minutes,
                   AVG(max_altitude_ft) as avg_alt,
                   MAX(max_altitude_ft) as max_alt,
                   AVG(avg_speed_mph) as avg_spd,
                   MIN(takeoff_time) as first_seen,
                   MAX(takeoff_time) as last_seen
            FROM flights WHERE callsign = ?
        ''', (callsign,))
        stats = dict(cursor.fetchone() or {})

        cursor.execute(
            "SELECT mission_type, COUNT(*) as count FROM flights WHERE callsign = ? GROUP BY mission_type ORDER BY count DESC",
            (callsign,)
        )
        missions = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            "SELECT category, severity, COUNT(*) as count FROM alerts WHERE callsign = ? GROUP BY category, severity",
            (callsign,)
        )
        alert_history = [dict(r) for r in cursor.fetchall()]

        cursor.execute('''
            SELECT cluster_label, COUNT(*) as count
            FROM cluster_assignments ca
            JOIN flights f ON ca.flight_id = f.flight_id
            WHERE f.callsign = ?
            GROUP BY cluster_label ORDER BY count DESC
        ''', (callsign,))
        clusters = [dict(r) for r in cursor.fetchall()]
        conn.close()

        hours = (stats.get("total_minutes") or 0) / 60
        total_flights = stats.get("total", 1) or 1

        lines = [
            "╔" + "═" * 68 + "╗",
            "║" + f"  AIRCRAFT INTELLIGENCE PROFILE: {callsign}".center(68) + "║",
            "╚" + "═" * 68 + "╝",
            "",
            "  STATISTICS",
            "  ─────────────────────────────────────────────",
            f"  Total flights:       {stats.get('total', 0)}",
            f"  Total flight hours:  {hours:.1f}h",
            f"  Average altitude:    {int(stats.get('avg_alt') or 0):,} ft",
            f"  Peak altitude:       {int(stats.get('max_alt') or 0):,} ft",
            f"  Average speed:       {int(stats.get('avg_spd') or 0)} mph",
            f"  First seen:          {stats.get('first_seen', 'N/A')}",
            f"  Last seen:           {stats.get('last_seen', 'N/A')}",
            "",
            "  MISSION BREAKDOWN",
            "  ─────────────────────────────────────────────",
        ]
        for m in missions:
            pct = m["count"] / total_flights * 100
            bar = "█" * int(pct / 5)
            lines.append(f"  {(m['mission_type'] or 'Unknown'):<35} {bar} {pct:.0f}%")

        if clusters:
            lines += ["", "  BEHAVIORAL CLUSTERS", "  ─────────────────────────────────────────────"]
            for c in clusters:
                lines.append(f"  {c['cluster_label']:<35} {c['count']} flights")

        if alert_history:
            lines += ["", "  ALERT HISTORY", "  ─────────────────────────────────────────────"]
            for a in alert_history:
                lines.append(f"  [{a['severity']}] {a['category']} × {a['count']}")

        lines += ["", "═" * 70]
        return "\n".join(lines)

    def severity_breakdown(self, days: int = 7) -> Dict[str, int]:
        """Return a dict of severity → alert count for the last *days* days."""
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT severity, COUNT(*) as cnt FROM alerts "
                "WHERE timestamp >= ? GROUP BY severity",
                (cutoff,),
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()
        return {r["severity"]: r["cnt"] for r in rows}

    def top_callsigns_by_alert_count(self, days: int = 7,
                                     limit: int = 10) -> List[Dict]:
        """Return callsigns with the most alerts in the last *days* days.

        Returns a list of dicts with keys ``callsign`` and ``alert_count``.
        """
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT callsign, COUNT(*) as alert_count FROM alerts "
                "WHERE timestamp >= ? GROUP BY callsign "
                "ORDER BY alert_count DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def weekly_report(self, date: datetime = None) -> str:
        """Generate a 7-day operational summary ending at *date* (default: now)."""
        from datetime import timedelta
        if date is None:
            date = datetime.utcnow()
        end = date
        start = date - timedelta(days=7)
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
        start_iso = start.isoformat()
        end_iso = end.isoformat()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            flights_total = (conn.execute(
                "SELECT COUNT(*) FROM flights WHERE takeoff_time BETWEEN ? AND ?",
                (start_iso, end_iso),
            ).fetchone() or [0])[0]

            severity_rows = conn.execute(
                "SELECT severity, COUNT(*) as cnt FROM alerts "
                "WHERE timestamp BETWEEN ? AND ? GROUP BY severity",
                (start_iso, end_iso),
            ).fetchall()
            alert_summary = {r["severity"]: r["cnt"] for r in severity_rows}

            callsign_rows = conn.execute(
                "SELECT callsign, COUNT(*) as cnt FROM alerts "
                "WHERE timestamp BETWEEN ? AND ? GROUP BY callsign "
                "ORDER BY cnt DESC LIMIT 5",
                (start_iso, end_iso),
            ).fetchall()
            top_callsigns = [dict(r) for r in callsign_rows]
        except Exception:
            flights_total = 0
            alert_summary = {}
            top_callsigns = []
        finally:
            conn.close()

        total_alerts = sum(alert_summary.values())
        lines = [
            "╔" + "═" * 68 + "╗",
            "║" + f"  WEEKLY OPERATIONAL REPORT — {start_str} to {end_str}".center(68) + "║",
            "╚" + "═" * 68 + "╝",
            "",
            "  SUMMARY (7 DAYS)",
            "  ─────────────────────────────────────────────",
            f"  Total flights:     {flights_total}",
            f"  Total alerts:      {total_alerts}",
            "",
            "  ALERT SEVERITY BREAKDOWN",
            "  ─────────────────────────────────────────────",
        ]
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            count = alert_summary.get(sev, 0)
            if count:
                lines.append(f"  {sev:<12} {count}")
        if not total_alerts:
            lines.append("  No alerts in the past 7 days")

        if top_callsigns:
            lines += ["", "  TOP CALLSIGNS BY ALERT COUNT",
                      "  ─────────────────────────────────────────────"]
            for c in top_callsigns:
                lines.append(f"  {c['callsign']:<15} {c['cnt']} alerts")

        lines += ["", "═" * 70]
        return "\n".join(lines)

    def infrastructure_report(self) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT inf.name as infrastructure, inf.type,
                       COUNT(*) as proximity_events,
                       AVG(fi.closest_distance_nm) as avg_distance
                FROM flight_infrastructure fi
                JOIN infrastructure_features inf ON fi.infrastructure_id = inf.feature_id
                GROUP BY infrastructure
                ORDER BY proximity_events DESC
                LIMIT 10
            ''')
            infra = [dict(r) for r in cursor.fetchall()]
        except Exception:
            infra = []
        conn.close()

        lines = [
            "╔" + "═" * 68 + "╗",
            "║" + "  INFRASTRUCTURE AVIATION ACTIVITY REPORT".center(68) + "║",
            "╚" + "═" * 68 + "╝",
            "",
            f"  {'Feature':<35} {'Type':<20} {'Events':<8} {'Avg Dist'}",
            f"  {'─'*35} {'─'*20} {'─'*8} {'─'*10}",
        ]
        for i in infra:
            lines.append(
                f"  {i.get('infrastructure','?'):<35} "
                f"{i.get('type','?'):<20} "
                f"{i.get('proximity_events', 0):<8} "
                f"{(i.get('avg_distance') or 0):.1f} nm"
            )
        if not infra:
            lines.append("  No infrastructure data yet. Run Phase 2 GIS layer first.")
        lines += ["", "═" * 70]
        return "\n".join(lines)


# ============================================================================
# PHASE 4 PIPELINE
# ============================================================================

class Phase4Pipeline:
    def __init__(self, db_path: str = str(Path.home() / "flight_database.db")):
        self.db_path = db_path
        self.alert_engine = AlertEngine(db_path)
        self.reporter = ReportGenerator(db_path)

    def run(self):
        print("\n" + "═" * 60)
        print("  PHASE 4: OPERATIONAL INTELLIGENCE")
        print("═" * 60)

        flights = self._load_flights()
        print(f"\n  Loaded {len(flights)} flights")

        print("\n  Step 1: Alert generation...")
        total_alerts = 0
        for flight in flights:
            track = self._load_track(flight["flight_id"])
            anomalies = self._load_anomalies(flight["flight_id"])
            alerts = self.alert_engine.evaluate_flight(flight, track, anomalies)
            self.alert_engine.save_alerts(alerts)
            total_alerts += len(alerts)
        print(f"  ✓ {total_alerts} alerts generated")

        print("\n  Step 2: Generating daily report...")
        print(self.reporter.daily_report())

        print("\n  Step 3: Aircraft profiles...")
        callsigns = sorted(set(f["callsign"] for f in flights))[:4]
        for callsign in callsigns:
            print(self.reporter.aircraft_profile_report(callsign))

        print("\n  Step 4: Infrastructure report...")
        print(self.reporter.infrastructure_report())

        print("\n  ✓ Phase 4 complete\n")

    def _load_flights(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM flights ORDER BY takeoff_time")
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    def _load_track(self, flight_id: str) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM track_points WHERE flight_id = ? ORDER BY timestamp",
            (flight_id,)
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    def _load_anomalies(self, flight_id: str) -> List[Dict]:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM flight_anomalies WHERE flight_id = ?", (flight_id,)
            )
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
            return rows
        except Exception:
            return []


if __name__ == "__main__":
    pipeline = Phase4Pipeline()
    pipeline.run()
