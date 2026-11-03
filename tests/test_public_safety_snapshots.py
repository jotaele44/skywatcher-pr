import hashlib
import unittest

from skywatcher.public_safety.records import PublicSafetyError
from skywatcher.public_safety.snapshots import certify_rollback, validate_snapshot


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.payload = b"official example"
        self.row = {
            "source_id": "agency-a",
            "source_record_id": "case-1",
            "source_url": "https://example.org/cases",
            "event_id": "aggregate-event-1",
            "category": "MARITIME_RESCUE",
            "status": "CLOSED",
            "event_date": "2025-01-01",
            "publication": "PUBLIC_AGGREGATE",
            "record_sha256": hashlib.sha256(b"record").hexdigest(),
        }
        self.snapshot = {
            "source_id": "agency-a", "retrieved_utc": "2026-10-21T18:00:00Z",
            "source_url": "https://example.org/cases",
            "raw_sha256": hashlib.sha256(self.payload).hexdigest(), "records": [self.row],
        }

    def test_receipt_and_restore(self):
        receipt = validate_snapshot(self.snapshot, source_bytes=self.payload)
        self.assertTrue(certify_rollback(receipt, dict(receipt)))

    def test_source_tampering(self):
        with self.assertRaises(PublicSafetyError):
            validate_snapshot(self.snapshot, source_bytes=b"modified")

    def test_conflicting_duplicate(self):
        altered = dict(self.row, status="ACTIVE")
        snap = dict(self.snapshot, records=[self.row, altered])
        with self.assertRaises(PublicSafetyError):
            validate_snapshot(snap, source_bytes=self.payload)

    def test_identical_duplicate_rejected(self):
        snap = dict(self.snapshot, records=[self.row, self.row])
        with self.assertRaises(PublicSafetyError):
            validate_snapshot(snap, source_bytes=self.payload)

    def test_cross_source_binding_rejected(self):
        snap = dict(self.snapshot, records=[dict(self.row, source_id="different")])
        with self.assertRaises(PublicSafetyError):
            validate_snapshot(snap, source_bytes=self.payload)

    def test_person_detail_rejected(self):
        snap = dict(self.snapshot, records=[dict(self.row, person_name="protected")])
        with self.assertRaises(PublicSafetyError):
            validate_snapshot(snap, source_bytes=self.payload)

    def test_non_utc_rejected(self):
        snap = dict(self.snapshot, retrieved_utc="2026-10-21T18:00:00-04:00")
        with self.assertRaises(PublicSafetyError):
            validate_snapshot(snap, source_bytes=self.payload)

    def test_restored_receipt_mismatch(self):
        receipt = validate_snapshot(self.snapshot, source_bytes=self.payload)
        with self.assertRaises(PublicSafetyError):
            certify_rollback(receipt, dict(receipt, record_count=2))


if __name__ == "__main__":
    unittest.main()
