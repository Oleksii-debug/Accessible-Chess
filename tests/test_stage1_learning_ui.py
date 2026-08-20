import unittest
from types import SimpleNamespace

from acs.acsdb import AcsDatabase
from acs.bookdocument import BookDocument, Game, Heading, Paragraph, Position
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI
from acs.training import ExerciseDefinition, ExerciseStep


BOOK_FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"
TRAINING_FEN = "7k/8/8/8/8/8/6R1/6K1 w - - 0 1"


class _FakeContinuousAnalysis:
    def __init__(self):
        self.running = False
        self.fen = None
        self.multipv = 5
        self.depth = 16
        self.last_result = None

    def start(self, fen, multipv=5, depth=16):
        self.running = True
        self.fen = fen
        self.multipv = multipv
        self.depth = depth
        return 1

    def update_position(self, fen):
        self.fen = fen
        return 1

    def stop(self):
        self.running = False
        return 1

    def close(self):
        self.running = False

    def state(self):
        return SimpleNamespace(
            running=self.running,
            fen=self.fen,
            multipv=self.multipv,
            depth=self.depth,
            last_result=self.last_result,
        )


def seed(database: AcsDatabase) -> None:
    database.save_book(
        BookDocument(
            "Reader",
            book_id="book:reader",
            blocks=[
                Heading(text="Chapter", block_id="chapter", source_anchor="p1"),
                Paragraph(text="Exact source paragraph", block_id="text", source_anchor="p2"),
                Position(fen=BOOK_FEN, caption="Explore", block_id="position", source_anchor="p3"),
            ],
        )
    )
    database.save_training_definition(
        ExerciseDefinition(
            "exercise:rook",
            TRAINING_FEN,
            (
                ExerciseStep(frozenset({"Rh2+"}), hint="Use the file"),
                ExerciseStep(frozenset({"Kg8"}), hint="Leave the file"),
            ),
            title="Rook exercise",
        )
    )


