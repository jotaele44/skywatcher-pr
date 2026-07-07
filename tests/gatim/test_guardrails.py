from tools.gatim.audit.contradiction_review import contradiction_flags
from tools.gatim.audit.guardrails import scan_text, validate_output_labels
from tools.gatim.core.classifier import apply_classification
from tools.gatim.core.normalizer import normalize_many

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "sanitized_seed"


def test_guardrail_scanner_flags_banned_phrase():
    assert scan_text("this is a confirmed anomaly") == ["confirmed anomaly"]


def test_output_labels_pass_guardrail_check():
    rows = apply_classification(normalize_many([FIXTURES / "access.csv"]))
    assert validate_output_labels(rows) == []


def test_contradiction_flags_context_anchor():
    rows = apply_classification(normalize_many([FIXTURES / "context.csv"]))
    assert "context_anchor_not_site_claim" in contradiction_flags(rows[0])
