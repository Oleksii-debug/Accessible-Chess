from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.version2_upgrade_base import (
    UpgradeLimits,
    UserDataLayout,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
)


class V2UpgradeBookProgressTempArtifactControlTests(unittest.TestCase):
    def _relative_files(
        self,
        coordinator: Version2UpgradeCoordinator,
    ) -> set[str]:
        root = coordinator.layout.root
        return {
            path.relative_to(root).as_posix()
            for path in coordinator._files()
        }

    def test_only_canonical_book_progress_temp_names_are_derived(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()

            canonical = (
                root / ".book-progress.json.abcd_123.tmp",
                root / ".book-progress.json.bak.xy_98765.tmp",
            )
            for path in canonical:
                path.write_bytes(b"writer-temp")

            near_misses = (
                root / ".book-progress.json.bad.token.tmp",
                root / ".book-progress.json.bad-token.tmp",
                root / ".book-progress.json..tmp",
                root / ".book-progress.json.bak.bad.token.tmp",
                root / ".book-progress.json.bak.bad-token.tmp",
                root / ".book-progress.json.bak..tmp",
                root / "book-progress.json.abcd_123.tmp",
                root / ".book-progress.json.abcd_123.tmp.keep",
                root / ".book-progress.json.abc1234.tmp",
                root / ".book-progress.json.abc123456.tmp",
                root / ".book-progress.json.bak.abc1234.tmp",
                root / ".book-progress.json.bak.abc123456.tmp",
            )
            for path in near_misses:
                path.write_bytes(b"user-data")

            nested = root / "user-content"
            nested.mkdir()
            (
                nested / ".book-progress.json.abcd_123.tmp"
            ).write_bytes(b"nested-user-data")

            near_miss_named_directory = (
                root / ".book-progress.json.zz_123.tmp"
            )
            near_miss_named_directory.mkdir()
            (
                near_miss_named_directory / "keep.bin"
            ).write_bytes(b"directory-user-data")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            for path in canonical:
                self.assertNotIn(path.name, files)
            for path in near_misses:
                self.assertIn(path.name, files)
            self.assertIn(
                "user-content/.book-progress.json.abcd_123.tmp",
                files,
            )
            self.assertIn(
                ".book-progress.json.zz_123.tmp/keep.bin",
                files,
            )

    def test_backup_excludes_owned_temps_but_preserves_near_misses(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            durable = root / "book-progress.json"
            durable.write_bytes(b'{"durable":"progress"}\n')
            owned_primary = root / ".book-progress.json.a1_b2c3d.tmp"
            owned_backup = root / ".book-progress.json.bak.d4_e5f67.tmp"
            owned_primary.write_bytes(b"primary-temp")
            owned_backup.write_bytes(b"backup-temp")
            user_file = root / ".book-progress.json.user.data.tmp"
            user_file.write_bytes(b"user-data")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            backup, manifest = coordinator._create_backup(
                "book-progress-temp-grammar"
            )
            paths = {str(item["path"]) for item in manifest["entries"]}

            self.assertIn("book-progress.json", paths)
            self.assertIn(".book-progress.json.user.data.tmp", paths)
            self.assertNotIn(owned_primary.name, paths)
            self.assertNotIn(owned_backup.name, paths)
            self.assertEqual(
                (backup / "data" / user_file.name).read_bytes(),
                b"user-data",
            )

    def test_owned_temp_bytes_do_not_consume_backup_quota(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            durable = root / "book-progress.json"
            durable.write_bytes(b"x")
            (
                root / ".book-progress.json.abcd_123.tmp"
            ).write_bytes(b"z" * 4096)
            (
                root / ".book-progress.json.bak.xy_98765.tmp"
            ).write_bytes(b"z" * 4096)

            coordinator = Version2UpgradeCoordinator(
                UserDataLayout(root),
                limits=UpgradeLimits(max_files=1, max_bytes=8),
            )
            self.assertEqual(
                self._relative_files(coordinator),
                {"book-progress.json"},
            )

            durable.write_bytes(b"y" * 16)
            with self.assertRaisesRegex(
                Version2UpgradeError,
                "backup exceeds byte limit",
            ):
                coordinator._files()

    def test_malformed_temp_lookalike_still_consumes_preservation_quota(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_bytes(b"x")
            (
                root / ".book-progress.json.abc1234.tmp"
            ).write_bytes(b"user-data")

            coordinator = Version2UpgradeCoordinator(
                UserDataLayout(root),
                limits=UpgradeLimits(max_files=1, max_bytes=1024),
            )
            with self.assertRaisesRegex(
                Version2UpgradeError,
                "backup exceeds file count limit",
            ):
                coordinator._files()


if __name__ == "__main__":
    unittest.main()
