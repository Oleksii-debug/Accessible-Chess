from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import acs.pgn_service as pgn_service
from acs.pgn_service import PgnSourceChangedError, open_pgn


ORIGINAL_PGN = """[Event "Original"]
[Result "*"]

1. e4 e5 *
"""
REPLACEMENT_PGN = """[Event "Replaced"]
[Result "*"]

1. d4 d5 *
"""


class PgnOpenSourceBindingTests(unittest.TestCase):
    def test_byte_identical_replacement_after_fingerprint_is_rejected_by_object_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pgn"
            replacement = root / "replacement.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            replacement.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            original_identity = (source.stat().st_dev, source.stat().st_ino)
            real_fingerprint = pgn_service.fingerprint
            fingerprint_calls = 0

            def fingerprint_then_replace(path, *args, **kwargs):
                nonlocal fingerprint_calls
                result = real_fingerprint(path, *args, **kwargs)
                fingerprint_calls += 1
                if fingerprint_calls == 1:
                    replacement.replace(source)
                return result

            with patch.object(
                pgn_service,
                "fingerprint",
                side_effect=fingerprint_then_replace,
            ):
                with self.assertRaises(PgnSourceChangedError):
                    open_pgn(source)

            self.assertNotEqual(
                (source.stat().st_dev, source.stat().st_ino),
                original_identity,
            )
            self.assertEqual(source.read_text(encoding="utf-8"), ORIGINAL_PGN)

    def test_different_replacement_after_fingerprint_is_rejected_before_parse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pgn"
            replacement = root / "replacement.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            replacement.write_text(REPLACEMENT_PGN, encoding="utf-8", newline="")
            real_fingerprint = pgn_service.fingerprint
            fingerprint_calls = 0

            def fingerprint_then_replace(path, *args, **kwargs):
                nonlocal fingerprint_calls
                result = real_fingerprint(path, *args, **kwargs)
                fingerprint_calls += 1
                if fingerprint_calls == 1:
                    replacement.replace(source)
                return result

            with patch.object(
                pgn_service,
                "fingerprint",
                side_effect=fingerprint_then_replace,
            ):
                with self.assertRaises(PgnSourceChangedError):
                    open_pgn(source)

            self.assertEqual(source.read_text(encoding="utf-8"), REPLACEMENT_PGN)

    def test_same_inode_same_size_mutation_after_fingerprint_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            original = source.read_bytes()
            mutated = original.replace(b"Original", b"Mutated!")
            self.assertEqual(len(mutated), len(original))
            self.assertNotEqual(mutated, original)
            original_identity = (source.stat().st_dev, source.stat().st_ino)
            real_fingerprint = pgn_service.fingerprint
            fingerprint_calls = 0

            def fingerprint_then_mutate(path, *args, **kwargs):
                nonlocal fingerprint_calls
                result = real_fingerprint(path, *args, **kwargs)
                fingerprint_calls += 1
                if fingerprint_calls == 1:
                    Path(path).write_bytes(mutated)
                return result

            with patch.object(
                pgn_service,
                "fingerprint",
                side_effect=fingerprint_then_mutate,
            ):
                with self.assertRaises(PgnSourceChangedError):
                    open_pgn(source)

            self.assertEqual(
                (source.stat().st_dev, source.stat().st_ino),
                original_identity,
            )
            self.assertEqual(source.read_bytes(), mutated)

    def test_path_swap_after_descriptor_open_never_redirects_parsed_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pgn"
            replacement = root / "replacement.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            replacement.write_text(REPLACEMENT_PGN, encoding="utf-8", newline="")
            real_opened_identity = pgn_service._opened_source_identity
            swapped = False
            swap_blocked = False

            def identity_then_swap(handle):
                nonlocal swapped, swap_blocked
                identity = real_opened_identity(handle)
                try:
                    replacement.replace(source)
                except PermissionError:
                    # Windows may deny pathname replacement while the trusted
                    # read handle is open. That is a stronger valid invariant.
                    swap_blocked = True
                else:
                    swapped = True
                return identity

            caught = None
            opened = None
            with patch.object(
                pgn_service,
                "_opened_source_identity",
                side_effect=identity_then_swap,
            ):
                try:
                    opened = open_pgn(source)
                except PgnSourceChangedError as exc:
                    caught = exc

            self.assertNotEqual(swapped, swap_blocked)
            if swapped:
                self.assertIsNotNone(caught)
                self.assertIsNone(opened)
                self.assertEqual(source.read_text(encoding="utf-8"), REPLACEMENT_PGN)
            else:
                self.assertTrue(swap_blocked)
                self.assertIsNone(caught)
                self.assertIsNotNone(opened)
                self.assertEqual(opened.total_games, 1)
                self.assertEqual(opened.games[0].tags["Event"], "Original")

    def test_normal_open_preserves_source_fingerprint_and_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "normal.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")

            opened = open_pgn(source)

            self.assertEqual(opened.total_games, 1)
            self.assertEqual(opened.games[0].tags["Event"], "Original")
            self.assertEqual(opened.source.size, source.stat().st_size)
            self.assertEqual(opened.source.sha256, pgn_service.fingerprint(source).sha256)


if __name__ == "__main__":
    unittest.main()
