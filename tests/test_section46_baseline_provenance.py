from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.section46_baseline_diff import VisualBaselineError, qualify


class Section46BaselineProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.capture = root / "capture"
        self.approved = root / "approved"
        self.capture.mkdir()
        self.approved.mkdir()
        self.observed = b"not-a-real-png-captured"
        self.reference = b"not-a-real-png-reviewed"
        (self.capture / "a.png").write_bytes(self.observed)
        (self.approved / "a.png").write_bytes(self.reference)
        self.captured_manifest = {
            "exact_source_sha": "a" * 40,
            "records": [{"screenshot": "a.png",
                         "sha256": hashlib.sha256(self.observed).hexdigest()}],
        }
        self.approved_manifest = {
            "schema_version": 1,
            "approved": True,
            "human_reviewed": True,
            "reviewer": "Independent visual reviewer",
            "reviewed_at": "2026-10-08T21:00:00Z",
            "baseline_source_sha": "b" * 40,
            "screenshots": [{"name": "a.png",
                             "sha256": hashlib.sha256(self.reference).hexdigest()}],
        }
        self.persist()

    def persist(self):
        (self.capture / "quality-manifest.json").write_text(
            json.dumps(self.captured_manifest), encoding="utf-8"
        )
        (self.approved / "approved-baselines.json").write_text(
            json.dumps(self.approved_manifest), encoding="utf-8"
        )

    def expect_blocked(self, reason):
        with self.assertRaisesRegex(VisualBaselineError, reason):
            qualify(self.capture, self.approved)

    def test_missing_review_is_not_a_visual_pass(self):
        (self.approved / "approved-baselines.json").unlink()
        self.expect_blocked("NO_APPROVED_BASELINES")

    def test_human_identity_utc_review_date_and_schema_must_be_explicit(self):
        for key, value in (
            ("human_reviewed", False),
            ("reviewer", ""),
            ("reviewed_at", "yesterday"),
            ("baseline_source_sha", "not-sha"),
            ("schema_version", 2),
        ):
            original = self.approved_manifest[key]
            with self.subTest(key=key):
                self.approved_manifest[key] = value
                self.persist()
                self.expect_blocked("approval|review|SHA|structure")
                self.approved_manifest[key] = original

    def test_tampered_current_png_fails_before_any_pixel_comparison(self):
        (self.capture / "a.png").write_bytes(b"tampered")
        self.expect_blocked("capture PNG SHA-256")

    def test_tampered_reviewed_png_fails_before_any_pixel_comparison(self):
        (self.approved / "a.png").write_bytes(b"tampered")
        self.expect_blocked("approved PNG SHA-256")

    def test_missing_exact_capture_sha_and_injected_path_are_rejected(self):
        self.captured_manifest.pop("exact_source_sha")
        self.persist()
        self.expect_blocked("source SHA")
        self.captured_manifest["exact_source_sha"] = "a" * 40
        self.captured_manifest["records"][0]["screenshot"] = "../private.png"
        self.approved_manifest["screenshots"][0]["name"] = "../private.png"
        self.persist()
        self.expect_blocked("unsafe screenshot")

    def test_duplicate_source_capture_names_are_rejected(self):
        self.captured_manifest["records"].append(
            dict(self.captured_manifest["records"][0])
        )
        self.persist()
        self.expect_blocked("ambiguous captured screenshot")


if __name__ == "__main__":
    unittest.main()
