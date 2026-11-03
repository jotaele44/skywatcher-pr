import hashlib
import json
import unittest

from skywatcher.public_safety.adapters import admit_public_snapshot
from skywatcher.public_safety.records import PublicSafetyError


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            "source_id": "public-test", "source_record_id": "1",
            "source_url": "https://example.org/cases", "event_id": "aggregate-1",
            "category": "DRUG_INTERDICTION", "status": "REPORTED",
            "event_date": "2025-02-03", "publication": "PUBLIC_AGGREGATE",
            "record_sha256": "a" * 64,
        }
        self.raw = json.dumps([self.record]).encode()
        self.manifest = {
            "source_id": "public-test", "source_url": "https://example.org/cases",
            "retrieved_utc": "2026-10-21T20:00:00Z",
            "raw_sha256": hashlib.sha256(self.raw).hexdigest(),
        }

    def test_good_snapshot(self):
        receipt = admit_public_snapshot(self.manifest, self.raw)
        self.assertEqual(receipt["record_count"], 1)

    def test_tampered_bytes(self):
        with self.assertRaises(PublicSafetyError):
            admit_public_snapshot(self.manifest, self.raw + b" ")

    def test_sensitive_fields(self):
        bad = json.dumps([dict(self.record, person_name="sensitive")]).encode()
        with self.assertRaises(PublicSafetyError):
            admit_public_snapshot(dict(self.manifest, raw_sha256=hashlib.sha256(bad).hexdigest()), bad)

    def test_no_assumed_source_identity(self):
        bad = json.dumps([dict(self.record, source_record_id="2", source_id="another")]).encode()
        with self.assertRaises(PublicSafetyError):
            admit_public_snapshot(dict(self.manifest, raw_sha256=hashlib.sha256(bad).hexdigest()), bad)

    def test_invalid_bytes(self):
        bad = b"not json"
        with self.assertRaises(PublicSafetyError):
            admit_public_snapshot(dict(self.manifest, raw_sha256=hashlib.sha256(bad).hexdigest()), bad)


if __name__ == "__main__":
    unittest.main()
