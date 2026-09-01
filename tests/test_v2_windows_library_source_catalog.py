from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import time
import unittest

from acs.acsdb import AcsDatabase
from acs.gametree import PgnGame, VariationLine
from acs.library_import_service import LibraryImportService
from acs.library_source_service import (
    LibrarySourceCatalogService,
    SourceCatalogCancelledError,
)
from acs.search_service import GameSearchPage
from acs.version2_windows_library_source_catalog import (
    SourceCatalogUiAction,
    SourceCatalogUiEventKind,
    Version2WindowsLibrarySourceCatalogController,
)


def _game(index: int) -> PgnGame:
    return PgnGame(
        tags={
            "Event": f"Catalog {index}",
            "White": f"White {index}",
            "Black": f"Black {index}",
            "Result": "*",
        },
        line=VariationLine(result="*"),
        source_index=index,
    )


class _BlockingCatalog(LibrarySourceCatalogService):
    def __init__(self, entered: threading.Event) -> None:
        self._entered = entered

    def list_sources(self, query=None, *, cancel_check=None):
        self._entered.set()
        assert cancel_check is not None
        while not cancel_check():
            time.sleep(0.005)
        raise SourceCatalogCancelledError("private cancellation detail")


class _FailureCatalog(LibrarySourceCatalogService):
    def __init__(self) -> None:
        pass

    def list_sources(self, query=None, *, cancel_check=None):
        raise RuntimeError(r"C:\Users\Private\library.acsdb traceback provider=secret")


class _DelayedCatalog(LibrarySourceCatalogService):
    def __init__(
        self,
        database: AcsDatabase,
        *,
        detail_entered: threading.Event,
        detail_release: threading.Event,
        games_entered: threading.Event,
        games_release: threading.Event,
    ) -> None:
        super().__init__(database)
        self._detail_entered = detail_entered
        self._detail_release = detail_release
        self._games_entered = games_entered
        self._games_release = games_release

    def get_source(self, source_id: int, *, cancel_check=None):
        self._detail_entered.set()
        if not self._detail_release.wait(5.0):
            raise RuntimeError("detail test gate timed out")
        return super().get_source(source_id, cancel_check=cancel_check)

    def source_games(
        self,
        source_id: int,
        *,
        after_game_id: int | None = None,
        limit: int = 50,
        cancel_check=None,
    ):
        self._games_entered.set()
        if not self._games_release.wait(5.0):
            raise RuntimeError("games test gate timed out")
        return super().source_games(
            source_id,
            after_game_id=after_game_id,
            limit=limit,
            cancel_check=cancel_check,
        )


