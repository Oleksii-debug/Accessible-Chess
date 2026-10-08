"""Fail-closed evidence tests for the existing Section-37 live corpus probe.

These tests do not use a synthetic PGN result as proof of a real download.
They prove a failed new run cannot leave an obsolete PASS receipt behind.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from acs.lawful_corpus_registry import LawfulCorpusError
from tools import revised_section37_real_cc0_readback as probe


class LiveCorpusEvidenceSafetyTests(unittest.TestCase):
    def test_failed_new_acquisition_deletes_stale_pass_and_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / "revised-section37-live-cc0-readback.json"
            staging = report.with_suffix(".tmp")
            report.write_text(json.dumps({"status": "PASS", "source": "prior-run"}))
            staging.write_text('{"status":"PASS","source":"stale-staging"}')
            with (
                patch.object(probe, "REPORT_FILE", report),
                patch.object(probe, "_exact_source_head", return_value="a" * 40),
                patch.object(probe, "acquire_cc0_source", side_effect=LawfulCorpusError("source offline")),
            ):
                with self.assertRaisesRegex(LawfulCorpusError, "source offline"):
                    probe.main()
            self.assertFalse(report.exists(), "old PASS must not survive a failed new run")
            self.assertFalse(staging.exists(), "old staging must not survive a failed new run")

    def test_catalog_failure_also_invalidates_old_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / "revised-section37-live-cc0-readback.json"
            report.write_text('{"status":"PASS"}')
            with (
                patch.object(probe, "REPORT_FILE", report),
                patch.object(probe, "_exact_source_head", return_value="a" * 40),
                patch.object(probe, "load_catalog", side_effect=LawfulCorpusError("bad catalog")),
            ):
                with self.assertRaisesRegex(LawfulCorpusError, "bad catalog"):
                    probe.main()
            self.assertFalse(report.exists())

    def test_checkout_mismatch_rejects_evidence_before_acquisition(self):
        head = "a" * 40
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / "revised-section37-live-cc0-readback.json"
            report.write_text('{"status":"PASS","source_commit_sha":"older"}')
            with (
                patch.object(probe, "REPORT_FILE", report),
                patch.object(
                    probe.subprocess, "run",
                    return_value=subprocess.CompletedProcess([], 0, head + chr(10), ""),
                ),
                patch.dict(os.environ, {"ACCESSIBLE_CHESS_EXPECTED_HEAD": "b" * 40}),
                patch.object(probe, "load_catalog") as catalog,
                patch.object(probe, "acquire_cc0_source") as acquire,
            ):
                with self.assertRaisesRegex(RuntimeError, "differs from expected candidate"):
                    probe.main()
                catalog.assert_not_called()
                acquire.assert_not_called()
            self.assertFalse(report.exists(), "stale PASS must be invalidated on SHA mismatch")

    def test_exact_checkout_sha_is_accepted_only_when_matching(self):
        head = "0f" * 20
        with (
            patch.object(
                probe.subprocess, "run",
                return_value=subprocess.CompletedProcess([], 0, head + chr(10), ""),
            ),
            patch.dict(os.environ, {"ACCESSIBLE_CHESS_EXPECTED_HEAD": head}),
        ):
            self.assertEqual(probe._exact_source_head(), head)

    def test_missing_git_checkout_refuses_unattributed_pass(self):
        with (
            patch.object(probe.subprocess, "run", side_effect=FileNotFoundError("git")),
            patch.dict(os.environ, {"ACCESSIBLE_CHESS_EXPECTED_HEAD": "c" * 40}),
        ):
            with self.assertRaisesRegex(RuntimeError, "cannot verify checkout SHA"):
                probe._exact_source_head()


if __name__ == "__main__":
    unittest.main()
