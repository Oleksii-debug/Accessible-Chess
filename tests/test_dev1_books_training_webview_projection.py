from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from acs.bookdocument import BookDocument, Diagram, Game, Heading, Paragraph, VariationTree
from acs.bookreader import BookReader
from acs.book_webview_projection import BookWebViewProjection
from acs.full_product_presenters import BookBlockView, BookReaderPresenter, TrainingPresenter
from acs.full_product_ui_shell import UILanguage
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.training_webview_projection import TrainingWebViewProjection


FEN = "8/8/8/8/8/8/4P3/4K2k w - - 0 1"


class BookProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = BookDocument(
            title="Accessible book",
            blocks=[
                Heading(text="Chapter 1", level=1, block_id="h1"),
                Paragraph(text="Read this paragraph.", source_anchor="chapter-1:p1"),
                Diagram(
                    fen=FEN,
                    caption="Critical position",
                    alt_text=None,
                    source_anchor=r"C:\\Users\\Oleksii\\private\\book-source.docx",
                ),
                Paragraph(text="After the board.", source_anchor="chapter-1:p2"),
                Game(
                    pgn='[Result "*"]\n\n1. e4 *',
                    title="Private game",
                    block_id="game-1",
                ),
            ],
        )
        self.calls = []

        def dispatch(action_id, payload):
            self.calls.append((action_id, dict(payload)))
            return {"fen": "SECRET", "path": r"C:\\private\\internal"}

        self.presenter = BookReaderPresenter(BookReader(self.document), language=UILanguage.EN)
        self.projection = BookWebViewProjection(self.presenter, dispatch, language=UILanguage.EN)

    def test_passive_snapshot_is_semantic_and_never_contains_raw_fen(self) -> None:
        first = self.projection.snapshot()
        self.assertEqual("heading", first["block"]["role"])
        self.assertEqual(1, first["block"]["heading_level"])
        self.assertFalse(first["block"]["has_position"])
        self.assertNotIn(FEN, repr(first))
        self.assertNotIn("position_fen", repr(first))

        diagram_event = self.projection.next_position()
        diagram = diagram_event.payload["snapshot"]
        self.assertEqual("img", diagram["block"]["role"])
        self.assertTrue(diagram["block"]["has_position"])
        self.assertIn("No separate diagram description", diagram["block"]["warning"])
        self.assertEqual("book-source.docx", diagram["block"]["source_anchor"])
        self.assertNotIn(FEN, repr(diagram))
        self.assertNotIn("Users", repr(diagram))

    def test_variation_tree_is_read_only_group_until_structured_tree_projection_exists(self) -> None:
        document = BookDocument(
            title="Variation semantics",
            blocks=[
                VariationTree(
                    root_fen=FEN,
                    pgn='[Result "*"]\n\n1. e4 (1. d4) *',
                    title="Candidate line",
                    block_id="variation-1",
                )
            ],
        )
        presenter = BookReaderPresenter(BookReader(document), language=UILanguage.EN)
        projection = BookWebViewProjection(
            presenter,
            lambda action_id, payload: None,
            language=UILanguage.EN,
        )

        snapshot = projection.snapshot()
        self.assertEqual("VariationTree", snapshot["block"]["kind"])
        self.assertEqual("group", snapshot["block"]["role"])
        self.assertTrue(snapshot["block"]["has_position"])
        self.assertNotEqual("tree", snapshot["block"]["role"])

    def test_snapshot_rejects_semantic_contract_drift_before_browser_publication(self) -> None:
        block = self.presenter.current()

        with self.assertRaisesRegex(ValueError, "kind/role"):
            self.projection._snapshot_from_block(replace(block, role="group"))
        with self.assertRaisesRegex(ValueError, "heading path"):
            self.projection._snapshot_from_block(
                replace(block, heading_path=("a", "b", "c", "d", "e", "f", "g"))
            )
        with self.assertRaisesRegex(ValueError, "position presence"):
            self.projection._snapshot_from_block(
                replace(block, kind="Position", role="group", position_fen=None)
            )

    def test_snapshot_rejects_book_block_subclass_before_attribute_hooks(self) -> None:
        class HostileBookBlock(BookBlockView):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if type(self).armed and name in {
                    "index",
                    "kind",
                    "role",
                    "title",
                    "text",
                    "heading_level",
                    "position_fen",
                    "heading_path",
                    "source_anchor",
                    "warning",
                    "list_items",
                    "list_ordered",
                    "list_start",
                }:
                    type(self).touched = True
                    raise AssertionError("BookBlockView attribute hook must not execute")
                return super().__getattribute__(name)

        block = self.presenter.current()
        hostile = HostileBookBlock(
            block.index,
            block.kind,
            block.role,
            block.title,
            block.text,
            block.heading_level,
            block.position_fen,
            block.heading_path,
            block.source_anchor,
            block.warning,
            block.list_items,
            block.list_ordered,
            block.list_start,
        )
        HostileBookBlock.armed = True

        with self.assertRaisesRegex(TypeError, "exact BookBlockView"):
            self.projection._snapshot_from_block(hostile)

        self.assertFalse(HostileBookBlock.touched)

    def test_snapshot_rejects_noncanonical_scalar_types_without_coercion(self) -> None:
        block = self.presenter.current()

        class RoleSpoof:
            def __str__(self) -> str:
                raise AssertionError("malformed role must never be coerced")

        with self.assertRaisesRegex(TypeError, "role must be text"):
            self.projection._snapshot_from_block(
                replace(block, role=RoleSpoof())  # type: ignore[arg-type]
            )

        for field_name in ("title", "text", "source_anchor", "warning"):
            with self.subTest(field=field_name):
                with self.assertRaisesRegex(TypeError, "must be text"):
                    self.projection._snapshot_from_block(
                        replace(block, **{field_name: None})  # type: ignore[arg-type]
                    )

        with self.assertRaisesRegex(TypeError, "position must be text"):
            self.projection._snapshot_from_block(
                replace(
                    block,
                    kind="Position",
                    role="group",
                    heading_level=None,
                    position_fen=object(),  # type: ignore[arg-type]
                )
            )

        with self.assertRaisesRegex(ValueError, "position must not be empty"):
            self.projection._snapshot_from_block(
                replace(
                    block,
                    kind="Position",
                    role="group",
                    heading_level=None,
                    position_fen="   ",
                )
            )

        for malformed in ("8/8/8\x00secret", "x" * 4097):
            with self.subTest(position=repr(malformed[:24])):
                with self.assertRaisesRegex(ValueError, "board-position token"):
                    self.projection._snapshot_from_block(
                        replace(
                            block,
                            kind="Position",
                            role="group",
                            heading_level=None,
                            position_fen=malformed,
                        )
                    )

    def test_snapshot_rejects_navigation_dict_subclass_before_container_hooks(self) -> None:
        class HostileNavigation(dict):
            armed = False
            touched = False

            @classmethod
            def _touch(cls, hook: str):
                cls.touched = True
                raise AssertionError(f"navigation {hook} hook must not execute")

            def __len__(self):
                if type(self).armed:
                    type(self)._touch("__len__")
                return super().__len__()

            def __iter__(self):
                if type(self).armed:
                    type(self)._touch("__iter__")
                return super().__iter__()

            def items(self):
                if type(self).armed:
                    type(self)._touch("items")
                return super().items()

        hostile = HostileNavigation(self.presenter.navigation_availability())
        HostileNavigation.armed = True

        with patch.object(self.presenter, "navigation_availability", return_value=hostile):
            with self.assertRaisesRegex(ValueError, "navigation availability schema"):
                self.projection.snapshot()

        self.assertFalse(HostileNavigation.touched)

    def test_snapshot_rejects_navigation_key_subclass_before_hash_or_equality_hooks(self) -> None:
        class HostileKey(str):
            armed = False
            touched = False

            @classmethod
            def _touch(cls, hook: str):
                cls.touched = True
                raise AssertionError(f"navigation key {hook} hook must not execute")

            def __hash__(self):
                if type(self).armed:
                    type(self)._touch("__hash__")
                return super().__hash__()

            def __eq__(self, other):
                if type(self).armed:
                    type(self)._touch("__eq__")
                return super().__eq__(other)

        canonical = self.presenter.navigation_availability()
        hostile_key = HostileKey("previous")
        hostile = {hostile_key: canonical["previous"]}
        hostile.update({key: value for key, value in canonical.items() if key != "previous"})
        HostileKey.armed = True

        with patch.object(self.presenter, "navigation_availability", return_value=hostile):
            with self.assertRaisesRegex(ValueError, "navigation availability schema"):
                self.projection.snapshot()

        self.assertFalse(HostileKey.touched)

    def test_snapshot_rejects_heading_and_navigation_contract_drift(self) -> None:
        paragraph = self.presenter.next_block()
        with self.assertRaisesRegex(ValueError, "non-heading"):
            self.projection._snapshot_from_block(replace(paragraph, heading_level=2))

        with patch.object(
            self.presenter,
            "navigation_availability",
            return_value={"previous": True},
        ):
            with self.assertRaisesRegex(ValueError, "navigation availability schema"):
                self.projection.snapshot()

        invalid_flags = {
            "previous": False,
            "next": True,
            "previous_heading": False,
            "next_heading": True,
            "previous_position": False,
            "next_position": True,
            "previous_game": False,
            "next_game": 1,
        }
        with patch.object(
            self.presenter,
            "navigation_availability",
            return_value=invalid_flags,
        ):
            with self.assertRaisesRegex(ValueError, "navigation availability flags"):
                self.projection.snapshot()

    def test_snapshot_rejects_semantics_that_sanitize_to_empty_webview_text(self) -> None:
        block = self.presenter.current()
        with self.assertRaisesRegex(ValueError, "empty visible part"):
            self.projection._snapshot_from_block(
                replace(block, heading_path=("\x00",))
            )

        with self.assertRaisesRegex(ValueError, "empty visible item"):
            self.projection._snapshot_from_block(
                replace(
                    block,
                    kind="List",
                    role="list",
                    heading_level=None,
                    list_items=("\x00",),
                    list_ordered=False,
                    list_start=None,
                )
            )

    def test_book_metadata_and_heading_path_have_raw_scan_ceiling(self) -> None:
        block = self.presenter.current()
        with (
            patch("acs.book_webview_projection._MAX_BOOK_BLOCK_VISIBLE_CHARS", 4),
            patch(
                "acs.book_webview_projection._safe_text",
                side_effect=AssertionError(
                    "Book sanitizer must not scan raw over-budget metadata"
                ),
            ) as safe_text,
        ):
            with self.assertRaisesRegex(ValueError, "title exceeds the raw text budget"):
                self.projection._snapshot_from_block(
                    replace(
                        block,
                        title="xxxxx",
                        text="",
                        source_anchor="",
                        warning="",
                        heading_path=(),
                    )
                )
            safe_text.assert_not_called()

            with self.assertRaisesRegex(ValueError, "heading path exceeds the raw text budget"):
                self.projection._snapshot_from_block(
                    replace(
                        block,
                        title="",
                        text="",
                        source_anchor="",
                        warning="",
                        heading_path=("xxxxx",),
                    )
                )
            safe_text.assert_not_called()

    def test_snapshot_rejects_raw_oversize_before_redaction_scan(self) -> None:
        paragraph = self.presenter.next_block()
        with (
            patch("acs.book_webview_projection._MAX_BOOK_BLOCK_VISIBLE_CHARS", 4),
            patch(
                "acs.book_webview_projection.redact_local_paths",
                side_effect=AssertionError("redaction must not scan raw oversize text"),
            ) as redact,
        ):
            with self.assertRaisesRegex(ValueError, "visible-text budget"):
                self.projection._snapshot_from_block(
                    replace(paragraph, text="xxxxx")
                )
        redact.assert_not_called()

    def test_list_whitespace_only_item_still_fails_after_deferred_sanitation(self) -> None:
        block = self.presenter.current()
        with self.assertRaisesRegex(ValueError, "empty visible item"):
            self.projection._snapshot_from_block(
                replace(
                    block,
                    kind="List",
                    role="list",
                    heading_level=None,
                    list_items=("   ",),
                    list_ordered=False,
                    list_start=None,
                )
            )

    def test_snapshot_rejects_oversized_list_before_element_scan(self) -> None:
        block = self.presenter.current()
        oversized = ("item",) * 65536 + (object(),)

        with self.assertRaisesRegex(ValueError, "item-count budget"):
            self.projection._snapshot_from_block(
                replace(
                    block,
                    kind="List",
                    role="list",
                    heading_level=None,
                    list_items=oversized,  # type: ignore[arg-type]
                    list_ordered=False,
                    list_start=None,
                )
            )

    def test_list_item_raw_bound_precedes_sanitizer_scan(self) -> None:
        block = self.presenter.current()
        with (
            patch("acs.book_webview_projection._MAX_BOOK_BLOCK_VISIBLE_CHARS", 4),
            patch(
                "acs.book_webview_projection._safe_visible_block_text",
                side_effect=AssertionError(
                    "Book sanitizer must not scan a raw over-budget list item"
                ),
            ) as safe_visible,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "list item exceeds the raw text budget",
            ):
                self.projection._snapshot_from_block(
                    replace(
                        block,
                        kind="List",
                        role="list",
                        heading_level=None,
                        title="",
                        text="",
                        source_anchor="",
                        warning="",
                        heading_path=(),
                        list_items=("xxxxx",),
                        list_ordered=False,
                        list_start=None,
                    )
                )
            safe_visible.assert_not_called()


    def test_list_item_rejects_string_subclass_before_string_operations(self) -> None:
        block = self.presenter.current()

        class HostileListItem(str):
            def __bool__(self) -> bool:
                raise AssertionError("list item subclass truthiness must not execute")

            def strip(self, *_args, **_kwargs):
                raise AssertionError("list item subclass strip must not execute")

            def replace(self, *_args, **_kwargs):
                raise AssertionError("list item subclass replace must not execute")

        with self.assertRaisesRegex(ValueError, "book list items are invalid"):
            self.projection._snapshot_from_block(
                replace(
                    block,
                    kind="List",
                    role="list",
                    heading_level=None,
                    list_items=(HostileListItem("item"),),  # type: ignore[arg-type]
                    list_ordered=False,
                    list_start=None,
                )
            )


    def test_snapshot_visible_text_budget_matches_webview_utf16_units(self) -> None:
        paragraph = self.presenter.next_block()
        with patch("acs.book_webview_projection._MAX_BOOK_BLOCK_VISIBLE_CHARS", 4):
            with self.assertRaisesRegex(ValueError, "visible-text budget"):
                self.projection._snapshot_from_block(
                    replace(paragraph, text="😀😀😀")
                )

    def test_snapshot_list_aggregate_budget_matches_webview_utf16_units(self) -> None:
        block = self.presenter.current()
        with patch("acs.book_webview_projection._MAX_BOOK_BLOCK_VISIBLE_CHARS", 4):
            with self.assertRaisesRegex(ValueError, "list exceeds the visible-text budget"):
                self.projection._snapshot_from_block(
                    replace(
                        block,
                        kind="List",
                        role="list",
                        heading_level=None,
                        list_items=("😀", "😀", "a"),
                        list_ordered=False,
                        list_start=None,
                    )
                )

    def test_snapshot_bounded_labels_never_exceed_webview_utf16_limit(self) -> None:
        block = self.presenter.current()
        snapshot = self.projection._snapshot_from_block(
            replace(block, title="😀" * 200)
        )
        title = snapshot["block"]["title"]
        self.assertEqual(180, len(title))
        self.assertEqual(360, len(title.encode("utf-16-le")) // 2)

    def test_snapshot_rejects_numbers_that_webview_cannot_represent_exactly(self) -> None:
        block = self.presenter.current()
        too_large = 1 << 53

        with self.assertRaisesRegex(ValueError, "block index"):
            self.projection._snapshot_from_block(replace(block, index=too_large))

        with self.assertRaisesRegex(ValueError, "list start"):
            self.projection._snapshot_from_block(
                replace(
                    block,
                    kind="List",
                    role="list",
                    heading_level=None,
                    list_items=("item",),
                    list_ordered=True,
                    list_start=too_large,
                )
            )

    def test_failed_navigation_render_restores_exact_semantic_cursor(self) -> None:
        document = BookDocument(
            title="Navigation transaction",
            blocks=[
                Heading(text="Chapter 1", level=1, block_id="tx-h1"),
                Paragraph(text="First paragraph.", block_id="tx-p1"),
                Diagram(fen=FEN, caption="First position", block_id="tx-d1"),
                Game(pgn='[Result "*"]\n\n1. e4 *', title="First game", block_id="tx-g1"),
                Heading(text="Chapter 2", level=1, block_id="tx-h2"),
                Diagram(fen=FEN, caption="Second position", block_id="tx-d2"),
                Game(pgn='[Result "*"]\n\n1. d4 *', title="Second game", block_id="tx-g2"),
            ],
        )
        cases = (
            ("next", 0),
            ("next_heading", 0),
            ("next_position", 0),
            ("next_game", 0),
            ("previous", 6),
            ("previous_heading", 6),
            ("previous_position", 6),
            ("previous_game", 6),
        )

        for method_name, start_index in cases:
            with self.subTest(method=method_name):
                reader = BookReader(document)
                reader.go_to(start_index)
                presenter = BookReaderPresenter(reader, language=UILanguage.EN)
                projection = BookWebViewProjection(
                    presenter,
                    lambda _action, _payload: None,
                    language=UILanguage.EN,
                )
                before = presenter.current()
                with patch.object(
                    projection,
                    "_render",
                    side_effect=ValueError("simulated WebView render failure"),
                ):
                    with self.assertRaisesRegex(ValueError, "simulated WebView"):
                        getattr(projection, method_name)()

                self.assertEqual(start_index, presenter.cursor_index)
                self.assertEqual(before, presenter.current())

    def test_open_position_keeps_fen_inside_python_dispatch_boundary(self) -> None:
        self.projection.next_position()
        event = self.projection.open_position()
        self.assertEqual("delegated", event.kind)
        self.assertEqual("book.open_position", self.calls[-1][0])
        self.assertEqual(FEN, self.calls[-1][1]["fen"])
        self.assertNotIn(FEN, repr(event))
        self.assertNotIn("SECRET", repr(event))
        self.assertNotIn("private", repr(event))

    def test_board_handoff_does_not_dispatch_when_presentation_preflight_fails(self) -> None:
        self.projection.next_position()
        with patch.object(
            self.projection,
            "_result_announcement",
            side_effect=ValueError("simulated announcement contract failure"),
        ):
            with self.assertRaises(ValueError):
                self.projection.open_position()
        self.assertEqual([], self.calls)

        self.projection.next_game()
        with patch.object(
            self.projection,
            "_result_announcement",
            side_effect=ValueError("simulated announcement contract failure"),
        ):
            with self.assertRaises(ValueError):
                self.projection.open_game()
        self.assertEqual([], self.calls)

    def test_board_handoff_rejects_semantic_snapshot_drift_before_dispatch(self) -> None:
        self.projection.next_position()
        position_block = self.presenter.current()
        with patch.object(
            self.presenter,
            "current",
            return_value=replace(position_block, role="paragraph"),
        ):
            with self.assertRaisesRegex(ValueError, "kind/role"):
                self.projection.open_position()
        self.assertEqual([], self.calls)

        self.projection.next_game()
        with patch.object(
            self.presenter,
            "navigation_availability",
            return_value={"previous": True},
        ):
            with self.assertRaisesRegex(ValueError, "navigation availability schema"):
                self.projection.open_game()
        self.assertEqual([], self.calls)

    def test_open_game_keeps_game_content_inside_python_dispatch_boundary(self) -> None:
        event = self.projection.next_game()
        self.assertEqual("Game", event.payload["snapshot"]["block"]["kind"])
        delegated = self.projection.open_game()
        self.assertEqual("delegated", delegated.kind)
        self.assertEqual(("book.open_game", {}), self.calls[-1])
        self.assertNotIn("1. e4", repr(delegated))
        self.assertNotIn("SECRET", repr(delegated))
        self.assertNotIn("private", repr(delegated).lower())

        self.projection.previous()
        returned = self.projection.return_from_board()
        self.assertEqual(4, returned.payload["snapshot"]["block"]["index"])

    def test_bookmark_and_board_return_restore_exact_reading_location(self) -> None:
        saved = self.projection.save_bookmark("chapter start")
        self.assertEqual(0, saved.payload["snapshot"]["block"]["index"])
        self.projection.next_position()
        restored = self.projection.restore_bookmark("chapter start")
        self.assertEqual(0, restored.payload["snapshot"]["block"]["index"])

        self.projection.next_position()
        self.projection.open_position()
        self.projection.next()
        returned = self.projection.return_from_board()
        self.assertEqual(2, returned.payload["snapshot"]["block"]["index"])

    def test_failed_bookmark_save_render_never_publishes_reader_mutation(self) -> None:
        before = self.presenter.current()
        before_name = self.projection.bookmark_name
        with patch.object(
            self.projection,
            "_render",
            side_effect=ValueError("simulated bookmark render failure"),
        ):
            with self.assertRaisesRegex(ValueError, "bookmark render"):
                self.projection.save_bookmark("not-published")

        self.assertEqual(before, self.presenter.current())
        self.assertEqual(before_name, self.projection.bookmark_name)
        with self.assertRaises(LookupError):
            self.presenter.restore_bookmark("not-published")

    def test_failed_bookmark_restore_render_restores_cursor_and_input_name(self) -> None:
        self.projection.save_bookmark("origin")
        self.projection.next_position()
        self.projection.save_bookmark("current")
        before = self.presenter.current()
        self.assertEqual("current", self.projection.bookmark_name)

        with patch.object(
            self.projection,
            "_render",
            side_effect=ValueError("simulated restore render failure"),
        ):
            with self.assertRaisesRegex(ValueError, "restore render"):
                self.projection.restore_bookmark("origin")

        self.assertEqual(before, self.presenter.current())
        self.assertEqual("current", self.projection.bookmark_name)

    def test_failed_board_return_render_restores_pre_return_cursor(self) -> None:
        self.projection.next_position()
        self.projection.open_position()
        self.projection.next()
        before = self.presenter.current()

        with patch.object(
            self.projection,
            "_render",
            side_effect=ValueError("simulated return render failure"),
        ):
            with self.assertRaisesRegex(ValueError, "return render"):
                self.projection.return_from_board()

        self.assertEqual(before, self.presenter.current())

    def test_bookmark_presenter_failure_restores_transient_input_name(self) -> None:
        before_name = self.projection.bookmark_name
        with patch.object(
            self.presenter,
            "bookmark",
            side_effect=RuntimeError("simulated reader bookmark failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "reader bookmark"):
                self.projection.save_bookmark("not-committed")
        self.assertEqual(before_name, self.projection.bookmark_name)

    def test_bookmark_name_is_bounded_before_reader_mutation(self) -> None:
        with self.assertRaises(ValueError):
            self.projection.save_bookmark("x" * 81)
        with self.assertRaises(ValueError):
            self.projection.save_bookmark("   ")
        self.assertEqual(0, self.presenter.current().index)

    def test_bookmark_raw_bound_and_exact_string_precede_normalization(self) -> None:
        class SplitBomb(str):
            def split(self, *args, **kwargs):
                raise AssertionError("bookmark subclass split must never execute")

        before = self.presenter.current()
        before_name = self.projection.bookmark_name

        with self.assertRaisesRegex(TypeError, "bookmark name must be text"):
            self.projection.save_bookmark(SplitBomb("safe"))
        with self.assertRaisesRegex(ValueError, "bookmark name is invalid"):
            self.projection.save_bookmark(" " * 80 + "x")

        self.assertEqual(before, self.presenter.current())
        self.assertEqual(before_name, self.projection.bookmark_name)

    def test_bookmark_utf16_bound_fails_before_reader_mutation(self) -> None:
        before = self.presenter.current()
        with self.assertRaisesRegex(ValueError, "bookmark name"):
            self.projection.save_bookmark("😀" * 41)
        self.assertEqual(before, self.presenter.current())

        accepted = self.projection.save_bookmark("😀" * 40)
        value = accepted.payload["snapshot"]["bookmark"]["value"]
        self.assertEqual(80, len(value.encode("utf-16-le")) // 2)

    def test_language_switch_changes_labels_without_changing_location(self) -> None:
        before = self.projection.snapshot()
        after = self.projection.set_language(UILanguage.UA).payload["snapshot"]
        self.assertEqual(before["block"]["index"], after["block"]["index"])
        self.assertEqual(before["block"]["dom_id"], after["block"]["dom_id"])
        self.assertNotEqual(before["heading"], after["heading"])

    def test_book_language_token_is_bounded_before_normalization(self) -> None:
        before = self.projection.language

        class HostileLanguage(str):
            stripped = False

            def strip(self, *_args, **_kwargs):
                type(self).stripped = True
                raise AssertionError("language subclass must not reach normalization")

        with self.assertRaisesRegex(TypeError, "language must be UILanguage"):
            self.projection.set_language(HostileLanguage("en"))
        self.assertFalse(HostileLanguage.stripped)
        self.assertIs(before, self.projection.language)

        with self.assertRaisesRegex(ValueError, "unsupported UI language"):
            self.projection.set_language("e" * 9)
        self.assertIs(before, self.projection.language)


    def test_book_render_rejects_hostile_announcement_string_before_subclass_hooks(self) -> None:
        class ReplaceBomb(str):
            touched = False

            def replace(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("hostile announcement replace must never execute")

            def strip(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("hostile announcement strip must never execute")

        block = self.presenter.current()
        with self.assertRaisesRegex(TypeError, "presentation text must be text"):
            self.projection._render(block, announcement=ReplaceBomb("saved"))
        self.assertFalse(ReplaceBomb.touched)

    def test_book_render_bounds_raw_announcement_before_sanitizer_scan(self) -> None:
        block = self.presenter.current()
        with (
            patch("acs.book_webview_projection._MAX_BOOK_BLOCK_VISIBLE_CHARS", 4),
            patch(
                "acs.book_webview_projection.redact_local_paths",
                side_effect=AssertionError("redaction must not scan raw over-budget announcement"),
            ) as redact,
        ):
            with self.assertRaisesRegex(ValueError, "raw text budget"):
                self.projection._render(block, announcement="xxxxx")
        redact.assert_not_called()


    def test_navigation_abort_restores_exact_semantic_cursor(self) -> None:
        class AbortSignal(BaseException):
            pass

        before = self.presenter.current()
        before_index = self.presenter.cursor_index
        with patch.object(
            self.projection,
            "_render",
            side_effect=AbortSignal("simulated browser abort"),
        ):
            with self.assertRaises(AbortSignal):
                self.projection.next()

        self.assertEqual(before_index, self.presenter.cursor_index)
        self.assertEqual(before, self.presenter.current())

    def test_book_language_abort_restores_projection_and_presenter_language(self) -> None:
        class AbortSignal(BaseException):
            pass

        before = self.projection.snapshot()
        with patch.object(
            self.projection,
            "snapshot",
            side_effect=AbortSignal("simulated locale render abort"),
        ):
            with self.assertRaises(AbortSignal):
                self.projection.set_language(UILanguage.UA)

        self.assertIs(UILanguage.EN, self.projection.language)
        after = self.projection.snapshot()
        self.assertEqual(before["heading"], after["heading"])
        self.assertEqual(before["block"]["index"], after["block"]["index"])

    def test_bookmark_save_abort_restores_transient_name_and_reader_binding(self) -> None:
        class AbortSignal(BaseException):
            pass

        before_name = self.projection.bookmark_name
        with patch.object(
            self.presenter,
            "bookmark",
            side_effect=AbortSignal("simulated bookmark publication abort"),
        ):
            with self.assertRaises(AbortSignal):
                self.projection.save_bookmark("abort-target")

        self.assertEqual(before_name, self.projection.bookmark_name)
        with self.assertRaises(LookupError):
            self.presenter.restore_bookmark("abort-target")

    def test_bookmark_restore_abort_restores_cursor_and_transient_name(self) -> None:
        class AbortSignal(BaseException):
            pass

        self.projection.save_bookmark("origin")
        self.projection.next_position()
        self.projection.save_bookmark("current")
        before = self.presenter.current()
        before_name = self.projection.bookmark_name

        with patch.object(
            self.projection,
            "_render",
            side_effect=AbortSignal("simulated restore browser abort"),
        ):
            with self.assertRaises(AbortSignal):
                self.projection.restore_bookmark("origin")

        self.assertEqual(before, self.presenter.current())
        self.assertEqual(before_name, self.projection.bookmark_name)


class TrainingProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.definition = ExerciseDefinition(
            exercise_id="ex-1",
            start_fen=FEN,
            steps=(
                ExerciseStep(
                    frozenset({"e4"}),
                    hint="Move the pawn two squares.",
                    explanation="Good.",
                ),
                ExerciseStep(frozenset({"Kh2"}), hint="Move the king."),
            ),
            title="Pawn practice",
            source_id="private-book-id",
            metadata={"path": r"C:\\private\\training.json"},
        )
        self.presenter = TrainingPresenter(ExerciseSession(self.definition), language=UILanguage.EN)
        self.projection = TrainingWebViewProjection(self.presenter, language=UILanguage.EN)

    def test_passive_snapshot_excludes_solution_fen_source_and_metadata(self) -> None:
        snapshot = self.projection.snapshot()
        text = repr(snapshot)
        self.assertEqual("ready", snapshot["status"])
        self.assertEqual(1, snapshot["progress"]["step"])
        self.assertEqual(2, snapshot["progress"]["total"])
        self.assertNotIn(FEN, text)
        self.assertNotIn("private-book-id", text)
        self.assertNotIn("training.json", text)
        self.assertNotIn("accepted_moves", text)
        self.assertNotIn("e4", text)

    def test_hint_and_reveal_do_not_advance_canonical_progress(self) -> None:
        before = self.presenter.snapshot()
        hinted = self.projection.hint()
        self.assertIn("Move the pawn two squares", hinted.payload["announcement"])
        self.assertEqual(before["step_index"], self.presenter.snapshot()["step_index"])

        revealed = self.projection.reveal()
        self.assertEqual(("e4",), revealed.payload["solution"])
        self.assertEqual(before["step_index"], self.presenter.snapshot()["step_index"])
        self.assertNotIn(FEN, repr(revealed))

    def test_wrong_answer_is_not_clear_signal_and_correct_answer_is(self) -> None:
        wrong = self.projection.submit("e3")
        self.assertFalse(wrong.payload["clear_answer"])
        self.assertEqual(1, wrong.payload["snapshot"]["progress"]["attempts"])
        self.assertEqual(1, wrong.payload["snapshot"]["progress"]["mistakes"])
        self.assertIn("Try again", wrong.payload["announcement"])

        correct = self.projection.submit("e4")
        self.assertTrue(correct.payload["clear_answer"])
        self.assertEqual(2, correct.payload["snapshot"]["progress"]["step"])
        self.assertEqual(2, correct.payload["snapshot"]["progress"]["attempts"])
        self.assertEqual(1, correct.payload["snapshot"]["progress"]["mistakes"])

        completed = self.projection.submit("Kh2")
        self.assertTrue(completed.payload["clear_answer"])
        self.assertTrue(completed.payload["snapshot"]["progress"]["completed"])
        self.assertTrue(completed.payload["snapshot"]["answer"]["disabled"])

    def test_answer_bound_and_type_fail_before_session_mutation(self) -> None:
        before = self.presenter.snapshot()
        with self.assertRaises(TypeError):
            self.projection.submit(123)
        with self.assertRaises(ValueError):
            self.projection.submit("x" * 129)
        with self.assertRaises(ValueError):
            self.projection.submit("  ")
        self.assertEqual(before, self.presenter.snapshot())

    def test_training_host_counters_match_browser_safe_integer_contract(self) -> None:
        too_large = replace(self.presenter.view(), attempts=1 << 53)
        with patch.object(self.presenter, "view", return_value=too_large):
            with self.assertRaisesRegex(ValueError, "training counters are invalid"):
                self.projection.snapshot()

        exact_max = (1 << 53) - 1
        accepted = replace(
            self.presenter.view(),
            attempts=exact_max,
            mistakes=exact_max,
            hints_used=exact_max,
        )
        with patch.object(self.presenter, "view", return_value=accepted):
            snapshot = self.projection.snapshot()
        self.assertEqual(exact_max, snapshot["progress"]["attempts"])
        self.assertEqual(exact_max, snapshot["progress"]["mistakes"])
        self.assertEqual(exact_max, snapshot["progress"]["hints_used"])

    def test_training_host_rejects_raw_oversize_before_nul_or_redaction_scan(self) -> None:
        view = replace(self.presenter.view(), title="x" * 361 + "\x00")
        with (
            patch.object(self.presenter, "view", return_value=view),
            patch(
                "acs.training_webview_projection.redact_local_paths",
                side_effect=AssertionError("redaction must not scan raw oversize Training text"),
            ) as redact,
        ):
            with self.assertRaisesRegex(ValueError, "training presentation text is too long"):
                self.projection.snapshot()
        redact.assert_not_called()

    def test_training_host_text_bounds_match_browser_utf16_units(self) -> None:
        oversized = replace(self.presenter.view(), title="😀" * 181)
        with patch.object(self.presenter, "view", return_value=oversized):
            with self.assertRaisesRegex(ValueError, "training presentation text is too long"):
                self.projection.snapshot()

        exact = replace(self.presenter.view(), title="😀" * 180)
        with patch.object(self.presenter, "view", return_value=exact):
            snapshot = self.projection.snapshot()
        self.assertEqual("😀" * 180, snapshot["title"])
        self.assertEqual(360, len(snapshot["title"].encode("utf-16-le")) // 2)

    def test_training_language_token_is_bounded_before_normalization(self) -> None:
        before = self.projection.language

        class HostileLanguage(str):
            stripped = False

            def strip(self, *_args, **_kwargs):
                type(self).stripped = True
                raise AssertionError("language subclass must not reach normalization")

        with self.assertRaisesRegex(TypeError, "language must be UILanguage"):
            self.projection.set_language(HostileLanguage("en"))
        self.assertFalse(HostileLanguage.stripped)
        self.assertIs(before, self.projection.language)

        with self.assertRaisesRegex(ValueError, "unsupported UI language"):
            self.projection.set_language("e" * 9)
        self.assertIs(before, self.projection.language)

    def test_training_host_rejects_string_subclasses_before_string_operations(self) -> None:
        class HostileText(str):
            def __contains__(self, _item) -> bool:
                raise AssertionError("string subclass must not reach NUL scan")

            def strip(self, *_args, **_kwargs):
                raise AssertionError("string subclass must not reach strip")

        view = replace(self.presenter.view(), title=HostileText("title"))
        with patch.object(self.presenter, "view", return_value=view):
            with self.assertRaisesRegex(TypeError, "training presentation text must be text"):
                self.projection.snapshot()

        before = self.presenter.snapshot()
        with self.assertRaisesRegex(TypeError, "training answer must be text"):
            self.projection.submit(HostileText("e4"))
        self.assertEqual(before, self.presenter.snapshot())

    def test_training_solution_and_answer_bounds_precede_nul_scan_and_use_utf16(self) -> None:
        with patch.object(
            self.presenter,
            "reveal_solution",
            return_value=("x" * 129 + "\x00",),
        ):
            with self.assertRaisesRegex(ValueError, "training solution move is too long"):
                self.projection.reveal()

        with patch.object(
            self.presenter,
            "reveal_solution",
            return_value=("😀" * 65,),
        ):
            with self.assertRaisesRegex(ValueError, "training solution move is too long"):
                self.projection.reveal()

        before = self.presenter.snapshot()
        with self.assertRaisesRegex(ValueError, "training answer is too long"):
            self.projection.submit("x" * 129 + "\x00")
        with self.assertRaisesRegex(ValueError, "training answer is too long"):
            self.projection.submit("😀" * 65)
        self.assertEqual(before, self.presenter.snapshot())

    def test_real_overbudget_explanation_render_rolls_back_canonical_move(self) -> None:
        definition = ExerciseDefinition(
            exercise_id="overbudget-explanation",
            start_fen=FEN,
            steps=(
                ExerciseStep(
                    frozenset({"e4"}),
                    explanation="x" * 1201,
                ),
            ),
            title="Rollback explanation",
        )
        presenter = TrainingPresenter(ExerciseSession(definition), language=UILanguage.EN)
        projection = TrainingWebViewProjection(presenter, language=UILanguage.EN)
        before = presenter.snapshot()
        retained = presenter.session

        with self.assertRaisesRegex(ValueError, "training presentation text is too long"):
            projection.submit("e4")

        self.assertIs(retained, presenter.session)
        self.assertEqual(before, presenter.snapshot())
        self.assertEqual("", presenter.message)
        self.assertEqual(0, presenter.session.step_index)
        self.assertEqual(0, presenter.session.attempts)
        self.assertEqual((), presenter.session.accepted_path)


    def test_real_overbudget_hint_render_rolls_back_hint_counter(self) -> None:
        definition = ExerciseDefinition(
            exercise_id="overbudget-hint",
            start_fen=FEN,
            steps=(
                ExerciseStep(
                    frozenset({"e4"}),
                    hint="x" * 1201,
                ),
            ),
            title="Rollback hint",
        )
        presenter = TrainingPresenter(ExerciseSession(definition), language=UILanguage.EN)
        projection = TrainingWebViewProjection(presenter, language=UILanguage.EN)
        before = presenter.snapshot()
        retained = presenter.session

        with self.assertRaisesRegex(ValueError, "training presentation text is too long"):
            projection.hint()

        self.assertIs(retained, presenter.session)
        self.assertEqual(before, presenter.snapshot())
        self.assertEqual("", presenter.message)
        self.assertEqual(0, presenter.session.hints_used)


    def test_reset_requires_exact_true_and_resets_canonical_session(self) -> None:
        self.projection.submit("e3")
        before = self.presenter.snapshot()
        with self.assertRaises(ValueError):
            self.projection.reset(confirmed=False)
        with self.assertRaises(ValueError):
            self.projection.reset(confirmed=1)
        self.assertEqual(before, self.presenter.snapshot())
        reset = self.projection.reset(confirmed=True)
        self.assertEqual(0, reset.payload["snapshot"]["progress"]["attempts"])
        self.assertEqual("ready", reset.payload["snapshot"]["status"])
        self.assertTrue(reset.payload["clear_answer"])

    def test_language_switch_preserves_progress_identity(self) -> None:
        self.projection.submit("e4")
        en = self.projection.snapshot()
        ua = self.projection.set_language(UILanguage.UA).payload["snapshot"]
        for key in ("step", "total", "attempts", "mistakes", "hints_used", "completed"):
            self.assertEqual(en["progress"][key], ua["progress"][key])
        self.assertEqual(en["title"], ua["title"])
        self.assertNotEqual(en["progress"]["step_label"], ua["progress"]["step_label"])
        self.assertNotEqual(en["heading"], ua["heading"])


    def test_training_submit_abort_restores_exact_session_state(self) -> None:
        class AbortSignal(BaseException):
            pass

        before = self.presenter.snapshot()
        retained = self.presenter.session
        with patch.object(
            self.projection,
            "_render",
            side_effect=AbortSignal("simulated training browser abort"),
        ):
            with self.assertRaises(AbortSignal):
                self.projection.submit("e4")

        self.assertIs(retained, self.presenter.session)
        self.assertEqual(before, self.presenter.snapshot())
        self.assertEqual("", self.presenter.message)

    def test_training_language_abort_restores_locale_without_progress_drift(self) -> None:
        class AbortSignal(BaseException):
            pass

        self.projection.submit("e3")
        before_state = self.presenter.snapshot()
        before_view = self.projection.snapshot()
        with patch.object(
            self.projection,
            "snapshot",
            side_effect=AbortSignal("simulated training locale abort"),
        ):
            with self.assertRaises(AbortSignal):
                self.projection.set_language(UILanguage.UA)

        self.assertIs(UILanguage.EN, self.projection.language)
        self.assertEqual(before_state, self.presenter.snapshot())
        after_view = self.projection.snapshot()
        self.assertEqual(before_view["heading"], after_view["heading"])

    def test_training_continuation_probe_abort_degrades_to_unavailable(self) -> None:
        class AbortSignal(BaseException):
            pass

        def abort_continuation() -> bool:
            raise AbortSignal("simulated continuation provider abort")

        projection = TrainingWebViewProjection(
            TrainingPresenter(ExerciseSession(self.definition), language=UILanguage.EN),
            language=UILanguage.EN,
            can_continue=abort_continuation,
        )
        projection.submit("e4")
        completed = projection.submit("Kh2")
        self.assertTrue(completed.payload["snapshot"]["progress"]["completed"])
        continuation = next(
            action
            for action in completed.payload["snapshot"]["actions"]
            if action["command"] == "training.continue"
        )
        self.assertFalse(continuation["enabled"])


if __name__ == "__main__":
    unittest.main()
