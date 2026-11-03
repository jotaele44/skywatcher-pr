import hashlib
import unittest

from skywatcher.public_safety.consumer import build_consumer_package
from skywatcher.public_safety.records import PublicSafetyError
from skywatcher.public_safety.snapshots import canonical_bytes


class ConsumerContractTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            "source_id": "agency", "source_record_id": "r1",
            "source_url": "https://example.org/records", "event_id": "event1",
            "category": "MARITIME_RESCUE", "status": "CLOSED",
            "event_date": "2024-01-05", "publication": "PUBLIC_AGGREGATE",
            "record_sha256": "a" * 64,
        }
        self.receipt = {
            "source_id": "agency", "source_url": "https://example.org/records",
            "retrieved_utc": "2026-10-21T20:00:00Z", "raw_sha256": "b" * 64,
            "record_count": 1,
            "canonical_records_sha256": hashlib.sha256(canonical_bytes([self.record])).hexdigest(),
        }

    def test_no_person_level_release(self):
        p = build_consumer_package([self.record], source_receipt=self.receipt)
        self.assertEqual(p["groups"], [])
        self.assertNotIn("source_record_id", str(p))
        self.assertEqual(p["certification"], "AUDIT_ONLY")

    def test_receipt_mismatch_rejected(self):
        with self.assertRaises(PublicSafetyError):
            build_consumer_package([self.record], source_receipt=dict(self.receipt, record_count=2))

    def test_duplicate_rejected(self):
        with self.assertRaises(PublicSafetyError):
            build_consumer_package([self.record, self.record], source_receipt=self.receipt)

    def test_personal_data_rejected(self):
        with self.assertRaises(PublicSafetyError):
            build_consumer_package([dict(self.record, person_name="private")], source_receipt=self.receipt)


    def test_five_events_publish_one_group(self):
        records = [
            dict(self.record, source_record_id=f"r{i}", event_id=f"event{i}")
            for i in range(5)
        ]
        receipt = dict(
            self.receipt,
            record_count=5,
            canonical_records_sha256=hashlib.sha256(canonical_bytes(records)).hexdigest(),
        )
        package = build_consumer_package(records, source_receipt=receipt)
        self.assertEqual(package["groups"], [
            {"category": "MARITIME_RESCUE", "status": "CLOSED", "year": "2024", "count": 5}
        ])

    def test_four_events_do_not_publish_group(self):
        records = [
            dict(self.record, source_record_id=f"r{i}", event_id=f"event{i}")
            for i in range(4)
        ]
        receipt = dict(
            self.receipt,
            record_count=4,
            canonical_records_sha256=hashlib.sha256(canonical_bytes(records)).hexdigest(),
        )
        self.assertEqual(build_consumer_package(records, source_receipt=receipt)["groups"], [])


if __name__ == "__main__":
    unittest.main()
