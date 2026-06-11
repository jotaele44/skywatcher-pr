"""Tests for hardening_layer: ExtractedField, MultiFrameConsensus,
TemporalValidator, StatefulTrackHypothesis, ResumableJobQueue."""

import pytest
from pipeline.hardening_layer import (
    ExtractedField,
    MultiFrameConsensus,
    ResumableJobQueue,
    StatefulTrackHypothesis,
    TemporalValidator,
    ValidationResult,
)


# ── ExtractedField ────────────────────────────────────────────────────────────

def _ef(**kw):
    defaults = dict(
        value="N5854Z", ocr_confidence=0.9, validation_score=0.9,
        consistency_score=0.9, extraction_method="tesseract",
        source_frame="img.jpg", field_name="callsign",
    )
    defaults.update(kw)
    return ExtractedField(**defaults)


def test_combined_confidence_is_geometric_mean():
    ef = _ef(ocr_confidence=0.8, validation_score=0.9, consistency_score=1.0)
    expected = round((0.8 * 0.9 * 1.0) ** (1 / 3), 4)
    assert ef.combined_confidence == expected


def test_is_reliable_above_threshold():
    ef = _ef(ocr_confidence=0.95, validation_score=0.95, consistency_score=0.95)
    assert ef.is_reliable(0.75) is True


def test_is_reliable_below_threshold():
    ef = _ef(ocr_confidence=0.5, validation_score=0.5, consistency_score=0.5)
    assert ef.is_reliable(0.75) is False


def test_zero_ocr_confidence_returns_zero():
    ef = _ef(ocr_confidence=0.0, validation_score=0.9, consistency_score=0.9)
    assert ef.combined_confidence == 0.0


# ── MultiFrameConsensus ───────────────────────────────────────────────────────

def test_consensus_empty_returns_empty():
    assert MultiFrameConsensus().build_consensus([]) == {}


def test_consensus_single_frame_passes_through():
    ef = _ef(value="N5854Z")
    result = MultiFrameConsensus().build_consensus([{"callsign": ef}])
    assert result["callsign"].value == "N5854Z"


def test_consensus_majority_wins():
    frames = [
        {"callsign": _ef(value="N5854Z", ocr_confidence=0.9)},
        {"callsign": _ef(value="N5854Z", ocr_confidence=0.85)},
        {"callsign": _ef(value="N5854X", ocr_confidence=0.7)},
    ]
    assert MultiFrameConsensus().build_consensus(frames)["callsign"].value == "N5854Z"


def test_consensus_method_label_is_consensus():
    frames = [{"callsign": _ef()}, {"callsign": _ef()}]
    result = MultiFrameConsensus().build_consensus(frames)
    assert result["callsign"].extraction_method == "consensus"


def test_consensus_non_ef_values_ignored():
    frames = [{"callsign": _ef(), "raw": "not-an-ef"}]
    result = MultiFrameConsensus().build_consensus(frames)
    assert "callsign" in result
    assert "raw" not in result


# ── TemporalValidator ─────────────────────────────────────────────────────────

def test_clean_track_no_violations():
    points = [
        {"timestamp": "2024-03-15T08:00:00", "latitude": 18.45, "longitude": -66.10,
         "altitude_ft": 1000, "ground_speed_mph": 80},
        {"timestamp": "2024-03-15T08:05:00", "latitude": 18.46, "longitude": -66.11,
         "altitude_ft": 1100, "ground_speed_mph": 82},
    ]
    tv = TemporalValidator()
    results = tv.validate_track(points)
    assert tv.count_violations(results) == 0
    assert tv.passed(results) is True


