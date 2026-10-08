"""Section 50 actual-source qualification must never masquerade as board semantic PASS."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from acs.local_video_library import RealVideoEntry, load_real_video_catalog
from tools.section50_real_video_source import MAX_VIDEO_BYTES, qualify_one


class RealVideoQualificationSafetyTests(unittest.TestCase):
    def setUp(self):
        items = load_real_video_catalog("docs/media/section47_real_video_catalog.json")
        self.assertGreaterEqual(len(items), 1)
        self.entry = next(x for x in items if x.video_id == "youth-chess-championships")
        self.assertIsNone(self.entry.expected_sha256)

    def test_without_network_completion_is_explicitly_blocked(self):
        with patch("tools.section50_real_video_source._download_bounded",
                   side_effect=OSError("network blocked")):
            status = qualify_one(self.entry)
        self.assertEqual(status["status"], "BLOCKED")
        self.assertEqual(status["chess_board_fen"], "NOT_TESTED")
        self.assertIsNone(status["source_sha256"])
        self.assertNotIn("network blocked", str(status))

    def test_trusted_mock_bytes_only_may_yield_decode_not_semantic_pass(self):
        digest = hashlib.sha256(b"fixture").hexdigest()
        with patch("tools.section50_real_video_source._download_bounded",
                   return_value=(7, digest)):
            with patch("tools.section50_real_video_source._decode_one_frame",
                       return_value=(digest, 12.0)):
                result = qualify_one(self.entry)
        self.assertEqual(result["status"], "SOURCE_FRAME_DECODED_SHA_NOT_YET_PINNED")
        self.assertFalse(result["catalog_sha256_pinned"])
        self.assertEqual(result["source_sha256"], digest)
        for field in ("chess_board_fen", "stockfish", "book_library", "agent", "restart"):
            self.assertEqual(result[field], "NOT_TESTED")

    def test_decode_error_blocks_without_leaking_raw_exception(self):
        with patch("tools.section50_real_video_source._download_bounded",
                   return_value=(7, hashlib.sha256(b"mock").hexdigest())):
            with patch("tools.section50_real_video_source._decode_one_frame",
                       side_effect=ValueError("temporary sensitive diagnostic")):
                result = qualify_one(self.entry)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertNotIn("temporary sensitive diagnostic", str(result))

    def test_qualified_source_is_distinct_from_model_or_fen_pass(self):
        from dataclasses import replace
        pinned = replace(self.entry, expected_sha256="b" * 64)
        with patch("tools.section50_real_video_source._download_bounded",
                   return_value=(42, "b" * 64)):
            with patch("tools.section50_real_video_source._decode_one_frame",
                       return_value=("c" * 64, 12.0)):
                result = qualify_one(pinned)
        self.assertEqual(result["status"], "SOURCE_FRAME_VERIFIED_SHA_PINNED")
        self.assertEqual(result["chess_board_fen"], "NOT_TESTED")
        self.assertFalse("chess_semantic_pass" in result)


if __name__ == "__main__":
    unittest.main()
