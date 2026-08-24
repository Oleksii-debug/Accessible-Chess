from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.gametree import parse_games
from acs.pgn_service import open_pgn, save_pgn_atomic


class Dev4PgnPostCommitCleanupAtomicityTests(unittest.TestCase):
    """Strict gates for cleanup failures after the destination is committed."""

    def _games(self):
        return parse_games('[Event "Committed"]\n[Result "*"]\n\n1. e4 *\n')

    def test_no_clobber_cleanup_failure_must_not_report_failed_save_after_commit(self) -> None:
        """A temp unlink failure after os.link must not create false-failure state."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "new.pgn"
            real_unlink = Path.unlink

            def fail_temp_cleanup(path: Path, *args, **kwargs):
                if path.name.startswith(destination.name + ".") and path.name.endswith(".tmp"):
                    raise OSError("temp cleanup failed after commit")
                return real_unlink(path, *args, **kwargs)

            with mock.patch("pathlib.Path.unlink", autospec=True, side_effect=fail_temp_cleanup):
                result = save_pgn_atomic(destination, self._games(), overwrite=False)

            self.assertTrue(destination.exists())
            self.assertIn("Committed", destination.read_text(encoding="utf-8"))
            self.assertEqual(result.sha256, open_pgn(destination).source.sha256)
            self.assertEqual(list(root.glob("new.pgn.*.tmp")), [])

    def test_expected_hash_snapshot_cleanup_failure_after_commit_is_success(self) -> None:
        """Failure of redundant CAS snapshot cleanup cannot falsify a committed save.

        The first ``.cas-*.bak`` unlink removes the mkstemp placeholder before
        the hard-link snapshot exists and must be allowed. The second occurs
        only after ``os.replace`` has committed and verified the new PGN; that
        is the cleanup failure this regression targets.
        """

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "existing.pgn"
            destination.write_text(
                '[Event "Original"]\n[Result "*"]\n\n1. d4 *\n',
                encoding="utf-8",
            )
            expected_sha256 = open_pgn(destination).source.sha256
            real_unlink = Path.unlink
            snapshot_unlinks = 0

            def fail_only_postcommit_snapshot_cleanup(path: Path, *args, **kwargs):
                nonlocal snapshot_unlinks
                if ".cas-" in path.name and path.name.endswith(".bak"):
                    snapshot_unlinks += 1
                    if snapshot_unlinks >= 2:
                        raise OSError("snapshot cleanup failed after commit")
                return real_unlink(path, *args, **kwargs)

            with mock.patch(
                "pathlib.Path.unlink",
                autospec=True,
                side_effect=fail_only_postcommit_snapshot_cleanup,
            ):
                result = save_pgn_atomic(
                    destination,
                    self._games(),
                    overwrite=True,
                    expected_sha256=expected_sha256,
                )

            self.assertGreaterEqual(snapshot_unlinks, 2)
            self.assertIn("Committed", destination.read_text(encoding="utf-8"))
            self.assertEqual(result.sha256, open_pgn(destination).source.sha256)
            self.assertEqual(list(root.glob("existing.pgn.cas-*.bak")), [])


if __name__ == "__main__":
    unittest.main()
