from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.gametree import parse_games
from acs.pgn_service import open_pgn, save_pgn_atomic


class Dev4PgnPostCommitCleanupAtomicityTests(unittest.TestCase):
    """Strict QA gates for cleanup failures after the destination is committed."""

    def _games(self):
        return parse_games('[Event "Committed"]\n[Result "*"]\n\n1. e4 *\n')

    def test_no_clobber_cleanup_failure_must_not_report_failed_save_after_commit(self) -> None:
        """A temp unlink failure after os.link must not create false-failure state.

        The destination hard link is already the committed PGN before the temp
        name is removed. Reporting the overall save as failed after that point
        makes retry semantics ambiguous: the caller sees an exception even
        though the requested destination now exists with the new content.
        """

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "new.pgn"
            real_unlink = Path.unlink

            def fail_temp_cleanup(path: Path, *args, **kwargs):
                if path.name.startswith(destination.name + ".") and path.name.endswith(".tmp"):
                    raise OSError("temp cleanup failed after commit")
                return real_unlink(path, *args, **kwargs)

            raised: BaseException | None = None
            with mock.patch("pathlib.Path.unlink", autospec=True, side_effect=fail_temp_cleanup):
                try:
                    save_pgn_atomic(destination, self._games(), overwrite=False)
                except BaseException as exc:  # evidence capture; invariant asserted below
                    raised = exc

            committed = destination.exists() and "Committed" in destination.read_text(encoding="utf-8")
            self.assertFalse(
                raised is not None and committed,
                "save_pgn_atomic reported failure after no-clobber publication had already committed the destination",
            )

    def test_expected_hash_snapshot_cleanup_failure_must_not_report_failed_save_after_commit(self) -> None:
        """A CAS snapshot unlink failure must not turn a successful replace into failure."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "existing.pgn"
            destination.write_text(
                '[Event "Original"]\n[Result "*"]\n\n1. d4 *\n',
                encoding="utf-8",
            )
            expected_sha256 = open_pgn(destination).source.sha256
            real_unlink = Path.unlink

            def fail_snapshot_cleanup(path: Path, *args, **kwargs):
                if ".cas-" in path.name and path.name.endswith(".bak"):
                    raise OSError("snapshot cleanup failed after commit")
                return real_unlink(path, *args, **kwargs)

            raised: BaseException | None = None
            with mock.patch("pathlib.Path.unlink", autospec=True, side_effect=fail_snapshot_cleanup):
                try:
                    save_pgn_atomic(
                        destination,
                        self._games(),
                        overwrite=True,
                        expected_sha256=expected_sha256,
                    )
                except BaseException as exc:  # evidence capture; invariant asserted below
                    raised = exc

            committed = "Committed" in destination.read_text(encoding="utf-8")
            self.assertFalse(
                raised is not None and committed,
                "save_pgn_atomic reported failure after expected-hash publication had already committed the destination",
            )


if __name__ == "__main__":
    unittest.main()
