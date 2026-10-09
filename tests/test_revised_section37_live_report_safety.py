"""Fail-closed evidence tests for the existing Section-37 live corpus probe.

These tests do not use a synthetic PGN result as proof of a real download.
They prove a failed new run cannot leave an obsolete PASS receipt behind.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
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


    def test_live_readback_consumes_exact_verified_snapshot_across_path_change(self):
        """A path replacement after digest verification cannot affect consumed PGN bytes."""
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "genuine.pgn.zst"
            original = b"exact SHA256-pinned external corpus bytes"
            source.write_bytes(original)
            record = {
                "id": "test_verified_archive",
                "license": "CC0",
                "download_url": "https://database.lichess.org/standard/test-verified.pgn.zst",
                "sha256": hashlib.sha256(original).hexdigest(),
                "max_bytes": 1024,
                "indexed_bytes": len(original),
            }
            report = Path(temp) / "live-report.json"
            seen = []

            class InspectingDecompressor:
                def stream_reader(self, compressed_stream):
                    # The old unsafe implementation reopened the path, yielding
                    # a real file handle rather than the verified immutable bytes.
                    self_type = type(compressed_stream)
                    seen.append(self_type)
                    if not isinstance(compressed_stream, io.BytesIO):
                        raise AssertionError("decompressor consumed mutable path, not verified bytes")
                    if compressed_stream.read() != original:
                        raise AssertionError("decompressor did not receive pinned source bytes")
                    # Simulate attacker mutation after the trusted snapshot.
                    source.write_bytes(b"untrusted new source")
                    return io.BytesIO(b"1. e4 e5\\n")

            def write_subset(lines, destination, requested):
                self.assertEqual(requested, 1)
                self.assertEqual(list(lines), ["1. e4 e5\\n"])
                destination.write_text("1. e4 e5\\n", encoding="utf-8")
                return 1

            with (
                patch.object(probe, "REPORT_FILE", report),
                patch.object(probe, "SOURCE_IDS", (record["id"],)),
                patch.object(probe, "SAMPLE_GAMES", 1),
                patch.object(probe, "_exact_source_head", return_value="a" * 40),
                patch.object(probe, "load_catalog", return_value=[record]),
                patch.object(probe, "acquire_cc0_source", return_value=source),
                patch.object(probe.zstandard, "ZstdDecompressor", InspectingDecompressor),
                patch.object(probe, "_write_complete_game_subset", side_effect=write_subset),
                patch.object(probe, "_parse_complete_game_subset",
                             return_value=[SimpleNamespace(source_index=0)]),
                patch.object(probe, "fingerprint",
                             return_value=SimpleNamespace(sha256="f" * 64, size=9)),
            ):
                probe.main()

            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(seen, [io.BytesIO])
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["sources"][0]["compressed_sha256"], record["sha256"])
            self.assertEqual(result["sources"][0]["compressed_bytes"], len(original))
            self.assertEqual(source.read_bytes(), b"untrusted new source")
            self.assertTrue(result["ephemeral_cache_deleted"])

    def test_live_readback_refuses_tamper_before_verified_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "genuine.pgn.zst"
            source.write_bytes(b"tampered source")
            record = {
                "id": "test_verified_archive",
                "license": "CC0",
                "download_url": "https://database.lichess.org/standard/test-verified.pgn.zst",
                "sha256": hashlib.sha256(b"original trusted bytes").hexdigest(),
                "max_bytes": 1024,
                "indexed_bytes": len(b"original trusted bytes"),
            }
            report = Path(temp) / "live-report.json"
            report.write_text('{"status":"PASS"}', encoding="utf-8")
            with (
                patch.object(probe, "REPORT_FILE", report),
                patch.object(probe, "SOURCE_IDS", (record["id"],)),
                patch.object(probe, "_exact_source_head", return_value="a" * 40),
                patch.object(probe, "load_catalog", return_value=[record]),
                patch.object(probe, "acquire_cc0_source", return_value=source),
                patch.object(probe.zstandard, "ZstdDecompressor") as decoder,
            ):
                with self.assertRaises(LawfulCorpusError):
                    probe.main()
                decoder.assert_not_called()
            self.assertFalse(report.exists(), "tampered source must not leave a PASS receipt")


if __name__ == "__main__":
    unittest.main()
