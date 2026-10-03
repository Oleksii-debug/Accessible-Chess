import unittest

from acs.acsdb import AcsDatabase
from acs.gametree import PgnGame, VariationLine
from acs.library_import_service import LibraryImportControlError, LibraryImportService


DIGEST = "A" * 64


def game(index: int) -> PgnGame:
    return PgnGame(
        tags={
            "Event": f"Library {index}",
            "White": f"White {index}",
            "Black": f"Black {index}",
            "Result": "*",
        },
        line=VariationLine(result="*"),
        source_index=index,
        warnings=[],
    )


class D07LibraryImportReuseFinalCancelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = AcsDatabase(":memory:")
        self.service = LibraryImportService(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_reuse_fails_closed_if_final_cancel_mutates_verified_game(self) -> None:
        original = self.service.import_games(
            (game(0),),
            source_name="original.pgn",
            source_format="pgn",
            source_sha256=DIGEST,
        )
        retry_game = game(0)
        calls = 0

        def cancel() -> bool:
            nonlocal calls
            calls += 1
            if calls == 3:
                retry_game.tags["Event"] = "Retargeted after reuse verification"
            return False

        with self.assertRaisesRegex(
            LibraryImportControlError,
            "Library import game changed after validation",
        ):
            self.service.import_games(
                [retry_game],
                source_name="retry-final-cancel.pgn",
                source_format="pgn",
                source_sha256=DIGEST,
                cancel_check=cancel,
            )

        self.assertEqual(calls, 3)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 1)
        stored = self.db.get_game(original.first_game_id)
        self.assertEqual(stored["event"], "Library 0")

        attempts = self.db.list_import_attempts()
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["status"], "failed")
        self.assertIsNone(attempts[0]["source_id"])
        self.assertEqual(
            attempts[0]["error_message"],
            "Library import game changed after validation",
        )


if __name__ == "__main__":
    unittest.main()
