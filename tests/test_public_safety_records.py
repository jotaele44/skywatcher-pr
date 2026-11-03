import unittest

from skywatcher.public_safety.records import PublicSafetyError, reconcile_events, validate_event

SAMPLE = {
    "source_id": "official-example",
    "source_record_id": "example-001",
    "source_url": "https://example.org/official-case",
    "event_id": "event-example-001",
    "category": "MARITIME_RESCUE",
    "status": "CLOSED",
    "event_date": "2025-01-01",
    "publication": "PUBLIC_AGGREGATE",
    "record_sha256": "a" * 64,
}

class PublicSafetyRecordsTests(unittest.TestCase):
    def test_valid_record(self):
        self.assertEqual(validate_event(SAMPLE), SAMPLE)

    def test_deduplicates_exact(self):
        self.assertEqual(len(reconcile_events([SAMPLE, SAMPLE])), 1)

    def test_collision_fails(self):
        different = dict(SAMPLE, status="ACTIVE")
        with self.assertRaises(PublicSafetyError):
            reconcile_events([SAMPLE, different])

    def test_rejects_sensitive_or_inferred_fields(self):
        for key in ("person_name", "live_location", "suspect_score", "lat", "immigration_status"):
            with self.subTest(key=key), self.assertRaises(PublicSafetyError):
                validate_event(dict(SAMPLE, **{key: "anything"}))

    def test_rejects_unverified_publication(self):
        with self.assertRaises(PublicSafetyError):
            validate_event(dict(SAMPLE, publication="RESTRICTED"))

    def test_rejects_missing_lineage(self):
        with self.assertRaises(PublicSafetyError):
            validate_event(dict(SAMPLE, record_sha256=""))

    def test_rejects_unknown_status(self):
        with self.assertRaises(PublicSafetyError):
            validate_event(dict(SAMPLE, status="SUSPECTED_CRIMINAL"))

if __name__ == "__main__":
    unittest.main()
