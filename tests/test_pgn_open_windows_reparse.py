from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import acs.import_contract as import_contract
import acs.pgn_service as pgn_service
from acs.pgn_service import PgnFileError, PgnSourceChangedError, open_pgn


_SAMPLE_PGN = """[Event "Direct Unicode"]
[Result "*"]

1. e4 e5 *
"""


def _remove_junction(path: Path) -> None:
    if os.name != "nt":
        return
    try:
        subprocess.run(
            ["cmd", "/c", "rmdir", str(path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


@unittest.skipUnless(os.name == "nt", "Windows reparse-point contract")
class PgnOpenWindowsReparseTests(unittest.TestCase):
    def _replace_file_with_junction(self, source: Path, target: Path) -> None:
        source.unlink()
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(source), str(target)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if completed.returncode:
            self.fail(f"could not create Windows junction test fixture: {completed.stdout}")
        self.addCleanup(_remove_junction, source)

    def _replace_directory_with_junction(self, source: Path, target: Path) -> None:
        moved = source.with_name(source.name + "-original")
        source.rename(moved)
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(source), str(target)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if completed.returncode:
            moved.rename(source)
            self.fail(f"could not create Windows parent-junction fixture: {completed.stdout}")

    def test_fingerprint_rejects_post_validation_junction_before_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pgn"
            target = root / "foreign-target"
            target.mkdir()
            (target / "foreign.txt").write_text("foreign", encoding="utf-8")
            source.write_text(_SAMPLE_PGN, encoding="utf-8", newline="")

            real_validate = import_contract._validate_source_path
            validations = 0

            def validate_then_swap(path):
                nonlocal validations
                result = real_validate(path)
                validations += 1
                if validations == 1:
                    self._replace_file_with_junction(source, target)
                return result

            with patch.object(
                import_contract,
                "_validate_source_path",
                side_effect=validate_then_swap,
            ), patch.object(
                import_contract.hashlib,
                "sha256",
                side_effect=AssertionError("reparse target bytes must not be hashed"),
            ) as digest:
                with self.assertRaises((OSError, ValueError)):
                    import_contract.fingerprint(source)

            digest.assert_not_called()

    def test_open_rejects_junction_swap_after_validation_before_reader_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pgn"
            target = root / "foreign-target"
            target.mkdir()
            (target / "foreign.txt").write_text("foreign", encoding="utf-8")
            source.write_text(_SAMPLE_PGN, encoding="utf-8", newline="")
            real_validate = pgn_service._validate_source_path
            validations = 0

            def validate_then_swap(path):
                nonlocal validations
                result = real_validate(path)
                validations += 1
                if validations == 1:
                    self._replace_file_with_junction(source, target)
                return result

            with patch.object(
                pgn_service,
                "_validate_source_path",
                side_effect=validate_then_swap,
            ), patch.object(
                pgn_service,
                "_opened_source_identity",
            ) as opened_identity:
                with self.assertRaises(PgnFileError):
                    open_pgn(source)

            opened_identity.assert_not_called()


    def test_fingerprint_rejects_parent_junction_swap_before_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            submitted = root / "submitted"
            foreign = root / "foreign"
            submitted.mkdir()
            foreign.mkdir()
            source = submitted / "source.pgn"
            foreign_source = foreign / "source.pgn"
            source.write_text(_SAMPLE_PGN, encoding="utf-8", newline="")
            foreign_source.write_text(
                _SAMPLE_PGN.replace("Direct Unicode", "Foreign"),
                encoding="utf-8",
                newline="",
            )
            real_validate = import_contract._validate_source_path
            validations = 0
            swapped = False

            def validate_then_swap(path):
                nonlocal validations, swapped
                result = real_validate(path)
                validations += 1
                if validations == 1:
                    self._replace_directory_with_junction(submitted, foreign)
                    swapped = True
                return result

            try:
                with patch.object(
                    import_contract,
                    "_validate_source_path",
                    side_effect=validate_then_swap,
                ), patch.object(
                    import_contract.hashlib,
                    "sha256",
                    side_effect=AssertionError("foreign source bytes must not be hashed"),
                ) as digest:
                    with self.assertRaises(ValueError):
                        import_contract.fingerprint(source)

                self.assertTrue(swapped)
                digest.assert_not_called()
            finally:
                if swapped:
                    _remove_junction(submitted)

    def test_open_rejects_parent_junction_swap_before_foreign_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            submitted = root / "submitted"
            foreign = root / "foreign"
            submitted.mkdir()
            foreign.mkdir()
            source = submitted / "source.pgn"
            foreign_source = foreign / "source.pgn"
            source.write_text(_SAMPLE_PGN, encoding="utf-8", newline="")
            foreign_source.write_text(
                _SAMPLE_PGN.replace("Direct Unicode", "Foreign"),
                encoding="utf-8",
                newline="",
            )
            real_validate = pgn_service._validate_source_path
            real_fdopen = pgn_service.os.fdopen
            validations = 0
            swapped = False

            class ReadForbiddenHandle:
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
                    raise AssertionError("foreign source bytes must not be read")

            def validate_then_swap(path):
                nonlocal validations, swapped
                result = real_validate(path)
                validations += 1
                if validations == 1:
                    self._replace_directory_with_junction(submitted, foreign)
                    swapped = True
                return result

            def fdopen_without_foreign_read(descriptor, *args, **kwargs):
                return ReadForbiddenHandle(real_fdopen(descriptor, *args, **kwargs))

            try:
                with patch.object(
                    pgn_service,
                    "_validate_source_path",
                    side_effect=validate_then_swap,
                ), patch.object(
                    pgn_service.os,
                    "fdopen",
                    side_effect=fdopen_without_foreign_read,
                ):
                    with self.assertRaises(PgnSourceChangedError):
                        open_pgn(source)

                self.assertTrue(swapped)
            finally:
                if swapped:
                    _remove_junction(submitted)


    def test_open_rejects_parent_junction_to_same_inode_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            submitted = root / "submitted"
            foreign = root / "foreign"
            submitted.mkdir()
            foreign.mkdir()
            source = submitted / "source.pgn"
            foreign_source = foreign / "source.pgn"
            source.write_text(_SAMPLE_PGN, encoding="utf-8", newline="")
            os.link(source, foreign_source)

            original = source.stat()
            self.assertEqual(
                (foreign_source.stat().st_dev, foreign_source.stat().st_ino),
                (original.st_dev, original.st_ino),
            )

            real_validate = pgn_service._validate_source_path
            real_fdopen = pgn_service.os.fdopen
            validations = 0
            swapped = False

            class ReadForbiddenHandle:
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
                    raise AssertionError(
                        "indirect same-inode source must be rejected before read"
                    )

            def validate_then_swap(path):
                nonlocal validations, swapped
                result = real_validate(path)
                validations += 1
                if validations == 1:
                    self._replace_directory_with_junction(submitted, foreign)
                    swapped = True
                    current = source.stat()
                    self.assertEqual(
                        (current.st_dev, current.st_ino),
                        (original.st_dev, original.st_ino),
                    )
                return result

            def fdopen_without_read(descriptor, *args, **kwargs):
                return ReadForbiddenHandle(real_fdopen(descriptor, *args, **kwargs))

            try:
                with patch.object(
                    pgn_service,
                    "_validate_source_path",
                    side_effect=validate_then_swap,
                ), patch.object(
                    pgn_service.os,
                    "fdopen",
                    side_effect=fdopen_without_read,
                ):
                    with self.assertRaises(PgnSourceChangedError):
                        open_pgn(source)

                self.assertTrue(swapped)
            finally:
                if swapped:
                    _remove_junction(submitted)



class PgnOpenDirectUnicodePathTests(unittest.TestCase):
    def test_direct_path_with_spaces_and_non_ascii_is_not_treated_as_indirect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "дані з пробілами"
            root.mkdir()
            source = root / "партія ♞.pgn"
            source.write_text(_SAMPLE_PGN, encoding="utf-8", newline="")

            opened = open_pgn(source)

            self.assertEqual(opened.total_games, 1)
            self.assertEqual(opened.games[0].tags["Event"], "Direct Unicode")


if __name__ == "__main__":
    unittest.main()
