"""Fail-closed evidence tests for the existing Section-37 live corpus probe.

These tests do not use a synthetic PGN result as proof of a real download.
They prove a failed new run cannot leave an obsolete PASS receipt behind.
"""
from __future__ import annotations

import json
from pathlib import Path
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
                patch.object(probe, "load_catalog", side_effect=LawfulCorpusError("bad catalog")),
            ):
                with self.assertRaisesRegex(LawfulCorpusError, "bad catalog"):
                    probe.main()
            self.assertFalse(report.exists())


if __name__ == "__main__":
    unittest.main()
