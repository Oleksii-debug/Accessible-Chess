from __future__ import annotations

import hashlib
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


class _ReadForbiddenHandle:
    def __init__(self, wrapped):
        self._wrapped = wrapped

    def __enter__(self):
        self._wrapped.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._wrapped.__exit__(exc_type, exc, tb)

    def fileno(self):
        return self._wrapped.fileno()

    def read(self, *args, **kwargs):
        raise AssertionError("replacement bytes must not be read before identity acceptance")


class PgnOpenSourceBindingTests(unittest.TestCase):
    def test_byte_identical_replacement_after_validation_is_rejected_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pgn"
            replacement = root / "replacement.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            replacement.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            original_identity = (source.stat().st_dev, source.stat().st_ino)
            real_validate = pgn_service._validate_source_path
            real_fdopen = pgn_service.os.fdopen
            validations = 0

            def validate_then_replace(path):
                nonlocal validations
                result = real_validate(path)
                validations += 1
                if validations == 1:
                    replacement.replace(source)
                return result

            def fdopen_without_replacement_read(descriptor, *args, **kwargs):
                return _ReadForbiddenHandle(real_fdopen(descriptor, *args, **kwargs))

            with patch.object(
                pgn_service,
                "_validate_source_path",
                side_effect=validate_then_replace,
            ), patch.object(
                pgn_service.os,
                "fdopen",
                side_effect=fdopen_without_replacement_read,
            ):
                with self.assertRaises(PgnSourceChangedError):
                    open_pgn(source)

            self.assertNotEqual(
                (source.stat().st_dev, source.stat().st_ino),
                original_identity,
            )
            self.assertEqual(source.read_text(encoding="utf-8"), ORIGINAL_PGN)

    def test_different_replacement_after_validation_is_rejected_before_parse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pgn"
            replacement = root / "replacement.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            replacement.write_text(REPLACEMENT_PGN, encoding="utf-8", newline="")
            real_validate = pgn_service._validate_source_path
            validations = 0

            def validate_then_replace(path):
                nonlocal validations
                result = real_validate(path)
                validations += 1
                if validations == 1:
                    replacement.replace(source)
                return result

            with patch.object(
                pgn_service,
                "_validate_source_path",
                side_effect=validate_then_replace,
            ):
                with self.assertRaises(PgnSourceChangedError):
                    open_pgn(source)

            self.assertEqual(source.read_text(encoding="utf-8"), REPLACEMENT_PGN)

    def test_same_inode_same_size_mutation_between_held_passes_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            original = source.read_bytes()
            mutated = original.replace(b"Original", b"Mutated!")
            self.assertEqual(len(mutated), len(original))
            self.assertNotEqual(mutated, original)
            original_identity = (source.stat().st_dev, source.stat().st_ino)
            real_rehash = pgn_service._rehash_open_source
            mutated_once = False

            def mutate_then_rehash(handle):
                nonlocal mutated_once
                source.write_bytes(mutated)
                mutated_once = True
                return real_rehash(handle)

            with patch.object(
                pgn_service,
                "_rehash_open_source",
                side_effect=mutate_then_rehash,
            ):
                with self.assertRaises(PgnSourceChangedError):
                    open_pgn(source)

            self.assertTrue(mutated_once)
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

    def test_normal_open_uses_one_source_descriptor_and_preserves_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "normal.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            real_safe_open = pgn_service._open_readonly_no_reparse

            with patch.object(
                pgn_service,
                "fingerprint",
                side_effect=AssertionError("production open must not re-open through fingerprint"),
            ), patch.object(
                pgn_service,
                "_open_readonly_no_reparse",
                wraps=real_safe_open,
            ) as safe_open:
                opened = open_pgn(source)

            self.assertEqual(safe_open.call_count, 1)
            self.assertEqual(opened.total_games, 1)
            self.assertEqual(opened.games[0].tags["Event"], "Original")
            self.assertEqual(opened.source.size, source.stat().st_size)
            self.assertEqual(
                opened.source.sha256,
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