def test_speed_violation_flagged():
    points = [
        {"timestamp": "2024-03-15T08:00:00", "latitude": 18.00, "longitude": -66.00,
         "altitude_ft": 1000, "ground_speed_mph": 80},
        # ~100 nm in 10 seconds = thousands of mph
        {"timestamp": "2024-03-15T08:00:10", "latitude": 19.50, "longitude": -66.00,
         "altitude_ft": 1000, "ground_speed_mph": 80},
    ]
    tv = TemporalValidator()
    results = tv.validate_track(points)
    speed_fails = [r for r in results if r.check_type == "speed" and not r.passed]
    assert len(speed_fails) >= 1


def test_backward_timestamp_flagged():
    points = [
        {"timestamp": "2024-03-15T08:05:00", "latitude": 18.45, "longitude": -66.10},
        {"timestamp": "2024-03-15T08:00:00", "latitude": 18.46, "longitude": -66.11},
    ]
    tv = TemporalValidator()
    results = tv.validate_track(points)
    mono = [r for r in results if r.check_type == "monotonic_time"]
    assert len(mono) == 1
    assert mono[0].passed is False


def test_single_point_no_checks():
    assert TemporalValidator().validate_track([{"timestamp": "2024-03-15T08:00:00"}]) == []


def test_count_violations_counts_failures():
    results = [
        ValidationResult(passed=True,  check_type="speed", description="OK"),
        ValidationResult(passed=False, check_type="speed", description="FAIL"),
        ValidationResult(passed=False, check_type="climb_rate", description="FAIL"),
    ]
    assert TemporalValidator().count_violations(results) == 2


# ── StatefulTrackHypothesis ───────────────────────────────────────────────────

def test_first_observation_initializes_track():
    sth = StatefulTrackHypothesis()
    result = sth.update("N5854Z", 18.45, -66.10, 1000, 80, "2024-03-15T08:00:00")
    assert result.check_type == "track_init"
    assert result.passed is True
    assert "N5854Z" in sth.states


def test_consistent_update_passes():
    sth = StatefulTrackHypothesis()
    sth.update("N5854Z", 18.45, -66.10, 1000, 80, "2024-03-15T08:00:00")
    # 60-second interval at 80 mph ≈ 1.2 nm — well within MAX_POSITION_ERROR_NM=5.0
    result = sth.update("N5854Z", 18.451, -66.101, 1050, 80, "2024-03-15T08:01:00")
    assert result.check_type == "track_consistency"
    assert result.passed is True


def test_teleport_flagged():
    sth = StatefulTrackHypothesis()
    sth.update("N5854Z", 18.45, -66.10, 1000, 80, "2024-03-15T08:00:00")
    result = sth.update("N5854Z", 25.00, -80.00, 1000, 80, "2024-03-15T08:00:30")
    assert result.passed is False


def test_clear_removes_single_track():
    sth = StatefulTrackHypothesis()
    sth.update("N5854Z", 18.45, -66.10, 1000, 80, "2024-03-15T08:00:00")
    sth.clear("N5854Z")
    assert "N5854Z" not in sth.states


def test_clear_all_empties_state():
    sth = StatefulTrackHypothesis()
    sth.update("N5854Z", 18.45, -66.10, 1000, 80, "2024-03-15T08:00:00")
    sth.update("C6062",  18.50, -67.10, 2000, 120, "2024-03-15T08:00:00")
    sth.clear_all()
    assert sth.states == {}


# ── ResumableJobQueue ─────────────────────────────────────────────────────────

def test_enqueue_and_get_pending(tmp_path):
    q = ResumableJobQueue(str(tmp_path / "jobs.db"))
    q.enqueue_batch(["/img/a.jpg", "/img/b.jpg"], batch_id="b1")
    assert len(q.get_pending_jobs(batch_id="b1")) == 2


def test_enqueue_idempotent_for_same_path(tmp_path):
    q = ResumableJobQueue(str(tmp_path / "jobs.db"))
    q.enqueue_batch(["/img/a.jpg"], batch_id="b1")
    q.enqueue_batch(["/img/a.jpg"], batch_id="b1")
    assert len(q.get_pending_jobs(batch_id="b1")) == 1


