"""Section 38 real original-file integrity and Book user-ingress regression gates.

Synthetic input here tests negative behavior only. Real-source PASS comes from
the separately downloaded pinned corpus in section38-real-corpus-integration.yml.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from tools import section38_real_corpus_integration as gate


SMALL_PGN = b'[Event "Original"]\n[White "Alice"]\n[Black "Bob"]\n1. e4 e5 1-0\n'


class Section38SourceBoundReadbackTests(unittest.TestCase):
    def test_exact_pgn_original_receipt_and_canonical_semantics(self):
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "original.pgn"
            source.write_bytes(SMALL_PGN)
            pinned = {"expected_sha256": sha256(SMALL_PGN).hexdigest(), "expected_games": 1}
            games = gate._verified_pgn_games(source, pinned)
            self.assertEqual(len(games), 1)
            record, games_again = gate._pgn_readback(source, pinned)
            self.assertEqual(len(games_again), 1)
            self.assertEqual(record["sha256"], pinned["expected_sha256"])
            self.assertEqual(record["status"], "PASS_SOURCE_PINNED")

    def test_stale_bytes_never_upgrade_a_pgn_receipt(self):
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "original.pgn"
            source.write_bytes(SMALL_PGN)
            pinned = {"expected_sha256": sha256(SMALL_PGN).hexdigest(), "expected_games": 1}
            source.write_bytes(SMALL_PGN + b"\n")
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                gate._verified_pgn_games(source, pinned)

    def test_matching_sha_but_false_expected_game_count_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "original.pgn"
            source.write_bytes(SMALL_PGN)
            pinned = {"expected_sha256": sha256(SMALL_PGN).hexdigest(), "expected_games": 2}
            with self.assertRaisesRegex(RuntimeError, "game count"):
                gate._verified_pgn_games(source, pinned)

    def test_empty_and_indirect_original_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            empty = root / "empty.pgn"
            empty.write_bytes(b"")
            pinned = {"expected_sha256": sha256(b"").hexdigest(), "expected_games": 0}
            with self.assertRaisesRegex(RuntimeError, "size"):
                gate._verified_pgn_games(empty, pinned)
            symlink = root / "linked.pgn"
            try:
                symlink.symlink_to(empty)
            except (OSError, NotImplementedError):
                return  # Windows permissions may prohibit symlink creation.
            with self.assertRaisesRegex(RuntimeError, "indirect"):
                gate._verified_pgn_games(symlink, pinned)

    def test_unpinned_or_mutated_book_rejected_before_semantic_open(self):
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "book.txt"
            source.write_text("Real source", encoding="utf-8")
            with mock.patch.object(gate, "open_book_library_source") as importer:
                with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                    gate._book_readback(source, "0" * 64)
                importer.assert_not_called()

    def test_canonical_native_book_open_is_required_and_semantic_loss_is_partial(self):
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "book.txt"
            source.write_text("Chapter: a position and an unavailable asset", encoding="utf-8")
            digest = sha256(source.read_bytes()).hexdigest()
            projection = SimpleNamespace(
                source=SimpleNamespace(sha256=digest),
                games=(),
                retained_book_blocks=3,
                warnings=("referenced asset is unavailable: diagram.png",),
            )
            prepared = SimpleNamespace(
                document=SimpleNamespace(blocks=(object(), object(), object())),
                warnings=(),
            )
            with (
                mock.patch.object(gate, "open_book_library_source", return_value=projection),
                mock.patch.object(gate.Version2Application, "prepare_book_open", return_value=prepared) as native,
            ):
                receipt = gate._book_readback(source, digest)
            native.assert_called_once_with(source)
            self.assertEqual(receipt["native_book_open_blocks"], 3)
            self.assertEqual(receipt["status"], "PARTIAL_SEMANTIC_LOSS")
            self.assertTrue(receipt["semantic_loss_detected"])

    def test_zero_native_semantic_blocks_cannot_pass_as_book(self):
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "book.txt"
            source.write_bytes(b"Prose")
            digest = sha256(source.read_bytes()).hexdigest()
            projection = SimpleNamespace(
                source=SimpleNamespace(sha256=digest),
                games=(),
                retained_book_blocks=1,
                warnings=(),
            )
            prepared = SimpleNamespace(document=SimpleNamespace(blocks=()), warnings=())
            with (
                mock.patch.object(gate, "open_book_library_source", return_value=projection),
                mock.patch.object(gate.Version2Application, "prepare_book_open", return_value=prepared),
            ):
                with self.assertRaisesRegex(RuntimeError, "lost semantic content"):
                    gate._book_readback(source, digest)

    def test_absent_original_source_never_reaches_library_ingress(self):
        with tempfile.TemporaryDirectory() as raw:
            with mock.patch.object(
                gate, "_library_gate",
                side_effect=AssertionError("Library must never see absent original"),
            ) as importer:
                with self.assertRaisesRegex(RuntimeError, "missing or indirect"):
                    gate.collect(Path(raw))
                importer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
