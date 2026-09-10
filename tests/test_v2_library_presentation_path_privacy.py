from __future__ import annotations

import unittest

from acs.full_product_presenters import (
    LibraryPresenter,
    LibraryRowView,
    LibraryView,
    SurfaceStatus,
)
from acs.full_product_ui_shell import UILanguage
from acs.library_webview_projection import (
    LibraryImportWebViewProjection,
    LibraryWebViewProjection,
    _scrub_visible_text,
)
from acs.search_service import GameSearchPage, GameSearchQuery


class _EmptySearchService:
    def search(self, query: GameSearchQuery) -> GameSearchPage:
        return GameSearchPage(items=(), next_after_game_id=None, has_more=False)


class _StaticLibraryPresenter(LibraryPresenter):
    def __init__(self, view: LibraryView, *, language: UILanguage) -> None:
        super().__init__(_EmptySearchService(), language=language)
        self._static_view = view

    def view(self) -> LibraryView:
        return self._static_view


class V2LibraryPresentationPathPrivacyTests(unittest.TestCase):
    PRIVATE_PATHS = (
        r"C:\Users\PrivateUser\Documents\library.pgn",
        r"C:Users\PrivateUser\Documents\library.pgn",
        r"\\server\private-share\PrivateUser\library.pgn",
        r"\\?\C:\Users\PrivateUser\Documents\library.pgn",
        "file:///C:/Users/PrivateUser/Documents/library.pgn",
        "/home/PrivateUser/library.pgn",
        "/opt/accessible-chess/private/library.pgn",
        "/srv/accessible-chess/private/library.pgn",
        "/etc/accessible-chess/private.conf",
        "/run/user/1000/private.sock",
        "/root/private/library.pgn",
        "/Applications/AccessibleChess/private/library.pgn",
    )

    @staticmethod
    def _projection(view: LibraryView, *, language: UILanguage = UILanguage.EN) -> LibraryWebViewProjection:
        presenter = _StaticLibraryPresenter(view, language=language)
        return LibraryWebViewProjection(
            presenter,
            lambda _action, _payload: None,
            language=language,
        )

    @staticmethod
    def _assert_private_path_hidden(test: unittest.TestCase, visible: object) -> None:
        text = repr(visible)
        test.assertIn("local path hidden", text.casefold())
        test.assertNotIn("PrivateUser", text)
        test.assertNotIn("private-share", text)

    def test_cross_platform_private_paths_are_redacted_before_webview_projection(self) -> None:
        for raw in self.PRIVATE_PATHS:
            with self.subTest(raw=raw):
                english = _scrub_visible_text(
                    f"Library source {raw}", language=UILanguage.EN, limit=2000
                )
                ukrainian = _scrub_visible_text(
                    f"Джерело бібліотеки {raw}", language=UILanguage.UA, limit=2000
                )
                self.assertIn("[local path hidden]", english)
                self.assertIn("[локальний шлях приховано]", ukrainian)
                self.assertNotIn("PrivateUser", english)
                self.assertNotIn("PrivateUser", ukrainian)
                self.assertNotIn("private-share", english)

    def test_real_library_row_source_title_result_message_and_summary_are_scrubbed(self) -> None:
        for raw in self.PRIVATE_PATHS:
            with self.subTest(raw=raw):
                ready_view = LibraryView(
                    status=SurfaceStatus.READY,
                    rows=(
                        LibraryRowView(
                            game_id=1,
                            label=f"Game title {raw}",
                            source_label=f"Source {raw}",
                            result=f"Result {raw}",
                            selected=False,
                        ),
                    ),
                    selected_game_id=None,
                    has_previous_page=False,
                    has_next_page=False,
                )
                ready_snapshot = self._projection(ready_view).snapshot()
                self._assert_private_path_hidden(
                    self,
                    {
                        "label": ready_snapshot["rows"][0]["label"],
                        "source_label": ready_snapshot["rows"][0]["source_label"],
                        "result": ready_snapshot["rows"][0]["result"],
                    },
                )

                error_view = LibraryView(
                    status=SurfaceStatus.ERROR,
                    rows=(),
                    selected_game_id=None,
                    has_previous_page=False,
                    has_next_page=False,
                    message=f"Library failure at {raw}",
                )
                error_snapshot = self._projection(error_view).snapshot()
                self._assert_private_path_hidden(
                    self,
                    {
                        "message": error_snapshot["message"],
                        "summary": error_snapshot["summary"],
                    },
                )

    def test_import_error_message_progress_and_nvda_announcement_are_scrubbed(self) -> None:
        for raw in self.PRIVATE_PATHS:
            with self.subTest(raw=raw):
                projection = LibraryImportWebViewProjection(
                    lambda _action, _payload: None,
                    language=UILanguage.EN,
                )
                projection.begin(1)
                event = projection.fail(RuntimeError(f"Import failure at {raw}"))
                self._assert_private_path_hidden(
                    self,
                    {
                        "message": event.payload["import"]["message"],
                        "progress_label": event.payload["import"]["progress_label"],
                        "announcement": event.payload["announcement"],
                    },
                )

    def test_safe_call_error_event_is_scrubbed(self) -> None:
        empty_view = LibraryView(
            status=SurfaceStatus.EMPTY,
            rows=(),
            selected_game_id=None,
            has_previous_page=False,
            has_next_page=False,
        )
        projection = self._projection(empty_view)
        for raw in self.PRIVATE_PATHS:
            with self.subTest(raw=raw):
                def fail() -> object:
                    raise RuntimeError(f"Library action failed at {raw}")

                event = projection.safe_call(fail)
                self.assertEqual("error", event.kind)
                self._assert_private_path_hidden(self, event.payload)

    def test_safe_domain_text_is_preserved(self) -> None:
        safe_values = (
            "https://example.com/chess/library",
            "/help",
            "incoming/library/study.pgn",
            "incoming\\library\\study.pgn",
            "8/8/8/8/8/8/4P3/4K2k w - - 0 1",
            "1. e4 e5 2. Nf3 Nc6",
            "Evaluation: +0.35",
            "Candidates Final — Round 7",
        )
        for value in safe_values:
            with self.subTest(value=value):
                self.assertEqual(
                    value,
                    _scrub_visible_text(value, language=UILanguage.EN, limit=2000),
                )

    def test_safe_library_payload_text_is_not_over_redacted(self) -> None:
        title = "Candidates Final — Round 7; 1. e4 e5 2. Nf3 Nc6; 8/8/8/8/8/8/4P3/4K2k w - - 0 1"
        source = "https://example.com/chess/library"
        relative_source = "incoming/library/study.pgn"
        view = LibraryView(
            status=SurfaceStatus.READY,
            rows=(
                LibraryRowView(1, title, source, "1-0", False),
                LibraryRowView(2, "Ordinary study title", relative_source, "1/2-1/2", False),
            ),
            selected_game_id=None,
            has_previous_page=False,
            has_next_page=False,
            message="",
        )
        snapshot = self._projection(view).snapshot()
        self.assertEqual(title, snapshot["rows"][0]["label"])
        self.assertEqual(source, snapshot["rows"][0]["source_label"])
        self.assertEqual("1-0", snapshot["rows"][0]["result"])
        self.assertEqual("Ordinary study title", snapshot["rows"][1]["label"])
        self.assertEqual(relative_source, snapshot["rows"][1]["source_label"])
        self.assertEqual("1/2-1/2", snapshot["rows"][1]["result"])


if __name__ == "__main__":
    unittest.main()
