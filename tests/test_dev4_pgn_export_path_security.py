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

    def _symlink_file_or_skip(self, link: Path, target: Path) -> None:
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"file symlink creation unavailable: {exc}")

    def _games(self):
        return parse_games('[Event "Path security"]\n[Result "*"]\n\n1. e4 *\n')

    def test_export_rejects_symlink_parent_instead_of_writing_through_it(self) -> None:
        """A submitted export path must not escape through a symlink parent."""

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
                save_pgn_atomic(destination, self._games(), overwrite=False)

            self.assertFalse(
                escaped_target.exists(),
                "Rejecting a symlink/reparse parent must not create the PGN in its target directory.",
            )

    def test_export_rejects_symlink_ancestor_not_only_direct_parent(self) -> None:
        """Ancestor-chain indirection must fail closed even when parent is real."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            submitted_root = root / "submitted"
            submitted_root.mkdir()
            external = root / "external"
            nested = external / "nested"
            nested.mkdir(parents=True)
            linked_ancestor = submitted_root / "linked"
            self._symlink_dir_or_skip(linked_ancestor, external)

            destination = linked_ancestor / "nested" / "escaped.pgn"
            escaped_target = nested / "escaped.pgn"

            with self.assertRaises((ValueError, OSError, RuntimeError)):
                save_pgn_atomic(destination, self._games(), overwrite=False)

            self.assertFalse(
                escaped_target.exists(),
                "Checking only destination.parent would miss a symlink/reparse ancestor.",
            )

    def test_export_rejects_existing_symlink_destination_in_overwrite_mode(self) -> None:
        """Overwrite mode must not accept an indirection object as destination."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "real.pgn"
            original = '[Event "External target"]\n[Result "*"]\n\n1. d4 *\n'
            target.write_text(original, encoding="utf-8")
            destination = root / "submitted.pgn"
            self._symlink_file_or_skip(destination, target)

            with self.assertRaises((ValueError, OSError, RuntimeError)):
                save_pgn_atomic(destination, self._games(), overwrite=True)

            self.assertTrue(
                destination.is_symlink(),
                "Rejecting a submitted symlink must not replace the indirection object itself.",
            )
            self.assertEqual(
                original,
                target.read_text(encoding="utf-8"),
                "Rejecting a submitted symlink must not modify its target.",
            )


if __name__ == "__main__":
    unittest.main()
