from __future__ import annotations

from pathlib import Path
import unittest

from acs.book_webview_projection import BookWebViewProjection
from acs.bookdocument import BookDocument, Diagram, Heading
from acs.bookreader import BookReader
from acs.full_product_actions import build_full_product_action_registry, validate_full_product_actions
from acs.full_product_presenters import BookReaderPresenter, LibraryPresenter, PgnTreePresenter
from acs.full_product_ui_shell import UILanguage
from acs.gametree import parse_games
from acs.keybindings import BindingContext
from acs.library_webview_projection import LibraryWebViewProjection
from acs.pgn_webview_projection import PgnWebViewProjection
from acs.search_service import GameSearchItem, GameSearchPage, GameSearchQuery


class TestReadyKeyboardContractTests(unittest.TestCase):
    def test_full_product_defaults_cover_pgn_library_and_books(self) -> None:
        validate_full_product_actions()
        registry = build_full_product_action_registry()
        expected = (
            (BindingContext.DOCUMENT, "Ctrl+Alt+Right", "pgn.next_item"),
            (BindingContext.DOCUMENT, "Ctrl+Alt+Left", "pgn.previous_item"),
            (BindingContext.DOCUMENT, "Ctrl+Alt+Up", "pgn.parent_variation"),
            (BindingContext.DOCUMENT, "Ctrl+Shift+Down", "pgn.board_enter_variation"),
            (BindingContext.DOCUMENT, "Ctrl+Shift+Up", "pgn.board_leave_variation"),
            (BindingContext.DATABASE, "Ctrl+F", "library.search"),
            (BindingContext.DATABASE, "Ctrl+Enter", "library.open_game"),
            (BindingContext.DATABASE, "Ctrl+I", "library.import"),
            (BindingContext.BOOK_READER, "Alt+Left", "book.previous_block"),
            (BindingContext.BOOK_READER, "Alt+Right", "book.next_block"),
            (BindingContext.BOOK_READER, "Alt+Shift+Left", "book.previous_heading"),
            (BindingContext.BOOK_READER, "Alt+Shift+Right", "book.next_heading"),
            (BindingContext.BOOK_READER, "Ctrl+Alt+P", "book.next_position"),
        )
        for context, chord, action_id in expected:
            with self.subTest(context=context, chord=chord):
                self.assertEqual(action_id, registry.resolve_binding(context, chord).action_id)


class TestReadyAnnouncementContractTests(unittest.TestCase):
    def test_pgn_selection_announces_variation_depth_and_label(self) -> None:
        games = tuple(
            parse_games(
                '[Event "Tree"]\n[Result "*"]\n\n'
                '1. e4 e5 (1... c5 2. Nf3 (2. Nc3)) 2. Nf3 *\n'
            )
        )
        presenter = PgnTreePresenter(games, language=UILanguage.UA)
        projection = PgnWebViewProjection(
            presenter,
            lambda *_: None,
            lambda: len(games),
            language=UILanguage.UA,
        )
        variation = next(item for item in presenter.items() if item.kind == "variation")
        event = projection.select(variation.node_id)
        spoken = event.payload["announcement"]
        self.assertIn("Варіант", spoken)
        self.assertIn("рівень", spoken)
        self.assertTrue(str(variation.label) in spoken)

    def test_book_navigation_announces_text_and_position_availability(self) -> None:
        document = BookDocument(
            title="Book",
            blocks=[
                Heading(text="Chapter", level=1),
                Diagram(
                    fen="8/8/8/8/8/8/4K3/7k w - - 0 1",
                    caption="Study position",
                    alt_text="Study position",
                ),
            ],
        )
        reader = BookReader(document)
        projection = BookWebViewProjection(
            BookReaderPresenter(reader, language=UILanguage.UA),
            lambda *_: None,
            language=UILanguage.UA,
        )
        event = projection.next_position()
        spoken = event.payload["announcement"]
        self.assertIn("Study position", spoken)
        self.assertIn("Позиція доступна", spoken)

    def test_library_keyboard_selection_announces_selected_row(self) -> None:
        class Search:
            def search(self, query):
                return GameSearchPage(
                    items=(
                        GameSearchItem(1, 1, "one.pgn", "PGN", 0, "full", "A", "B", "One", None, None, None, "*", None, None, None),
                        GameSearchItem(2, 1, "one.pgn", "PGN", 1, "full", "C", "D", "Two", None, None, None, "*", None, None, None),
                    ),
                    next_after_game_id=None,
                    has_more=False,
                )

        presenter = LibraryPresenter(Search(), language=UILanguage.UA)
        projection = LibraryWebViewProjection(
            presenter,
            lambda *_: None,
            language=UILanguage.UA,
        )
        projection.search(GameSearchQuery(limit=50))
        event = projection.move_selection(1)
        self.assertIn("Вибрано 2", event.payload["announcement"])
        self.assertIn("C", event.payload["announcement"])
        self.assertIn("D", event.payload["announcement"])


class TestReadyVisualAndSurfaceAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).parents[1]
        cls.index = (cls.root / "web" / "index.html").read_text(encoding="utf-8")
        cls.pgn = (cls.root / "web" / "full_product_pgn.js").read_text(encoding="utf-8")
        cls.library = (cls.root / "web" / "full_product_library.js").read_text(encoding="utf-8")
        cls.books = (cls.root / "web" / "full_product_books_training.js").read_text(encoding="utf-8")

    def test_pico_is_vendored_offline_with_accessibility_overrides(self) -> None:
        css = self.root / "web" / "vendor" / "pico-2.1.1.min.css"
        license_file = self.root / "web" / "vendor" / "PICO-CSS-LICENSE.md"
        self.assertTrue(css.is_file())
        self.assertTrue(license_file.is_file())
        self.assertIn('href="vendor/pico-2.1.1.min.css"', self.index)
        self.assertIn("@media(forced-colors:active)", self.index)
        self.assertIn("@media(prefers-reduced-motion:reduce)", self.index)
        self.assertIn("focus-visible", self.index)

    def test_visual_board_uses_unicode_pieces_but_keeps_aria_label_authority(self) -> None:
        self.assertIn("function pieceGlyph(label)", self.index)
        self.assertIn("♔", self.index)
        self.assertIn("♟", self.index)
        self.assertIn("node.setAttribute('aria-label',cell.label)", self.index)
        self.assertIn("piece.setAttribute('aria-hidden','true')", self.index)
        self.assertIn("coord.setAttribute('aria-hidden','true')", self.index)

    def test_surface_hotkeys_remain_root_scoped_and_preserve_native_copy(self) -> None:
        self.assertIn('root.addEventListener("keydown"', self.pgn)
        self.assertIn('root.addEventListener("keydown"', self.library)
        self.assertIn('root.addEventListener("keydown"', self.books)
        self.assertIn('toLowerCase() === "c"', self.pgn)
        self.assertIn('selection.toString()', self.pgn)
        self.assertIn('toLowerCase() === "c"', self.books)
        self.assertIn('selection.toString()', self.books)


if __name__ == "__main__":
    unittest.main()
