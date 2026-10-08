"""Section 50: evidence truth, source invalidation, opt-in and no mock promotion."""
from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.section49_50_live_qualification import (
    SCHEMA_VERSION, _main, _sha256_file, classify_evidence,
)


class EvidenceClassificationTests(unittest.TestCase):
    def test_mock_or_unauthenticated_cannot_be_live_pass(self):
        for evidence in (
            {"schema": SCHEMA_VERSION, "evidence_class": "MOCK",
             "status": "LIVE_RESPONSE_RECEIVED", "source_sha": "a" * 40},
            {"schema": SCHEMA_VERSION, "evidence_class": "LIVE_MODEL",
             "status": "MOCK_PASS", "source_sha": "a" * 40},
            {"schema": SCHEMA_VERSION, "evidence_class": "LIVE_MODEL",
             "status": "LIVE_RESPONSE_RECEIVED", "source_sha": None},
            {"schema": SCHEMA_VERSION, "evidence_class": "YOUTUBE_EMBED",
             "status": "PASS", "source_sha": "a" * 40},
            {"evidence_class": "LIVE_MODEL", "status": "LIVE_RESPONSE_RECEIVED",
             "source_sha": "a" * 40},
        ):
            self.assertNotEqual(classify_evidence(evidence),
                                "MODEL_TRANSPORT_ONLY")

    def test_live_model_transport_still_not_chess_semantics(self):
        proof = {
            "schema": SCHEMA_VERSION, "evidence_class": "LIVE_MODEL",
            "status": "LIVE_RESPONSE_RECEIVED", "source_sha": "a" * 40,
        }
        self.assertEqual(classify_evidence(proof), "MODEL_TRANSPORT_ONLY")
        self.assertNotIn("PASS", classify_evidence(proof))

    def test_offline_video_hash_cannot_be_end_to_end(self):
        proof = {
            "schema": SCHEMA_VERSION, "evidence_class": "OFFLINE_VIDEO",
            "sha256": hashlib.sha256(b"video-fixture").hexdigest(),
            "bytes": 13,
        }
        self.assertEqual(classify_evidence(proof), "SOURCE_BYTES_ONLY")
        self.assertNotEqual(classify_evidence(proof), "VIDEO_E2E_PASS")

    def test_video_file_symlink_and_resource_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "fixture.webm"
            p.write_bytes(b"video-fixture")
            digest, size = _sha256_file(p)
            self.assertEqual(digest, hashlib.sha256(b"video-fixture").hexdigest())
            self.assertEqual(size, 13)
            with self.assertRaises(ValueError):
                _sha256_file(p, max_bytes=3)
            q = Path(directory) / "shortcut.webm"
            try:
                q.symlink_to(p)
            except (OSError, NotImplementedError):
                pass
            else:
                with self.assertRaises(ValueError):
                    _sha256_file(q)

    def test_malformed_source_never_becomes_qualified(self):
        self.assertEqual(classify_evidence(None), "INVALID")
        self.assertEqual(classify_evidence({"schema": "wrong"}), "INVALID")


class OfflineRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_offline_run_does_not_touch_live_gateway(self):
        args = SimpleNamespace(execute_live=False, free_tier_confirmed=False,
                               route=["mistral:test", "groq:test", "gemini:test"],
                               video=None)
        with patch("tools.section49_50_live_qualification._probe",
                   side_effect=AssertionError("no live call authorized")):
            report = await _main(args)
        self.assertEqual(report["run_mode"], "OFFLINE_ONLY")
        self.assertFalse(report["section49_done"])
        self.assertFalse(report["section50_done"])
        self.assertEqual(report["independent_live_routes"], 0)
        self.assertEqual(len(report["routes"]), 3)
        self.assertTrue(all(item["status"] == "BLOCKED"
                            for item in report["routes"]))

    async def test_missing_video_never_promoted(self):
        args = SimpleNamespace(execute_live=False, free_tier_confirmed=False,
                               route=[], video="/no/such/input.webm")
        report = await _main(args)
        self.assertEqual(report["video"]["status"], "BLOCKED")
        self.assertEqual(report["integrated_semantic_qualification"],
                         "NOT_TESTED")

    async def test_available_bytes_remain_byte_only(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "fixture.mp4"
            p.write_bytes(b"not-valid-mp4")
            args = SimpleNamespace(execute_live=False, free_tier_confirmed=False,
                                   route=[], video=str(p))
            report = await _main(args)
            self.assertEqual(report["video"]["status"], "SOURCE_BYTES_ONLY")
            self.assertEqual(report["video"]["board_fen_extraction"], "NOT_TESTED")
            self.assertFalse(report["section50_done"])

    async def test_live_probe_never_self_issues_done(self):
        args = SimpleNamespace(execute_live=True, free_tier_confirmed=True,
                               route=["mistral:test", "groq:test", "gemini:test"],
                               video=None)
        async def simulated_probe(provider, model, sha):
            return {"schema": SCHEMA_VERSION, "evidence_class": "LIVE_MODEL",
                    "provider": provider, "model": model, "source_sha": sha,
                    "status": "LIVE_RESPONSE_RECEIVED"}
        with patch("tools.section49_50_live_qualification._probe",
                   side_effect=simulated_probe):
            report = await _main(args)
        self.assertFalse(report["section49_done"])
        self.assertFalse(report["section50_done"])
        self.assertEqual(report["integrated_semantic_qualification"],
                         "NOT_TESTED")


if __name__ == "__main__":
    unittest.main()
