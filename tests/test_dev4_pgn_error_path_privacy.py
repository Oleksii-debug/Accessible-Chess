from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs import pgn_service
from acs.gametree import parse_games
from acs.pgn_service import PgnConcurrentWriteError, save_pgn_atomic


class Dev4PgnErrorPathPrivacyTests(unittest.TestCase):
    """User-facing PGN save diagnostics must not expose private parent paths."""

    def _games(self):
        return parse_games('[Event "Privacy"]\n[Result "*"]\n\n1. e4 *\n')

    def _private_destination(self, root: Path) -> Path:
        private = root / "Users" / "PrivateUser" / "Documents"
        private.mkdir(parents=True)
        return private / "analysis.pgn"

    def _assert_private_parents_redacted(self, message: str) -> None:
        self.assertNotIn("PrivateUser", message)
        self.assertNotIn("Documents", message)
        self.assertNotIn("Users", message)
        self.assertIn("analysis.pgn", message)

    def _existing_destination(self, root: Path) -> tuple[Path, str]:
        destination = self._private_destination(root)
        destination.write_text(
            '[Event "Existing"]\n[Result "*"]\n\n*\n',
            encoding="utf-8",
        )
        expected_sha256 = pgn_service._current_sha256(destination)
        self.assertIsNotNone(expected_sha256)
        return destination, expected_sha256

    def _temporary_payload(self, destination: Path) -> Path:
        tmp = destination.parent / "candidate.tmp"
        tmp.write_text(
            '[Event "Candidate"]\n[Result "*"]\n\n1. e4 *\n',
            encoding="utf-8",
        )
        return tmp

    def test_existing_destination_error_does_not_expose_absolute_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = self._private_destination(Path(directory))
            destination.write_text('[Event "Existing"]\n[Result "*"]\n\n*\n', encoding="utf-8")

            with self.assertRaises(FileExistsError) as raised:
                save_pgn_atomic(destination, self._games(), overwrite=False)

            self._assert_private_parents_redacted(str(raised.exception))

    def test_expected_hash_mismatch_does_not_expose_absolute_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = self._private_destination(Path(directory))
            destination.write_text('[Event "Existing"]\n[Result "*"]\n\n*\n', encoding="utf-8")

            with self.assertRaises(PgnConcurrentWriteError) as raised:
                save_pgn_atomic(
                    destination,
                    self._games(),
                    overwrite=True,
                    expected_sha256="0" * 64,
                )

            self._assert_private_parents_redacted(str(raised.exception))

    def test_publication_second_destination_check_redacts_private_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination, expected_sha256 = self._existing_destination(Path(directory))
            tmp = self._temporary_payload(destination)

            with mock.patch.object(
                pgn_service,
                "_current_sha256",
                side_effect=[expected_sha256, "1" * 64],
            ):
                with self.assertRaises(PgnConcurrentWriteError) as raised:
                    pgn_service._publish_expected_hash(tmp, destination, expected_sha256)

            self._assert_private_parents_redacted(str(raised.exception))

    def test_publication_snapshot_check_redacts_private_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination, expected_sha256 = self._existing_destination(Path(directory))
            tmp = self._temporary_payload(destination)

            with mock.patch.object(
                pgn_service,
                "_current_sha256",
                side_effect=[expected_sha256, expected_sha256, "2" * 64],
            ):
                with self.assertRaises(PgnConcurrentWriteError) as raised:
                    pgn_service._publish_expected_hash(tmp, destination, expected_sha256)

            self._assert_private_parents_redacted(str(raised.exception))

    def test_during_publication_conflict_redacts_private_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination, expected_sha256 = self._existing_destination(Path(directory))
            tmp = self._temporary_payload(destination)

            with mock.patch.object(
                pgn_service,
                "_current_sha256",
                side_effect=[expected_sha256, expected_sha256, expected_sha256, "3" * 64],
            ):
                with self.assertRaises(PgnConcurrentWriteError) as raised:
                    pgn_service._publish_expected_hash(tmp, destination, expected_sha256)

            self._assert_private_parents_redacted(str(raised.exception))


if __name__ == "__main__":
    unittest.main()