def test_mark_complete_removes_from_pending(tmp_path):
    q = ResumableJobQueue(str(tmp_path / "jobs.db"))
    q.enqueue_batch(["/img/a.jpg"], batch_id="b1")
    job = q.get_pending_jobs(batch_id="b1")[0]
    q.mark_complete(job["job_id"])
    assert len(q.get_pending_jobs(batch_id="b1")) == 0


def test_mark_error_keeps_job_in_pending_for_retry(tmp_path):
    q = ResumableJobQueue(str(tmp_path / "jobs.db"))
    q.enqueue_batch(["/img/a.jpg"], batch_id="b1")
    job = q.get_pending_jobs(batch_id="b1")[0]
    q.mark_error(job["job_id"], "OCR failed")
    assert len(q.get_pending_jobs(batch_id="b1")) == 1


def test_checkpoint_saved(tmp_path):
    q = ResumableJobQueue(str(tmp_path / "jobs.db"))
    q.enqueue_batch(["/img/a.jpg"], batch_id="b1")
    q.save_checkpoint("b1", completed=0, failed=0)
    progress = q.get_progress("b1")
    assert isinstance(progress, dict)


# ── Phase 9: Production Hardening ────────────────────────────────────────────

def test_get_failed_jobs_empty_when_no_errors(tmp_path):
    q = ResumableJobQueue(str(tmp_path / "jobs.db"))
    q.enqueue_batch(["/img/a.jpg"], batch_id="b1")
    assert q.get_failed_jobs() == []


def test_get_failed_jobs_returns_errored(tmp_path):
    q = ResumableJobQueue(str(tmp_path / "jobs.db"))
    q.enqueue_batch(["/img/a.jpg", "/img/b.jpg"], batch_id="b1")
    jobs = q.get_pending_jobs()
    q.mark_error(jobs[0]["job_id"], "network timeout")
    failed = q.get_failed_jobs()
    assert len(failed) == 1
    assert failed[0]["job_id"] == jobs[0]["job_id"]


def test_retry_failed_jobs_resets_to_pending(tmp_path):
    q = ResumableJobQueue(str(tmp_path / "jobs.db"))
    q.enqueue_batch(["/img/a.jpg", "/img/b.jpg"], batch_id="b1")
    jobs = q.get_pending_jobs()
    q.mark_error(jobs[0]["job_id"], "timeout")
    q.mark_error(jobs[1]["job_id"], "timeout")
    count = q.retry_failed_jobs()
    assert count == 2
    assert q.get_failed_jobs() == []


def test_retry_failed_jobs_filtered_by_batch(tmp_path):
    q = ResumableJobQueue(str(tmp_path / "jobs.db"))
    q.enqueue_batch(["/img/a.jpg"], batch_id="b1")
    q.enqueue_batch(["/img/b.jpg"], batch_id="b2")
    jobs = q.get_pending_jobs()
    for j in jobs:
        q.mark_error(j["job_id"], "err")
    count = q.retry_failed_jobs(batch_id="b1")
    assert count == 1
    assert len(q.get_failed_jobs(batch_id="b1")) == 0
    assert len(q.get_failed_jobs(batch_id="b2")) == 1


def test_get_batch_stats_returns_dict(tmp_path):
    q = ResumableJobQueue(str(tmp_path / "jobs.db"))
    q.enqueue_batch(["/img/a.jpg", "/img/b.jpg"], batch_id="b1")
    stats = q.get_batch_stats("b1")
    assert isinstance(stats, dict)
    assert stats["total"] == 2
    assert stats["pending"] == 2


def test_get_batch_stats_after_complete(tmp_path):
    q = ResumableJobQueue(str(tmp_path / "jobs.db"))
    q.enqueue_batch(["/img/a.jpg"], batch_id="b1")
    job = q.get_pending_jobs()[0]
    q.mark_complete(job["job_id"])
    stats = q.get_batch_stats("b1")
    assert stats["complete"] == 1
    assert stats["pending"] == 0
