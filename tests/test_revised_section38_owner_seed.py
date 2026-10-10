"""Real Stockfish bytes -> owner-test package -> canonical Library -> restart."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.version2_package_assembler import Version2PackageAssemblyError
from acs.library_source_service import LibrarySourceCatalogService
from acs.user_library_seed import (
    UserLibrarySeedError, import_user_library_seed, load_user_library_seed,
)
from tools.revised_section38_stockfish_owner_seed import (
    SEED_PGN_NAME, prepare_owner_test_stockfish_seed,
)


class RealStockfishOwnerLibrarySeedTests(unittest.TestCase):
    def test_real_source_published_once_and_survives_library_restart(self):
        with tempfile.TemporaryDirectory(prefix="acs-real-stockfish-owner-seed-") as temp:
            parent = Path(temp) / "release-content"
            parent.mkdir()
            target = parent / "user-library-seed"
            receipt = prepare_owner_test_stockfish_seed(target)
            self.assertEqual(receipt["status"], "OWNER_TEST_PREPARED_NOT_PUBLIC_RELEASE")
            self.assertEqual(receipt["derived_games"], 32)
            self.assertEqual(receipt["distribution"], "OWNER_TEST_ONLY")
            self.assertFalse(receipt["network_required"])
            manifest = load_user_library_seed(target)
            self.assertEqual(len(manifest.entries), 1)
            self.assertEqual(manifest.entries[0].file_name, SEED_PGN_NAME)
            self.assertEqual(manifest.entries[0].sha256, receipt["derived_pgn_sha256"])

            database_path = Path(temp) / "actual-real-games.acsdb"
            with AcsDatabase(database_path) as database:
                first = import_user_library_seed(database, manifest)
                self.assertEqual(first.source_count, 1)
                self.assertEqual(first.game_count, 32)
                self.assertEqual(first.reused_source_count, 0)
                database.verify_integrity()
            with AcsDatabase(database_path) as database:
                repeated = import_user_library_seed(database, load_user_library_seed(target))
                self.assertEqual(repeated.game_count, 32)
                self.assertEqual(repeated.reused_source_count, 1)
                listing = LibrarySourceCatalogService(database).list_sources()
                self.assertEqual(len(listing.items), 1)
                src = listing.items[0]
                self.assertEqual(src.game_count, 32)
                self.assertEqual(src.source_sha256, receipt["derived_pgn_sha256"])
                rows = LibrarySourceCatalogService(database).source_games(src.source_id, limit=32)
                self.assertEqual(len(rows.items), 32)
                self.assertFalse(rows.has_more)
                database.verify_integrity()

    def test_existing_empty_seed_directory_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp) / "release-content"
            parent.mkdir()
            target = parent / "user-library-seed"
            target.mkdir()
            with self.assertRaises(FileExistsError):
                prepare_owner_test_stockfish_seed(target)
            self.assertEqual(tuple(target.iterdir()), ())
            self.assertTrue(target.is_dir())

    def test_concurrent_owner_destination_is_not_clobbered(self):
        """Existing package publisher is the sole atomic NOREPLACE authority."""
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp) / "release-content"
            parent.mkdir()
            target = parent / "user-library-seed"

            def hostile_creator(_staged, dest):
                dest.mkdir()
                (dest / "owner.txt").write_text("preserve", encoding="utf-8")
                raise Version2PackageAssemblyError("target appeared")

            with patch(
                "tools.revised_section38_stockfish_owner_seed._publish_directory_no_replace",
                side_effect=hostile_creator,
            ) as publisher:
                with self.assertRaises(Version2PackageAssemblyError):
                    prepare_owner_test_stockfish_seed(target)
                publisher.assert_called_once()
            self.assertEqual((target / "owner.txt").read_text(encoding="utf-8"),
                             "preserve")
            self.assertEqual(tuple(path.name for path in target.iterdir()), ("owner.txt",))

    def test_no_clobber_and_corrupted_real_seed_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp) / "release-content"
            parent.mkdir()
            target = parent / "user-library-seed"
            receipt = prepare_owner_test_stockfish_seed(target)
            pristine = (target / SEED_PGN_NAME).read_bytes()
            with self.assertRaises(FileExistsError):
                prepare_owner_test_stockfish_seed(target)
            self.assertEqual((target / SEED_PGN_NAME).read_bytes(), pristine)
            self.assertEqual(receipt["derived_bytes"], len(pristine))

            tampered = pristine[:-1] + bytes([pristine[-1] ^ 1])
            (target / SEED_PGN_NAME).write_bytes(tampered)
            with AcsDatabase(Path(temp) / "negative.acsdb") as database:
                with self.assertRaises(UserLibrarySeedError):
                    import_user_library_seed(database, load_user_library_seed(target))
                self.assertEqual(
                    LibrarySourceCatalogService(database).list_sources().items, (),
                )
                database.verify_integrity()


if __name__ == "__main__":
    unittest.main()
