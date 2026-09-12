from __future__ import annotations

import unittest

import acs.book_webview_projection as book_projection_module
import acs.presentation_privacy as presentation_privacy
import acs.training_webview_projection as training_projection_module
from acs.book_webview_projection import BookWebViewProjection, _safe_text as book_safe_text
from acs.full_product_presenters import (
    BookBlockView,
    BookReaderPresenter,
    TrainingPresenter,
    TrainingView,
)
from acs.full_product_ui_shell import UILanguage
from acs.presentation_privacy import redact_local_paths
from acs.training import ExerciseStatus
from acs.training_webview_projection import (
    TrainingWebViewProjection,
    _safe_text as training_safe_text,
)


class _StaticBookPresenter(BookReaderPresenter):
    def __init__(self, block: BookBlockView) -> None:
        self._block = block
        self._language = UILanguage.EN

    def set_language(self, language: UILanguage) -> None:
        self._language = language

    def current(self) -> BookBlockView:
        return self._block


class _StaticTrainingPresenter(TrainingPresenter):
    def __init__(self, view: TrainingView) -> None:
        self._view = view
        self._language = UILanguage.EN

    def set_language(self, language: UILanguage) -> None:
        self._language = language

    def view(self) -> TrainingView:
        return self._view


class V2SharedPresentationPathPrivacyTests(unittest.TestCase):
    PRIVATE_PATHS = (
        r"C:\Users\PrivateUser\Documents\study.pgn",
        r"C:Users\PrivateUser\Documents\study.pgn",
        r"C:Users/PrivateUser/Documents/study.pgn",
        r"C:My Documents\PrivateUser\study.pgn",
        r"\\server\private-share\PrivateUser\study.pgn",
        r"\\?\C:\Users\PrivateUser\Documents\study.pgn",
        r"\\?\UNC\server\private-share\PrivateUser\study.pgn",
        "file:///C:/Users/PrivateUser/Documents/study.pgn",
        "file:/home/PrivateUser/study.pgn",
        "/home/PrivateUser/study.pgn",
        "/opt/accessible-chess/private/study.pgn",
        "/srv/accessible-chess/private/study.pgn",
        "/etc/accessible-chess/private.conf",
        "/run/user/1000/private.sock",
        "/root/private/study.pgn",
        "/Applications/AccessibleChess/private/study.pgn",
    )

    SAFE_DOMAIN_TEXT = (
        "https://example.com/chess/help",
        "https://example.org/C:/opening-guide?next=/home/chapter",
        "/help",
        "/home",
        "/var",
        "/Applications",
        "incoming/books/study.md",
        r"incoming\books\study.md",
        "8/8/8/8/8/8/4P3/4K2k w - - 0 1",
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6",
        "Chapter C: White/Black to move after 1. e4 e5.",
        "A file: appendix label and file:appendix token are ordinary prose.",
        "Evaluation: +0.35; план: король і пішак — звичайний текст.",
    )

    @staticmethod
    def _book_projection(block: BookBlockView) -> BookWebViewProjection:
        return BookWebViewProjection(
            _StaticBookPresenter(block),
            lambda _action, _payload: None,
            language=UILanguage.EN,
        )

    @staticmethod
    def _training_projection(view: TrainingView) -> TrainingWebViewProjection:
        return TrainingWebViewProjection(
            _StaticTrainingPresenter(view),
            language=UILanguage.EN,
        )

    def assert_private_path_hidden(self, value: object, raw: str) -> None:
        text = str(value)
        self.assertIn("[local path hidden]", text)
        self.assertNotIn(raw, text)
        self.assertNotIn("PrivateUser", text)
        self.assertNotIn("private-share", text)

    def test_books_and_training_import_the_one_shared_sanitizer(self) -> None:
        self.assertIs(
            book_projection_module.redact_local_paths,
            presentation_privacy.redact_local_paths,
        )
        self.assertIs(
            training_projection_module.redact_local_paths,
            presentation_privacy.redact_local_paths,
        )

    def test_shared_helper_redacts_cross_platform_private_paths_and_keeps_next_line(self) -> None:
        marker = "[private path hidden]"
        for raw in self.PRIVATE_PATHS:
            with self.subTest(raw=raw):
                rendered = redact_local_paths(f"Source: {raw}\nNext semantic line", marker)
                self.assertIn(marker, rendered)
                self.assertIn("Next semantic line", rendered)
                self.assertNotIn("PrivateUser", rendered)
                self.assertNotIn("private-share", rendered)

    def test_book_and_training_safe_text_use_the_same_bilingual_redaction_contract(self) -> None:
        for raw in self.PRIVATE_PATHS:
            with self.subTest(raw=raw):
                self.assertIn(
                    "[local path hidden]",
                    book_safe_text(f"Book source {raw}", language=UILanguage.EN, limit=2000),
                )
                self.assertIn(
                    "[local path hidden]",
                    training_safe_text(f"Training source {raw}", language=UILanguage.EN, limit=2000),
                )
                self.assertIn(
                    "[локальний шлях приховано]",
                    book_safe_text(f"Джерело {raw}", language=UILanguage.UA, limit=2000),
                )
                self.assertIn(
                    "[локальний шлях приховано]",
                    training_safe_text(f"Джерело {raw}", language=UILanguage.UA, limit=2000),
                )

    def test_book_title_text_source_warning_heading_path_and_announcement_are_scrubbed(self) -> None:
        raw = r"C:\Users\PrivateUser\Books\private-study.pgn"
        block = BookBlockView(
            index=0,
            kind="paragraph",
            role="paragraph",
            title=f"Title {raw}",
            text=f"Text {raw}",
            heading_level=None,
            position_fen=None,
            heading_path=(f"Heading {raw}",),
            source_anchor=f"Source {raw}",
            warning=f"Warning {raw}",
        )
        projection = self._book_projection(block)
        snapshot = projection.snapshot()
        rendered_block = snapshot["block"]

        for field in ("title", "text", "source_anchor", "warning"):
            with self.subTest(field=field):
                self.assert_private_path_hidden(rendered_block[field], raw)
        self.assert_private_path_hidden(rendered_block["heading_path"][0], raw)

        event = projection._render(block, announcement=f"Announcement {raw}")
        self.assert_private_path_hidden(event.payload["announcement"], raw)

    def test_training_title_message_and_announcement_are_scrubbed(self) -> None:
        raw = r"C:\Users\PrivateUser\Training\private-exercise.json"
        view = TrainingView(
            status=ExerciseStatus.READY,
            title=f"Title {raw}",
            step_number=1,
            total_steps=1,
            attempts=0,
            mistakes=0,
            hints_used=0,
            completed=False,
            message=f"Message {raw}",
        )
        projection = self._training_projection(view)
        snapshot = projection.snapshot()
        self.assert_private_path_hidden(snapshot["title"], raw)
        self.assert_private_path_hidden(snapshot["message"], raw)

        event = projection._render(view, announcement=f"Announcement {raw}")
        self.assert_private_path_hidden(event.payload["announcement"], raw)

    def test_path_like_ordinary_book_prose_fen_san_urls_and_unicode_are_not_rewritten(self) -> None:
        prose = "\n".join(self.SAFE_DOMAIN_TEXT)
        block = BookBlockView(
            index=0,
            kind="paragraph",
            role="paragraph",
            title="Ordinary notation and source examples",
            text=prose,
            heading_level=None,
            position_fen=None,
            heading_path=("Privacy regression",),
            source_anchor="incoming/books/study.md",
            warning="",
        )
        rendered = self._book_projection(block).snapshot()["block"]
        self.assertEqual(prose, rendered["text"])
        self.assertEqual("incoming/books/study.md", rendered["source_anchor"])

        for value in self.SAFE_DOMAIN_TEXT:
            with self.subTest(value=value):
                self.assertEqual(value, redact_local_paths(value, "[hidden]"))
                self.assertEqual(
                    value,
                    book_safe_text(value, language=UILanguage.EN, limit=2000),
                )
                self.assertEqual(
                    value,
                    training_safe_text(value, language=UILanguage.EN, limit=2000),
                )

    def test_helper_rejects_invalid_boundary_arguments(self) -> None:
        with self.assertRaises(TypeError):
            redact_local_paths(123, "[hidden]")
        with self.assertRaises(ValueError):
            redact_local_paths("text", "")


if __name__ == "__main__":
    unittest.main()
