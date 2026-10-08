"""Section 52.6 rights and package-input gates using actual local fixture bytes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from acs.section52_distribution_qualification import (
    SCHEMA, DistributionQualificationError, qualify_distribution_corpus,
)

SHA = "a" * 40


class Section52CorpusQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.stage = self.root / "stage"
        (self.stage / "books").mkdir(parents=True)
        self.content = b"[Event \"Fixture\"]\n1. e4 e5 *\n"
        (self.stage / "books" / "sample.pgn").write_bytes(self.content)
        self.manifest = self.root / "manifest.json"
        self.doc = {
            "schema": SCHEMA, "kind": "TEST_BUILD", "source_sha": SHA,
            "assets": [{
                "path": "books/sample.pgn",
                "sha256": hashlib.sha256(self.content).hexdigest(),
                "permission": "OWNER_TEST_TRANSFER",
                "source_url": "https://example.org/sample.pgn",
                "rights_ref": "fixture-transfer-license",
            }],
            "external_links": [{"title": "Original source", "url": "https://example.org"}],
        }

    def verify(self):
        self.manifest.write_text(json.dumps(self.doc, ensure_ascii=False), encoding="utf-8")
        return qualify_distribution_corpus(
            stage_dir=self.stage, manifest_path=self.manifest,
            expected_source_sha=SHA,
        )

    def deny(self):
        with self.assertRaises(DistributionQualificationError):
            self.verify()

    def test_owner_test_variant_is_explicitly_not_final_product_evidence(self):
        evidence = self.verify()
        self.assertEqual(evidence["kind"], "TEST_BUILD")
        self.assertEqual(evidence["qualified_asset_count"], 1)
        self.assertEqual(evidence["qualified_bytes"], len(self.content))
        self.assertEqual(evidence["rights_counts"]["OWNER_TEST_TRANSFER"], 1)
        self.assertFalse(evidence["section52_done"])
        self.assertFalse(evidence["actual_legal_rights_verified"])

    def test_public_variant_rejects_owner_only_material(self):
        self.doc["kind"] = "PUBLIC_RELEASE"
        self.deny()
        self.doc["assets"][0]["permission"] = "PUBLIC_REDISTRIBUTION"
        self.assertEqual(self.verify()["kind"], "PUBLIC_RELEASE")

    def test_public_link_only_variant_needs_no_bundled_corpus(self):
        self.doc["kind"] = "PUBLIC_RELEASE"
        self.doc["assets"].clear()
        self.deny()  # undeclared local content is still present
        (self.stage / "books" / "sample.pgn").unlink()
        self.assertEqual(self.verify()["qualified_asset_count"], 0)

    def test_checksum_mismatch_unknown_corpus_and_missing_file(self):
        path = self.stage / "books" / "sample.pgn"
        path.write_bytes(b"different")
        self.deny()
        path.write_bytes(self.content)
        extra = self.stage / "books" / "extra.pgn"
        extra.write_bytes(b"undeclared")
        self.deny()
        extra.unlink()
        path.unlink()
        self.deny()

    def test_unicode_file_names_are_supported_without_case_collisions(self):
        original = self.stage / "books" / "sample.pgn"
        original.rename(self.stage / "books" / "Партія.pgn")
        self.doc["assets"][0]["path"] = "books/Партія.pgn"
        self.assertEqual(self.verify()["qualified_asset_count"], 1)
        (self.stage / "books" / "партія.pgn").write_bytes(self.content)
        self.deny()

    def test_traversal_device_names_and_urls_are_denied(self):
        for value in ("../sample.pgn", "/etc/passwd", "books/../sample.pgn",
                      "books/CON.txt", "books/sample.pgn."):
            self.doc["assets"][0]["path"] = value
            self.deny()
        self.doc["assets"][0]["path"] = "books/sample.pgn"
        for value in ("http://example.org", "https://example.org/a#fragment"):
            self.doc["assets"][0]["source_url"] = value
            self.deny()

    def test_duplicate_or_unknown_rights_and_source_sha_are_denied(self):
        self.doc["assets"].append(dict(self.doc["assets"][0]))
        self.deny()
        self.doc["assets"].pop()
        self.doc["assets"][0]["permission"] = "NOT_CLEARED"
        self.deny()
        self.doc["assets"][0]["permission"] = "OWNER_TEST_TRANSFER"
        self.doc["source_sha"] = "b" * 40
        self.deny()

    def test_unknown_manifest_fields_are_denied(self):
        self.doc["extra"] = "unexpected"
        self.deny()

    def test_symlinks_do_not_pass_as_staged_files(self):
        path = self.stage / "books" / "sample.pgn"
        alternate = self.root / "alternate.pgn"
        alternate.write_bytes(self.content)
        path.unlink()
        try:
            path.symlink_to(alternate)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        self.deny()

    def test_duplicate_json_keys_and_nonfinite_values_are_denied(self):
        for payload in ('{"schema":"a","schema":"b"}', '{"number":NaN}'):
            self.manifest.write_text(payload, encoding="utf-8")
            with self.assertRaises(DistributionQualificationError):
                qualify_distribution_corpus(
                    stage_dir=self.stage,
                    manifest_path=self.manifest,
                    expected_source_sha=SHA,
                )


    def test_source_uri_whitespace_and_windows_directory_case_alias(self):
        self.doc["assets"][0]["source_url"] = " https://example.org/sample.pgn"
        self.deny()
        self.doc["assets"][0]["source_url"] = "https://example.org/\\nsample"
        self.deny()
        self.doc["assets"][0]["source_url"] = "https://example.org/sample.pgn"
        (self.stage / "Books").mkdir()
        self.deny()


if __name__ == "__main__":
    unittest.main()
