from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from acs.atomic_publication import AtomicPublicationError, publish_directory_no_replace


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux renameat2 coverage")
class AtomicPublicationLinuxTests(unittest.TestCase):
    def test_success_atomically_moves_staged_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            staged = root / ".candidate.staged"
            output = root / "candidate"
            staged.mkdir()
            (staged / "data.txt").write_text("ready", encoding="utf-8")

            publish_directory_no_replace(staged, output)

            self.assertFalse(staged.exists())
            self.assertEqual(
                (output / "data.txt").read_text(encoding="utf-8"),
                "ready",
            )

    def test_existing_directory_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            staged = root / ".candidate.staged"
            output = root / "candidate"
            staged.mkdir()
            (staged / "new.txt").write_text("new", encoding="utf-8")
            output.mkdir()
            (output / "keep.txt").write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(
                AtomicPublicationError,
                "will not be overwritten",
            ):
                publish_directory_no_replace(staged, output)

            self.assertTrue(staged.is_dir())
            self.assertEqual(
                (output / "keep.txt").read_text(encoding="utf-8"),
                "keep",
            )
            self.assertFalse((output / "new.txt").exists())

    def test_existing_file_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            staged = root / ".candidate.staged"
            output = root / "candidate"
            staged.mkdir()
            output.write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(
                AtomicPublicationError,
                "will not be overwritten",
            ):
                publish_directory_no_replace(staged, output)

            self.assertEqual(output.read_text(encoding="utf-8"), "keep")
            self.assertTrue(staged.is_dir())

    def test_existing_symlink_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            staged = root / ".candidate.staged"
            output = root / "candidate"
            target = root / "target"
            staged.mkdir()
            target.mkdir()
            output.symlink_to(target, target_is_directory=True)

            with self.assertRaisesRegex(
                AtomicPublicationError,
                "will not be overwritten",
            ):
                publish_directory_no_replace(staged, output)

            self.assertTrue(output.is_symlink())
            self.assertTrue(staged.is_dir())

    def test_cross_parent_publication_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()
            staged = left / ".candidate.staged"
            staged.mkdir()
            output = right / "candidate"

            with self.assertRaisesRegex(AtomicPublicationError, "share one parent"):
                publish_directory_no_replace(staged, output)

            self.assertTrue(staged.is_dir())
            self.assertFalse(output.exists())

    def test_unsupported_platform_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            staged = root / ".candidate.staged"
            output = root / "candidate"
            staged.mkdir()

            with patch("acs.atomic_publication.os.name", "posix"), patch(
                "acs.atomic_publication.sys.platform",
                "darwin",
            ):
                with self.assertRaisesRegex(AtomicPublicationError, "unsupported"):
                    publish_directory_no_replace(staged, output)

            self.assertTrue(staged.is_dir())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