class V2WindowsLibrarySourceCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "library.acsdb"
        self.factory_threads: list[str] = []
        self.cleanup_threads: list[str] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _import(
        self,
        *,
        source_name: str,
        digest_char: str,
        source_format: str = "pgn",
        game_count: int = 1,
    ) -> int:
        with AcsDatabase(self.db_path) as database:
            result = LibraryImportService(database).import_games(
                tuple(_game(index) for index in range(game_count)),
                source_name=source_name,
                source_format=source_format,
                source_sha256=digest_char * 64,
            )
            return result.source_id

    def _add_empty(self, *, source_name: str, digest_char: str, source_format: str = "pgn") -> int:
        with AcsDatabase(self.db_path) as database:
            return database.add_source(source_name, source_format, digest_char * 64)

    def _factory(self):
        self.factory_threads.append(threading.current_thread().name)
        database = AcsDatabase(self.db_path)
        service = LibrarySourceCatalogService(database)

        def cleanup() -> None:
            self.cleanup_threads.append(threading.current_thread().name)
            database.close()

        return service, cleanup

    @staticmethod
    def _flush(posted: list[object]) -> None:
        while posted:
            callback = posted.pop(0)
            assert callable(callback)
            callback()

    def _complete(self, controller, posted: list[object]) -> None:
        self.assertTrue(controller.wait(15.0))
        self.assertTrue(controller.join(1.0))
        self._flush(posted)

    def _controller(self, *, page_size: int = 50):
        events = []
        games = []
        posted: list[object] = []
        controller = Version2WindowsLibrarySourceCatalogController(
            self._factory,
            event_sink=events.append,
            trusted_games_sink=games.append,
            post_to_ui=posted.append,
            page_size=page_size,
        )
        return controller, events, games, posted

    def test_real_catalog_pages_are_path_and_private_identity_free(self) -> None:
        self._import(
            source_name=r"C:\Users\Oleksii\Private\one.pgn",
            digest_char="a",
        )
        self._import(
            source_name="/home/private/databases/two.cbh",
            digest_char="b",
            source_format="cbh",
        )
        self._import(
            source_name="D:drive-relative.pgn",
            digest_char="c",
        )

        controller, events, _, posted = self._controller(page_size=10)
        self.assertTrue(controller.load())
        self._complete(controller, posted)
        page = controller.page
        self.assertIsNotNone(page)
        assert page is not None
        self.assertEqual(
            [row.source_name for row in page.rows],
            ["one.pgn", "two.cbh", "drive-relative.pgn"],
        )
        self.assertEqual(page.focus_target, "library-source-0")
        self.assertFalse(page.has_previous)
        for row in page.rows:
            self.assertFalse(hasattr(row, "source_id"))
            self.assertFalse(hasattr(row, "source_sha256"))
            self.assertFalse(hasattr(row, "latest_attempt_id"))
            self.assertFalse(hasattr(row, "first_game_id"))
            self.assertFalse(hasattr(row, "last_game_id"))

        rendered = "\n".join(repr(event) for event in events)
        for token in (
            r"C:\Users\Oleksii\Private",
            "/home/private/databases",
            "D:drive-relative",
            "a" * 64,
            "b" * 64,
            "c" * 64,
            "source_id=",
            "latest_attempt_id=",
        ):
            self.assertNotIn(token, rendered)
        self.assertTrue(self.factory_threads)
        self.assertEqual(self.factory_threads, self.cleanup_threads)
        self.assertTrue(
            all(name.startswith("AccessibleChess-V2-SourceCatalog-") for name in self.factory_threads)
        )

    def test_forward_backward_history_uses_presentation_actions_and_new_generations(self) -> None:
        for index, digest in enumerate("abcde"):
            self._import(
                source_name=f"source-{index}.pgn",
                digest_char=digest,
            )
        controller, events, _, posted = self._controller(page_size=2)

        self.assertTrue(controller.load())
        self._complete(controller, posted)
        page1 = controller.page
        assert page1 is not None
        self.assertEqual(events[-1].kind, SourceCatalogUiEventKind.PAGE)
        self.assertEqual(events[-1].action, SourceCatalogUiAction.LOAD)
        self.assertTrue(page1.has_next)
        self.assertFalse(page1.has_previous)

        self.assertTrue(controller.next_page())
        self._complete(controller, posted)
        page2 = controller.page
        assert page2 is not None
        self.assertGreater(page2.generation, page1.generation)
        self.assertEqual(events[-1].action, SourceCatalogUiAction.NEXT_PAGE)
        self.assertTrue(page2.has_previous)
        self.assertEqual([row.source_name for row in page2.rows], ["source-2.pgn", "source-3.pgn"])

        self._import(source_name="source-5.pgn", digest_char="f")

        self.assertTrue(controller.previous_page())
        self._complete(controller, posted)
        back = controller.page
        assert back is not None
        self.assertGreater(back.generation, page2.generation)
        self.assertEqual(events[-1].action, SourceCatalogUiAction.PREVIOUS_PAGE)
        self.assertEqual([row.source_name for row in back.rows], ["source-0.pgn", "source-1.pgn"])
        self.assertFalse(back.has_previous)

    def test_selection_is_generation_scoped_and_strictly_typed(self) -> None:
        self._import(source_name="one.pgn", digest_char="a")
        self._import(source_name="two.pgn", digest_char="b")
        controller, events, _, posted = self._controller()
        self.assertTrue(controller.load())
        self._complete(controller, posted)
        first = controller.page
        assert first is not None

        self.assertTrue(controller.select(1, generation=first.generation))
        self._flush(posted)
        selected = controller.page
        assert selected is not None
        self.assertEqual(selected.selected_index, 1)
        self.assertEqual(selected.focus_target, "library-source-1")
        self.assertEqual(events[-1].kind, SourceCatalogUiEventKind.SELECTION)
        self.assertEqual(events[-1].detail.source_name, "two.pgn")

        self.assertTrue(controller.refresh())
        self._complete(controller, posted)
        refreshed = controller.page
        assert refreshed is not None
        self.assertGreater(refreshed.generation, first.generation)
        self.assertFalse(controller.select(0, generation=first.generation))
        with self.assertRaises(TypeError):
            controller.select(True, generation=refreshed.generation)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            controller.select(0, generation=False)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            controller.select(-1, generation=refreshed.generation)

    def test_selected_detail_and_game_handoff_reuse_exact_canonical_services(self) -> None:
        source_id = self._import(
            source_name=r"C:\Private\games.pgn",
            digest_char="a",
            game_count=5,
        )
        controller, events, games, posted = self._controller()
        self.assertTrue(controller.load())
        self._complete(controller, posted)
        page = controller.page
        assert page is not None
        self.assertTrue(controller.select(0, generation=page.generation))
        self._flush(posted)

        self.assertTrue(controller.selected_detail())
        self._complete(controller, posted)
        self.assertEqual(events[-1].kind, SourceCatalogUiEventKind.DETAIL)
        self.assertEqual(events[-1].detail.source_name, "games.pgn")
        self.assertFalse(hasattr(events[-1].detail, "source_id"))

        self.assertTrue(controller.open_selected_games(limit=2))
        self._complete(controller, posted)
        self.assertEqual(len(games), 1)
        self.assertIsInstance(games[0], GameSearchPage)
        self.assertEqual(len(games[0].items), 2)
        self.assertTrue(all(item.source_id == source_id for item in games[0].items))
        self.assertEqual(events[-1].kind, SourceCatalogUiEventKind.GAMES_READY)
        self.assertEqual(events[-1].focus_target, "library-game-list")
        self.assertNotIn(str(source_id), repr(events[-1]))
        self.assertNotIn("start_fen", repr(events[-1]))

    def test_async_detail_and_games_do_not_publish_for_a_changed_same_page_selection(self) -> None:
        first_source = self._import(
            source_name="first.pgn",
            digest_char="a",
            game_count=3,
        )
        self._import(
            source_name="second.pgn",
            digest_char="b",
            game_count=2,
        )
        detail_entered = threading.Event()
        detail_release = threading.Event()
        games_entered = threading.Event()
        games_release = threading.Event()
        events = []
        games = []
        posted: list[object] = []

        def factory():
            database = AcsDatabase(self.db_path)
            service = _DelayedCatalog(
                database,
                detail_entered=detail_entered,
                detail_release=detail_release,
                games_entered=games_entered,
                games_release=games_release,
            )
            return service, database.close

        controller = Version2WindowsLibrarySourceCatalogController(
            factory,
            event_sink=events.append,
            trusted_games_sink=games.append,
            post_to_ui=posted.append,
        )
        self.assertTrue(controller.load())
        self._complete(controller, posted)
        page = controller.page
        assert page is not None
        generation = page.generation
        self.assertTrue(controller.select(0, generation=generation))
        self._flush(posted)

        self.assertTrue(controller.selected_detail())
        self.assertTrue(detail_entered.wait(5.0))
        self.assertTrue(controller.select(1, generation=generation))
        self._flush(posted)
        detail_release.set()
        self._complete(controller, posted)
        self.assertEqual(events[-1].kind, SourceCatalogUiEventKind.SELECTION)
        self.assertEqual(events[-1].detail.source_name, "second.pgn")
        self.assertFalse(any(event.kind == SourceCatalogUiEventKind.DETAIL for event in events[-2:]))

        self.assertTrue(controller.select(0, generation=generation))
        self._flush(posted)
        marker = len(events)
        self.assertTrue(controller.open_selected_games(limit=2))
        self.assertTrue(games_entered.wait(5.0))
        self.assertTrue(controller.select(1, generation=generation))
        self._flush(posted)
        games_release.set()
        self._complete(controller, posted)
        self.assertEqual(games, [])
        self.assertFalse(
            any(
                event.kind == SourceCatalogUiEventKind.GAMES_READY
                for event in events[marker:]
            )
        )
        self.assertEqual(events[-1].kind, SourceCatalogUiEventKind.SELECTION)
        self.assertEqual(events[-1].detail.source_name, "second.pgn")
        self.assertNotIn(str(first_source), repr(events[-1]))

    def test_format_filter_and_zero_game_source_are_preserved_without_ui_search_truth(self) -> None:
        self._import(source_name="one.pgn", digest_char="a", source_format="PGN")
        self._import(source_name="two.cbh", digest_char="b", source_format="cbh")
        self._add_empty(source_name="empty.cbh", digest_char="c", source_format="cbh")
        controller, _, _, posted = self._controller(page_size=10)
        self.assertTrue(controller.load(source_format=" cBh "))
        self._complete(controller, posted)
        page = controller.page
        assert page is not None
        self.assertEqual([row.source_name for row in page.rows], ["two.cbh", "empty.cbh"])
        self.assertEqual(page.rows[1].game_count, 0)
        self.assertEqual(page.rows[1].attempt_count, 0)
        self.assertIsNone(page.rows[1].latest_attempt_status)
        with self.assertRaises(TypeError):
            controller.load(source_format=3)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            Version2WindowsLibrarySourceCatalogController(
                self._factory,
                event_sink=lambda event: None,
                trusted_games_sink=lambda page: None,
                post_to_ui=lambda callback: callback(),
                page_size=201,
            )

    def test_cancel_is_canonical_cooperative_and_cleanup_remains_worker_owned(self) -> None:
        entered = threading.Event()
        cleanup_threads: list[str] = []
        factory_threads: list[str] = []
        posted: list[object] = []
        events = []

        def factory():
            factory_threads.append(threading.current_thread().name)

            def cleanup() -> None:
                cleanup_threads.append(threading.current_thread().name)

            return _BlockingCatalog(entered), cleanup

        controller = Version2WindowsLibrarySourceCatalogController(
            factory,
            event_sink=events.append,
            trusted_games_sink=lambda page: None,
            post_to_ui=posted.append,
        )
        self.assertTrue(controller.load())
        self.assertTrue(entered.wait(5.0))
        self.assertFalse(controller.load())
        self.assertTrue(controller.cancel())
        self._complete(controller, posted)
        self.assertEqual(events[-1].kind, SourceCatalogUiEventKind.CANCELLED)
        self.assertEqual(events[-1].action, SourceCatalogUiAction.LOAD)
        self.assertEqual(factory_threads, cleanup_threads)
        self.assertTrue(factory_threads[0].startswith("AccessibleChess-V2-SourceCatalog-"))
        self.assertFalse(controller.cancel())

    def test_backend_failure_is_bounded_and_path_free(self) -> None:
        posted: list[object] = []
        events = []
        controller = Version2WindowsLibrarySourceCatalogController(
            lambda: _FailureCatalog(),
            event_sink=events.append,
            trusted_games_sink=lambda page: None,
            post_to_ui=posted.append,
        )
        self.assertTrue(controller.load())
        self._complete(controller, posted)
        failed = events[-1]
        self.assertEqual(failed.kind, SourceCatalogUiEventKind.FAILED)
        self.assertEqual(failed.error_code, "SOURCE_CATALOG_UNAVAILABLE")
        rendered = repr(failed)
        for token in ("Users", "Private", "library.acsdb", "traceback", "provider"):
            self.assertNotIn(token, rendered)

    def test_ui_post_failure_never_falls_back_to_worker_thread(self) -> None:
        self._import(source_name="one.pgn", digest_char="a")
        sink_calls = []

        def broken_poster(callback):
            raise RuntimeError(r"C:\private\ui-post.txt")

        controller = Version2WindowsLibrarySourceCatalogController(
            self._factory,
            event_sink=sink_calls.append,
            trusted_games_sink=lambda page: sink_calls.append(page),
            post_to_ui=broken_poster,
        )
        self.assertTrue(controller.load())
        self.assertTrue(controller.wait(10.0))
        self.assertEqual(sink_calls, [])
        self.assertIsNotNone(controller.page)


if __name__ == "__main__":
    unittest.main()
