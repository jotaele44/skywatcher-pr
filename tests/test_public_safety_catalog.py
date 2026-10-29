import unittest

from skywatcher.public_safety.catalog import validate_source_catalog
from skywatcher.public_safety.records import PublicSafetyError


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.row = {"id": "pr_alertas", "url": "https://www.alertas.pr.gov/personas-desaparecidas",
                    "publisher": "Puerto Rico Government", "scope": "MISSING_PERSON",
                    "admission": "BLOCKED_PERSON_LEVEL", "notes": "No individual records."}
        self.catalog = {"schema_version": "pitirre-source-catalog-v0.1",
                        "certification": "DISCOVERY_ONLY", "as_of": "2026-10-21",
                        "sources": [self.row]}

    def test_valid_metadata_only(self):
        result = validate_source_catalog(self.catalog)
        self.assertEqual(result["source_count"], 1)
        self.assertFalse(result["live_ingestion_enabled"])

    def test_person_admission_rejected(self):
        with self.assertRaises(PublicSafetyError):
            validate_source_catalog(dict(self.catalog, sources=[
                dict(self.row, admission="MANUAL_PUBLICATION_REVIEW")]))

    def test_duplicate_identifiers_rejected(self):
        with self.assertRaises(PublicSafetyError):
            validate_source_catalog(dict(self.catalog, sources=[self.row, self.row]))

    def test_unapproved_claim_rejected(self):
        with self.assertRaises(PublicSafetyError):
            validate_source_catalog(dict(self.catalog, certification="CERTIFIED"))

    def test_unexpected_sensitive_data_rejected(self):
        with self.assertRaises(PublicSafetyError):
            validate_source_catalog(dict(self.catalog, sources=[dict(self.row, name="person")]))

    def test_unsafe_url_rejected(self):
        with self.assertRaises(PublicSafetyError):
            validate_source_catalog(dict(self.catalog, sources=[
                dict(self.row, url="http://example.org")]))

if __name__ == "__main__":
    unittest.main()
