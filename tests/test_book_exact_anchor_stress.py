from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_board_workflow import BookBoardWorkflow
from acs.book_progress_store import BookProgressStore
from acs.book_text_import import BookTextFormat, import_text_book
from acs.bookdocument import BookDocument, Game, Paragraph, Position, VariationTree
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.engine_ports import RawAnalysisLine
from acs.version2_application import Version2Application


NESTED_GAME = '''[Event "Exact anchor stress"]
[Result "*"]

1. e4 (1. d4 d5 (1... Nf6) 2. c4) e5 2. Nf3 *
'''


class _FakeAnalysisEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
        self.calls.append((fen, multipv, depth))
        return (
            RawAnalysisLine(
                depth=depth,
                score_kind="cp",
                score_value=17,
                pv=("e2e4",),
            ),
        )

    def close(self) -> None:
        return None


class BookExactAnchorStressTests(unittest.TestCase):
    @staticmethod
    def _large_document() -> BookDocument:
        blocks = []
        for index in range(700):
            common = {
                "block_id": f"block-{index:04d}",
                "source_anchor": f"semantic:{index:04d}",
            }
            if index == 137:
                blocks.append(Position(fen=Board.START, caption="Embedded position", **common))
            elif index == 311:
                blocks.append(Game(pgn=NESTED_GAME, title="Embedded nested game", **common))
            elif index == 487:
                blocks.append(
                    VariationTree(
                        root_fen=Board.START,
                        pgn=NESTED_GAME,
                        title="Embedded nested variation",
                        **common,
                    )
                )
            else:
                blocks.append(Paragraph(text=f"Readable block {index}", **common))
        return BookDocument(
            title="Exact semantic anchor stress",
            language="uk",
            source_name="evidence-only.md",
            blocks=blocks,
        )

    def test_hundreds_of_blocks_named_bookmarks_snapshot_reopen_and_reorder_are_exact(self) -> None:
        document = self._large_document()
        reader = BookReader(document)
        bookmarked: dict[str, str] = {}
        for index in range(0, 700, 13):
            reader.go_to(index)
            name = f"bookmark-{index:04d}"
            reader.save_return_point(name)
            bookmarked[name] = document.blocks[index].block_id

        reader.go_to(487)
        expected_current = reader.location()
        snapshot = reader.snapshot()

        reopened_document = BookDocument.from_dict(document.as_dict())
        reopened = BookReader.restore_snapshot(reopened_document, snapshot)
        self.assertEqual(reopened.location().block_id, expected_current.block_id)
        self.assertEqual(reopened.location().source_anchor, expected_current.source_anchor)
        self.assertEqual(reopened.location().kind, expected_current.kind)

        for name, expected_block_id in bookmarked.items():
            restored = reopened.restore_return_point(name)
            self.assertEqual(
                restored.block_id,
                expected_block_id,
                f"named bookmark {name} drifted to a nearby block",
            )

        reordered_document = BookDocument.from_dict(document.as_dict())
        reordered_document.blocks = (
            reordered_document.blocks[350:]
            + reordered_document.blocks[:350]
        )
        reordered = BookReader.restore_snapshot(reordered_document, snapshot)
        self.assertEqual(reordered.location().block_id, expected_current.block_id)
        self.assertEqual(reordered.location().source_anchor, expected_current.source_anchor)
        for name, expected_block_id in bookmarked.items():
            self.assertEqual(
                reordered.restore_return_point(name).block_id,
                expected_block_id,
                f"semantic reorder changed named bookmark {name}",
            )

    def test_position_game_variation_nested_navigation_analysis_and_return_are_exact(self) -> None:
        document = self._large_document()
        reader = BookReader(document)
        engine = _FakeAnalysisEngine()
        analysis = AnalysisService(lambda: engine)
        self.addCleanup(analysis.close)
        assisted = EngineAssistedWorkflowService(analysis)

        with tempfile.TemporaryDirectory() as root:
            store = BookProgressStore(Path(root) / "book-progress.json")
            for index in (137, 311, 487):
                with self.subTest(index=index):
                    reader.go_to(index)
                    user_bookmark = f"user-{index}"
                    reader.save_return_point(user_bookmark)
                    origin = reader.location()
                    expected_user_target = reader.snapshot()["return_points"][user_bookmark]
                    workflow = BookBoardWorkflow(reader, assisted)
                    opened = workflow.open_current()
                    self.assertEqual(opened.origin, origin)
                    self.assertEqual(reader.location(), origin)

                    if index in (311, 487):
                        workflow.next_move()
                        workflow.enter_variation(0)
                        workflow.next_move()
                        workflow.next_move()
                        workflow.enter_variation(0)
                        workflow.next_move()
                        analyzed = workflow.analyze(multipv=3, depth=7)
                        self.assertFalse(analyzed.stale)
                        self.assertIsNone(analyzed.error)
                        workflow.leave_variation()
                        workflow.leave_variation()
                    else:
                        analyzed = workflow.analyze(multipv=2, depth=5)
                        self.assertFalse(analyzed.stale)
                        self.assertIsNone(analyzed.error)

                    restored = workflow.return_to_book()
                    self.assertEqual(restored, origin)
                    self.assertEqual(reader.location(), origin)
                    self.assertFalse(workflow.active)
                    self.assertEqual(
                        reader.snapshot()["return_points"][user_bookmark],
                        expected_user_target,
                    )

                    store.save("stress-book", reader)
                    restarted = store.restore(
                        "stress-book",
                        BookDocument.from_dict(document.as_dict()),
                    )
                    self.assertEqual(restarted.location().block_id, origin.block_id)
                    self.assertEqual(restarted.location().source_anchor, origin.source_anchor)
                    self.assertEqual(
                        restarted.restore_return_point(user_bookmark).block_id,
                        origin.block_id,
                    )

        self.assertGreaterEqual(len(engine.calls), 3)

    def test_source_replacement_gets_new_identity_and_reopening_old_bytes_restores_exact_old_anchor(self) -> None:
        old_bytes = (
            "# Identity book\n\n"
            + "\n\n".join(f"Old paragraph {index}" for index in range(320))
            + "\n"
        ).encode("utf-8")
        new_bytes = old_bytes.replace(b"Old paragraph 17", b"Replacement paragraph 17", 1)

        old_import = import_text_book(
            old_bytes,
            source_name="same-name.md",
            source_format=BookTextFormat.MARKDOWN,
        )
        new_import = import_text_book(
            new_bytes,
            source_name="same-name.md",
            source_format=BookTextFormat.MARKDOWN,
        )
        self.assertNotEqual(old_import.source_sha256, new_import.source_sha256)
        self.assertNotEqual(old_import.book_key, new_import.book_key)

        reader = BookReader(old_import.document)
        reader.go_to(211)
        reader.save_return_point("old-source-bookmark")
        old_location = reader.location()

        with tempfile.TemporaryDirectory() as root:
            store = BookProgressStore(Path(root) / "book-progress.json")
            store.save(old_import.book_key, reader)
            self.assertTrue(store.has(old_import.book_key))
            self.assertFalse(store.has(new_import.book_key))
            with self.assertRaises(LookupError):
                store.restore(new_import.book_key, new_import.document)

            old_again = import_text_book(
                old_bytes,
                source_name="same-name.md",
                source_format=BookTextFormat.MARKDOWN,
            )
            self.assertEqual(old_again.book_key, old_import.book_key)
            reopened_old = store.restore(old_again.book_key, old_again.document)
            self.assertEqual(reopened_old.location().block_id, old_location.block_id)
            self.assertEqual(reopened_old.location().source_anchor, old_location.source_anchor)
            self.assertEqual(
                reopened_old.restore_return_point("old-source-bookmark").block_id,
                old_location.block_id,
            )

    def test_failed_progress_write_during_return_still_restarts_at_exact_origin(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            database = AcsDatabase(root / "library.acsdb")
            self.addCleanup(database.close)
            analysis = AnalysisService(lambda: None)
            self.addCleanup(analysis.close)
            progress = BookProgressStore(root / "book-progress.json")
            app = Version2Application(
                database,
                progress_store=progress,
                engine_assistance=EngineAssistedWorkflowService(analysis),
                board_dispatch=lambda *_: None,
            )
            book = root / "return.md"
            book.write_text(
                "# Return\n\nBefore\n\n```pgn\n"
                + NESTED_GAME
                + "```\n\nAfter\n",
                encoding="utf-8",
            )
            app.open_book(book)
            moved = app.browser_command("books", "book.next_game")
            self.assertEqual(moved["kind"], "render")
            origin = app.reader.location()
            key = app.book_key

            opened = app.browser_command("books", "book.open_position")
            self.assertEqual(opened["kind"], "delegated")
            self.assertTrue(app.book_workflow.active)
            app.router.dispatch("book.board_next_move")
            app.router.dispatch("book.board_enter_variation")
            app.router.dispatch("book.board_next_move")

            with patch.object(
                progress,
                "save",
                side_effect=OSError("simulated return progress failure"),
            ):
                result = app.browser_command("books", "book.return_from_board")

            self.assertEqual(result["kind"], "error")
            self.assertFalse(app.book_workflow.active)
            self.assertEqual(app.reader.location(), origin)

            restarted = progress.restore(key, BookDocument.from_dict(app.reader.document.as_dict()))
            self.assertEqual(restarted.location().block_id, origin.block_id)
            self.assertEqual(restarted.location().source_anchor, origin.source_anchor)


if __name__ == "__main__":
    unittest.main()
