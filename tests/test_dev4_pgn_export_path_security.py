from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.gametree import parse_games
from acs.pgn_service import save_pgn_atomic


class Dev4PgnExportPathSecurityTests(unittest.TestCase):
    """QA gate for untrusted filesystem indirection on PGN export paths."""

    def _symlink_dir_or_skip(self, link: Path, target: Path) -> None:
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlink creation unavailable: {exc}")

    def test_export_rejects_symlink_parent_instead_of_writing_through_it(self) -> None:
        """A submitted export path must not escape through a symlink parent.

        The DEV4 Full Product path-security contract treats filesystem
        indirection at external import/export boundaries as fail-closed.  A
        destination below a symlink/reparse-style parent currently causes the
        temp file and final atomic replace to occur in the symlink target.  A
        safe implementation must reject that path before creating or replacing
        anything outside the submitted directory tree.
        """

        games = parse_games('[Event "Path security"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            submitted_root = root / "submitted"
            submitted_root.mkdir()
            external = root / "external"
            external.mkdir()
            linked_parent = submitted_root / "exports"
            self._symlink_dir_or_skip(linked_parent, external)

            destination = linked_parent / "escaped.pgn"
            escaped_target = external / "escaped.pgn"

            with self.assertRaises((ValueError, OSError, RuntimeError)):
                save_pgn_atomic(destination, games, overwrite=False)

            self.assertFalse(
                escaped_target.exists(),
                "Rejecting a symlink/reparse parent must not create the PGN in its target directory.",
            )


if __name__ == "__main__":
    unittest.main()
