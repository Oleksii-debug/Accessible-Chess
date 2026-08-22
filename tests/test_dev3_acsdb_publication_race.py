import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from acs.acsdb import AcsDatabase


PGN = '''[Event "Publication Race"]
[Site "Uzhhorod"]
[Date "2026.08.22"]
[Round "1"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 e5 1-0
'''


class Dev3AcsdbPublicationRaceTests(unittest.TestCase):
    def _populate(self, path: Path) -> None:
        with AcsDatabase(path) as db:
            db.import_pgn_text(PGN, "race-source.pgn")

    def _assert_competing_creator_wins(self, operation, destination: Path) -> None:
        real_link = os.link
        real_replace = os.replace
        competitor = b"competitor-wins"
        created = False

        def create_competitor_once() -> None:
            nonlocal created
            if not created:
                destination.write_bytes(competitor)
                created = True

        def raced_link(source, target, *args, **kwargs):
            if Path(target) == destination:
                create_competitor_once()
            return real_link(source, target, *args, **kwargs)

        def raced_replace(source, target, *args, **kwargs):
            if Path(target) == destination:
                create_competitor_once()
            return real_replace(source, target, *args, **kwargs)

        with mock.patch("acs.acsdb.os.link", side_effect=raced_link), mock.patch(
            "acs.acsdb.os.replace", side_effect=raced_replace
        ):
            with self.assertRaises(FileExistsError):
                operation()

        self.assertTrue(created)
        self.assertEqual(destination.read_bytes(), competitor)
        leftovers = [
            path
            for path in destination.parent.iterdir()
            if path.name.startswith(f".{destination.name}.") and path.suffix == ".tmp"
        ]
        self.assertEqual(leftovers, [])

    def test_backup_no_overwrite_is_atomic_against_final_publication_creator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live.acsdb"
            destination = root / "backup.acsdb"
            self._populate(live)

            with AcsDatabase(live) as db:
                self._assert_competing_creator_wins(
                    lambda: db.backup_to(destination, overwrite=False), destination
                )

    def test_restore_no_overwrite_is_atomic_against_final_publication_creator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live.acsdb"
            backup = root / "backup.acsdb"
            destination = root / "restored.acsdb"
            self._populate(live)
            with AcsDatabase(live) as db:
                db.backup_to(backup)

            self._assert_competing_creator_wins(
                lambda: AcsDatabase.restore_backup(backup, destination, overwrite=False),
                destination,
            )


if __name__ == "__main__":
    unittest.main()