class Stage1LearningUiTests(unittest.TestCase):
    def setUp(self):
        self.database = AcsDatabase()
        seed(self.database)
        self.api = Stage1ReleaseAccessibleChessAPI(database=self.database)

    def tearDown(self):
        self.api.close_analysis()
        self.database.close()

    def test_book_exploration_restores_exact_text_and_chess_workspace(self):
        self.api.make_move("e4")
        original = self.api.get_state()
        self.assertTrue(self.api.open_book("book:reader")["ok"])
        self.assertTrue(self.api.book_go_to(1, 5)["ok"])
        source = self.api.get_state()["bookReader"]["location"]

        opened = self.api.open_book_chess_block(2)
        self.assertTrue(opened["ok"])
        temporary = self.api.get_state()
        self.assertEqual(temporary["mode"], "book")
        self.assertEqual(temporary["fen"], BOOK_FEN)
        self.assertEqual(temporary["bookReader"]["embedded"]["origin"], source)

        self.api.make_move("Kf3")
        returned = self.api.return_to_book_text()
        self.assertTrue(returned["ok"])
        restored = self.api.get_state()
        self.assertEqual(restored["fen"], original["fen"])
        self.assertEqual(restored["moves"], original["moves"])
        self.assertEqual(restored["bookReader"]["location"], source)
        self.assertIsNone(restored["bookReader"]["embedded"])

    def test_training_blocks_answer_leaks_and_canonical_board_mutations(self):
        self.api.make_move("d4")
        original = self.api.get_state()
        started = self.api.start_training("exercise:rook")
        self.assertTrue(started["ok"])
        state = self.api.get_state()
        self.assertEqual(state["mode"], "training")
        self.assertEqual(state["fen"], TRAINING_FEN)
        self.assertEqual(state["training"]["revealedMoves"], [])
        self.assertNotIn("Rh2", str(state["training"]))

        blocked_move = self.api.make_move("Rh2+")
        self.assertFalse(blocked_move["ok"])
        blocked_analysis = self.api.start_analysis()
        self.assertFalse(blocked_analysis["ok"])

        wrong = self.api.submit_training_move("Rh3")
        self.assertFalse(wrong["ok"])
        self.assertEqual(self.api.get_state()["fen"], TRAINING_FEN)
        reveal = self.api.reveal_training_solution()
        self.assertTrue(reveal["ok"])
        self.assertEqual(self.api.get_state()["training"]["revealedMoves"], ["Rh2+"])

        self.assertTrue(self.api.submit_training_move("g2h2")["ok"])
        self.assertEqual(
            self.api.get_state()["fen"],
            "7k/8/8/8/8/8/7R/6K1 b - - 1 1",
        )
        self.assertFalse(self.api.reveal_training_solution()["ok"])
        self.assertFalse(self.api.submit_training_move("Kh7")["ok"])
        self.assertTrue(self.api.reveal_training_solution()["ok"])
        self.assertTrue(self.api.submit_training_move("Kg8")["ok"])
        self.assertTrue(self.api.get_state()["training"]["analysisAllowed"])

        closed = self.api.close_training()
        self.assertTrue(closed["ok"])
        restored = self.api.get_state()
        self.assertEqual(restored["fen"], original["fen"])
        self.assertEqual(restored["moves"], original["moves"])

    def test_invalid_imports_are_concise_and_do_not_create_rows(self):
        before = self.database.catalog_counts()
        book = self.api.import_book_json('{"schema_version":2,"title":"Bad","blocks":[{"kind":"Position","fen":"8/8/8/8/8/8/8/8 w - - 0 1"}],"language":null,"author":null,"source_name":null,"book_id":"bad","warnings":[]}')
        training = self.api.import_training_json('{"schema_version":1}')
        self.assertFalse(book["ok"])
        self.assertFalse(training["ok"])
        self.assertNotIn("Traceback", book["announcement"])
        self.assertNotIn("ValueError", training["announcement"])
        after = self.database.catalog_counts()
        self.assertEqual(after["books"], before["books"])
        self.assertEqual(after["training_definitions"], before["training_definitions"])

    def test_database_game_reference_opens_through_the_canonical_gametree(self):
        report = self.database.import_pgn_text('[Result "*"]\n\n1. e4 e5 *')
        game_id = report.game_ids[0]
        self.database.save_book(
            BookDocument(
                "Database-linked book",
                book_id="book:database-linked",
                blocks=[Game(game_id=game_id, title="Linked game")],
            )
        )

        self.assertTrue(self.api.open_book("book:database-linked")["ok"])
        self.assertTrue(self.api.open_book_chess_block()["ok"])
        self.assertEqual(self.api.get_state()["fen"], self.api.board.START)

    def test_training_restores_the_exact_prior_analysis_enabled_state(self):
        self.api.close_analysis()
        fake = _FakeContinuousAnalysis()
        api = Stage1ReleaseAccessibleChessAPI(
            database=self.database,
            continuous_analysis=fake,
        )
        try:
            self.assertTrue(api.start_analysis()["ok"])
            self.assertTrue(api.get_state()["analysis"]["enabled"])
            self.assertTrue(api.start_training("exercise:rook")["ok"])
            self.assertFalse(api.get_state()["analysis"]["enabled"])
            self.assertTrue(api.close_training()["ok"])
            self.assertTrue(api.get_state()["analysis"]["enabled"])

            self.assertTrue(api.stop_analysis()["ok"])
            self.assertTrue(api.start_training("exercise:rook")["ok"])
            self.assertTrue(api.submit_training_move("Rh2+")["ok"])
            self.assertTrue(api.submit_training_move("Kg8")["ok"])
            self.assertTrue(api.analyze_training_position()["ok"])
            self.assertTrue(api.get_state()["analysis"]["enabled"])
            self.assertTrue(api.close_training()["ok"])
            self.assertFalse(api.get_state()["analysis"]["enabled"])
        finally:
            api.close_analysis()


if __name__ == "__main__":
    unittest.main()
