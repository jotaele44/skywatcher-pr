import unittest

from skywatcher.public_safety.changes import compare_receipts
from skywatcher.public_safety.records import PublicSafetyError


class ReceiptChangeTests(unittest.TestCase):
    def setUp(self):
        self.before = {
            "source_id": "agency", "source_url": "https://example.org/source",
            "retrieved_utc": "2026-10-21T12:00:00Z",
            "raw_sha256": "a" * 64,
            "canonical_records_sha256": "b" * 64,
            "record_count": 5,
        }
        self.after = dict(self.before, retrieved_utc="2026-10-21T13:00:00Z")

    def test_same_payload(self):
        self.assertEqual(compare_receipts(self.before, self.after)["classification"], "UNCHANGED")

    def test_byte_only(self):
        self.after["raw_sha256"] = "c" * 64
        self.assertEqual(compare_receipts(self.before, self.after)["classification"], "BYTE_ONLY_CHANGE")

    def test_logical_change(self):
        self.after["canonical_records_sha256"] = "d" * 64
        self.assertEqual(compare_receipts(self.before, self.after)["classification"], "LOGICAL_CHANGE")

    def test_source_swap_rejected(self):
        self.after["source_id"] = "other"
        with self.assertRaises(PublicSafetyError):
            compare_receipts(self.before, self.after)

    def test_same_timestamp_conflict(self):
        self.after["retrieved_utc"] = self.before["retrieved_utc"]
        self.after["raw_sha256"] = "c" * 64
        with self.assertRaises(PublicSafetyError):
            compare_receipts(self.before, self.after)


if __name__ == "__main__":
    unittest.main()
