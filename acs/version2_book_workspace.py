"""Accessible Books composition over the accepted reader and Board workflow.

The V2 projection uses the workflow's return stack for both open and return.
It never creates the legacy presenter's independent Board return point.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
import re
from typing import Any

from .book_board_workflow import (
    BookBoardMode,
    BookBoardWorkflow,
    BookBoardWorkflowCode,
    BookBoardWorkflowError,
)
from .book_webview_bridge import BookWebViewBridge
from .book_webview_projection import (
    BookWebViewEvent,
    BookWebViewProjection,
    _MAX_BOOK_BLOCK_VISIBLE_CHARS,
    _safe_text,
    _utf16_units,
)
from .bookdocument import Diagram, Exercise, Game, Position, VariationTree
from .bookreader import BookReader
from .full_product_actions import ActionDispatchResult
from .full_product_presenters import (
    BookReaderPresenter,
    PgnGameView,
    PgnTreeItem,
    PgnTreePresenter,
)
from .gametree import Comment, MoveNode, PgnGame, VariationLine
from .full_product_ui_shell import UILanguage
from .version2_windows_book_board_adapter import BookBoardUiEvent, BookBoardUiEventKind


_MAX_BOOK_SEMANTIC_ITEMS = 10_000
_MAX_BOOK_SEMANTIC_DEPTH = 256
_MAX_BOOK_SEMANTIC_TEXT_ENTRIES = 50_000
_MAX_BOOK_SEMANTIC_SECTION_LABEL_UNITS = 360
_MAX_BOOK_SEMANTIC_FIELD_LABEL_UNITS = 120
_MAX_BOOK_SEMANTIC_PLAYERS_UNITS = 720
_MAX_BOOK_SEMANTIC_ITEM_LABEL_UNITS = 1_200
_MAX_BOOK_SEMANTIC_RESULT_UNITS = 16
_MAX_BOOK_SEMANTIC_NODE_ID_CHARS = 4_096
_BOOK_SEMANTIC_RESULTS = frozenset({"1-0", "0-1", "1/2-1/2", "*"})
_BOOK_SEMANTIC_METADATA = (
    ("event", "Event"), ("site", "Site"), ("date", "Date"),
    ("round", "Round"), ("eco", "ECO"), ("opening", "Opening"),
)

_SEMANTIC_LABELS = {
    UILanguage.UA: {
        "moves": "Ходи та варіанти",
        "players": "Гравці",
        "result": "Результат",
        "variation_depth": "Рівень варіанта",
        "unknown": "невідомо",
        "event": "Подія", "site": "Місце", "date": "Дата",
        "round": "Тур", "eco": "ECO", "opening": "Дебют",
        "reading_unavailable": "Ходи цієї партії неможливо безпечно показати; шахівниця залишається доступною.",
        "content_unavailable": "Шаховий вміст цієї партії недоступний або невалідний; відкриття на шахівниці вимкнено.",
        "recovery_warnings": "Шаховий текст відновлено з попередженнями: {count}. Перегляньте попередження перед використанням.",
    },
    UILanguage.EN: {
        "moves": "Moves and variations",
        "players": "Players",
        "result": "Result",
        "variation_depth": "Variation depth",
        "unknown": "unknown",
        "event": "Event", "site": "Site", "date": "Date",
        "round": "Round", "eco": "ECO", "opening": "Opening",
        "reading_unavailable": "This game's moves cannot be displayed safely; the board remains available.",
        "content_unavailable": "This game's chess content is unavailable or invalid; opening it on the board is disabled.",
        "recovery_warnings": "Chess text was recovered with warnings: {count}. Review the warnings before using it.",
    },
}


class _BookSemanticProjectionError(ValueError):
    pass


class Version2BookWebViewProjection(BookWebViewProjection):
    def __init__(
        self,
        reader: BookReader,
        workflow: BookBoardWorkflow,
        dispatch: Callable[[str, Mapping[str, object]], Any],
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if type(reader) is not BookReader or type(workflow) is not BookBoardWorkflow:
            raise TypeError("V2 Books requires the canonical reader and workflow")
        # Exact roots are not enough if they belong to different Books. The
        # projection reads visible block/metadata state from reader while semantic
        # GameTree and board actions resolve through the workflow reader. Mixing
        # those authorities could publish chess content from one Book under the
        # visible location/metadata of another.
        if workflow._reader is not reader:
            raise ValueError("V2 Books reader and workflow must share one authority")
        self._reader = reader
        self._workflow = workflow
        # BookWebViewProjection deliberately accepts only the exact canonical
        # presenter type so subclasses cannot override publication behavior. V2
        # adds its GameTree projection here and needs no presenter subclass.
        super().__init__(BookReaderPresenter(reader, language=language), dispatch, language=language)

    def _semantic_tree_snapshot(self, index: int) -> dict[str, object]:
        mode, game, workflow_warnings = self._workflow.semantic_game_snapshot(index)
        if (
            type(workflow_warnings) is not tuple
            or len(workflow_warnings) > _MAX_BOOK_SEMANTIC_TEXT_ENTRIES
            or any(type(warning) is not str for warning in workflow_warnings)
        ):
            raise _BookSemanticProjectionError("semantic workflow warnings are invalid")
        if (
            type(mode) is not BookBoardMode
            or mode not in {BookBoardMode.GAME, BookBoardMode.VARIATION}
        ):
            raise _BookSemanticProjectionError("semantic GameTree mode is invalid")
        if type(game) is not PgnGame:
            raise _BookSemanticProjectionError("semantic GameTree game is invalid")
        if type(game.line) is not VariationLine:
            raise _BookSemanticProjectionError("semantic GameTree root line is invalid")
        if (
            type(game.tags) is not dict
            or len(game.tags) > _MAX_BOOK_SEMANTIC_TEXT_ENTRIES
            or type(game.warnings) is not list
            or len(game.warnings) > _MAX_BOOK_SEMANTIC_TEXT_ENTRIES
        ):
            raise _BookSemanticProjectionError("semantic GameTree metadata is invalid")
        if len(workflow_warnings) != len(game.warnings):
            raise _BookSemanticProjectionError("semantic workflow warnings are inconsistent")
        # An exact dict can still contain hostile key/value subclasses. Validate
        # the detached tag table by iteration before any named lookup can invoke
        # user-defined hashing/equality behavior through a malformed DTO.
        for tag_name, tag_value in game.tags.items():
            if type(tag_name) is not str or type(tag_value) is not str:
                raise _BookSemanticProjectionError("semantic GameTree tag is invalid")

        # PgnTreePresenter normalizes comments, joins NAGs and constructs labels.
        # Bound every raw scalar and collection it will scan before constructing
        # the presenter so a malformed trusted-side DTO cannot move the resource
        # boundary behind strip/join/f-string work.
        raw_text_entries = 0
        raw_text_units = 0

        def claim_raw_text(
            value: object,
            *,
            max_units: int = _MAX_BOOK_BLOCK_VISIBLE_CHARS,
        ) -> int:
            nonlocal raw_text_entries, raw_text_units
            if type(max_units) is not int or not 0 <= max_units <= _MAX_BOOK_BLOCK_VISIBLE_CHARS:
                raise _BookSemanticProjectionError("semantic raw scalar limit is invalid")
            # Python len(str) counts Unicode code points, while the WebView
            # contract is expressed in UTF-16 units. A supplementary scalar
            # therefore costs two canonical units. Keep len() only as the O(1)
            # impossible-to-fit guard, then charge exact UTF-16 units before
            # presenter strip/join/f-string work can scan the value.
            if type(value) is not str or len(value) > max_units:
                raise _BookSemanticProjectionError("semantic raw text is invalid")
            units = _utf16_units(value)
            if units > max_units:
                raise _BookSemanticProjectionError("semantic raw text is invalid")
            raw_text_entries += 1
            if raw_text_entries > _MAX_BOOK_SEMANTIC_TEXT_ENTRIES:
                raise _BookSemanticProjectionError("semantic raw text-entry limit exceeded")
            raw_text_units += units
            if raw_text_units > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
                raise _BookSemanticProjectionError("semantic raw text budget exceeded")
            return units

        def claim_comment_list(values: object) -> None:
            if type(values) is not list or len(values) > _MAX_BOOK_SEMANTIC_TEXT_ENTRIES:
                raise _BookSemanticProjectionError("semantic raw comment collection is invalid")
            for comment in values:
                if type(comment) is not Comment:
                    raise _BookSemanticProjectionError("semantic raw comment is invalid")
                claim_raw_text(comment.text)

        # Only known chess metadata enters reading DTOs. Bound source scalars
        # before presenter construction; paths are redacted by the same safe()
        # authority as move comments when the public detail rows are rendered.
        for _kind, tag in _BOOK_SEMANTIC_METADATA:
            claim_raw_text(game.tags.get(tag, ""), max_units=1_200)

        white_raw = game.tags.get("White", "")
        black_raw = game.tags.get("Black", "")
        white_units = claim_raw_text(
            white_raw,
            max_units=_MAX_BOOK_SEMANTIC_PLAYERS_UNITS,
        )
        black_units = claim_raw_text(
            black_raw,
            max_units=_MAX_BOOK_SEMANTIC_PLAYERS_UNITS,
        )
        if white_units + 3 + black_units > _MAX_BOOK_SEMANTIC_PLAYERS_UNITS:
            raise _BookSemanticProjectionError("semantic raw players text is too long")

        root_result = game.line.result
        if root_result is not None and type(root_result) is not str:
            raise _BookSemanticProjectionError("semantic root result is invalid")
        effective_result = root_result or game.tags.get("Result", "*")
        claim_raw_text(
            effective_result,
            max_units=_MAX_BOOK_SEMANTIC_RESULT_UNITS,
        )
        if effective_result not in _BOOK_SEMANTIC_RESULTS:
            raise _BookSemanticProjectionError("semantic game result is invalid")

        stack: list[tuple[object, int]] = [(game.line, 0)]
        count = 0
        seen_lines: set[int] = set()
        seen_moves: set[int] = set()
        while stack:
            line, move_depth = stack.pop()
            if type(line) is not VariationLine:
                raise _BookSemanticProjectionError("semantic GameTree line is invalid")
            line_identity = id(line)
            if line_identity in seen_lines:
                raise _BookSemanticProjectionError("semantic GameTree line is reused")
            seen_lines.add(line_identity)
            if type(line.moves) is not list:
                raise _BookSemanticProjectionError("semantic GameTree moves are invalid")
            if line.moves and move_depth > _MAX_BOOK_SEMANTIC_DEPTH:
                raise _BookSemanticProjectionError("semantic GameTree depth limit exceeded")
            claim_comment_list(line.leading_comments)
            claim_comment_list(line.trailing_comments)
            if line.result is not None:
                claim_raw_text(
                    line.result,
                    max_units=_MAX_BOOK_SEMANTIC_RESULT_UNITS,
                )
                if line.result not in _BOOK_SEMANTIC_RESULTS:
                    raise _BookSemanticProjectionError("semantic line result is invalid")

            for move in line.moves:
                if type(move) is not MoveNode:
                    raise _BookSemanticProjectionError("semantic GameTree move is invalid")
                move_identity = id(move)
                if move_identity in seen_moves:
                    raise _BookSemanticProjectionError("semantic GameTree move is reused")
                seen_moves.add(move_identity)
                count += 1
                if count > _MAX_BOOK_SEMANTIC_ITEMS:
                    raise _BookSemanticProjectionError("semantic GameTree item limit exceeded")

                label_units = claim_raw_text(
                    move.san,
                    max_units=_MAX_BOOK_SEMANTIC_ITEM_LABEL_UNITS,
                )
                if move.move_number is not None:
                    move_number_units = claim_raw_text(
                        move.move_number,
                        max_units=_MAX_BOOK_SEMANTIC_ITEM_LABEL_UNITS,
                    )
                    if move.move_number:
                        label_units += move_number_units + 1

                if type(move.nags) is not list or len(move.nags) > _MAX_BOOK_SEMANTIC_TEXT_ENTRIES:
                    raise _BookSemanticProjectionError("semantic move NAGs are invalid")
                # PgnTreePresenter uses " ".join(move.nags): every adjacent
                # pair contributes one separator even when one or both NAG
                # strings are empty. Charge those separators from O(1) list
                # metadata before scanning the elements.
                annotation_units = max(0, len(move.nags) - 1)
                if annotation_units > _MAX_BOOK_SEMANTIC_ITEM_LABEL_UNITS:
                    raise _BookSemanticProjectionError("semantic move annotation is too long")
                for nag in move.nags:
                    annotation_units += claim_raw_text(
                        nag,
                        max_units=_MAX_BOOK_SEMANTIC_ITEM_LABEL_UNITS,
                    )
                    if annotation_units > _MAX_BOOK_SEMANTIC_ITEM_LABEL_UNITS:
                        raise _BookSemanticProjectionError("semantic move annotation is too long")
                if annotation_units:
                    label_units += annotation_units + 1
                if label_units > _MAX_BOOK_SEMANTIC_ITEM_LABEL_UNITS:
                    raise _BookSemanticProjectionError("semantic move label is too long")

                claim_comment_list(move.comments_before)
                claim_comment_list(move.comments_after)
                if type(move.variations) is not list:
                    raise _BookSemanticProjectionError("semantic move variations are invalid")
                for variation in move.variations:
                    if type(variation) is not VariationLine:
                        raise _BookSemanticProjectionError("semantic variation is invalid")
                    variation_depth = move_depth + 1
                    if variation_depth > _MAX_BOOK_SEMANTIC_DEPTH:
                        raise _BookSemanticProjectionError("semantic GameTree depth limit exceeded")
                    count += 1
                    if count > _MAX_BOOK_SEMANTIC_ITEMS:
                        raise _BookSemanticProjectionError("semantic GameTree item limit exceeded")
                    stack.append((variation, move_depth + 2))

        try:
            view = PgnTreePresenter((game,), language=self.language).view()
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise _BookSemanticProjectionError(
                "semantic GameTree presenter data is invalid"
            ) from exc
        if type(view) is not PgnGameView:
            raise _BookSemanticProjectionError("semantic GameTree view is invalid")
        if (
            type(view.game_index) is not int
            or view.game_index != 0
            or type(view.items) is not tuple
        ):
            raise _BookSemanticProjectionError("semantic GameTree view is unavailable")
        if len(view.items) > _MAX_BOOK_SEMANTIC_ITEMS:
            raise _BookSemanticProjectionError("semantic GameTree item limit exceeded")

        visible_total = 0
        visible_entries = 0

        def clean(
            value: object,
            *,
            allow_empty: bool = True,
            max_units: int = _MAX_BOOK_BLOCK_VISIBLE_CHARS,
        ) -> tuple[str, int]:
            if type(max_units) is not int or not 0 <= max_units <= _MAX_BOOK_BLOCK_VISIBLE_CHARS:
                raise _BookSemanticProjectionError("semantic GameTree scalar limit is invalid")
            # Semantic presenter fields are already canonical text.  Reject an
            # oversized/malformed scalar from O(1) metadata before replace(),
            # strip() or path-redaction can scan attacker-controlled text.
            if type(value) is not str or len(value) > max_units:
                raise _BookSemanticProjectionError("semantic GameTree text is invalid")
            try:
                # Keep one complete supplementary Unicode scalar beyond the
                # browser limit.  +1 can truncate a two-unit scalar exactly back
                # to max_units and turn an over-limit value into an accepted one.
                text = _safe_text(
                    value,
                    language=self.language,
                    limit=max_units + 2,
                )
            except (TypeError, ValueError) as exc:
                raise _BookSemanticProjectionError("semantic GameTree text is invalid") from exc
            if not allow_empty and not text:
                raise _BookSemanticProjectionError("semantic GameTree text is empty")
            units = _utf16_units(text)
            if units > max_units:
                raise _BookSemanticProjectionError("semantic GameTree scalar text limit exceeded")
            return text, units

        def account_visible_units(units: int) -> None:
            nonlocal visible_total
            if type(units) is not int or units < 0:
                raise _BookSemanticProjectionError("semantic GameTree visible text accounting is invalid")
            visible_total += units
            if visible_total > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
                raise _BookSemanticProjectionError("semantic GameTree text budget exceeded")

        def safe(
            value: object,
            *,
            allow_empty: bool = True,
            max_units: int = _MAX_BOOK_BLOCK_VISIBLE_CHARS,
            count_visible: bool = True,
        ) -> str:
            nonlocal visible_entries
            text, units = clean(
                value,
                allow_empty=allow_empty,
                max_units=max_units,
            )
            visible_entries += 1
            if visible_entries > _MAX_BOOK_SEMANTIC_TEXT_ENTRIES:
                raise _BookSemanticProjectionError("semantic GameTree text-entry limit exceeded")
            if count_visible:
                account_visible_units(units)
            return text

        def preflight_view_comments(values: object) -> int:
            if type(values) is not tuple or len(values) > _MAX_BOOK_SEMANTIC_TEXT_ENTRIES:
                raise _BookSemanticProjectionError("semantic comment collection is invalid")
            raw_units = 0
            for value in values:
                if type(value) is not str or len(value) > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
                    raise _BookSemanticProjectionError("semantic comment text is invalid")
                units = _utf16_units(value)
                if units > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
                    raise _BookSemanticProjectionError("semantic comment text is invalid")
                raw_units += units
                if raw_units > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
                    raise _BookSemanticProjectionError("semantic comment text budget exceeded")
            return raw_units

        def safe_many(values: object) -> tuple[str, ...]:
            nonlocal visible_entries
            preflight_view_comments(values)
            rendered: list[str] = []
            for value in values:
                text, units = clean(value)
                if not text:
                    continue
                visible_entries += 1
                if visible_entries > _MAX_BOOK_SEMANTIC_TEXT_ENTRIES:
                    raise _BookSemanticProjectionError(
                        "semantic GameTree text-entry limit exceeded"
                    )
                account_visible_units(units)
                rendered.append(text)
            return tuple(rendered)

        labels = _SEMANTIC_LABELS[self.language]
        white, _ = clean(
            game.tags.get("White", ""),
            max_units=_MAX_BOOK_SEMANTIC_PLAYERS_UNITS,
        )
        black, _ = clean(
            game.tags.get("Black", ""),
            max_units=_MAX_BOOK_SEMANTIC_PLAYERS_UNITS,
        )
        white = white or labels["unknown"]
        black = black or labels["unknown"]
        result = effective_result

        semantic_label = safe(
            labels["moves"],
            allow_empty=False,
            max_units=_MAX_BOOK_SEMANTIC_SECTION_LABEL_UNITS,
        )
        players_label = safe(
            labels["players"],
            allow_empty=False,
            max_units=_MAX_BOOK_SEMANTIC_FIELD_LABEL_UNITS,
        )
        players = safe(
            f"{white} — {black}",
            allow_empty=False,
            max_units=_MAX_BOOK_SEMANTIC_PLAYERS_UNITS,
        )
        # The browser renders the players label/value as one paragraph with
        # ": " between the already-counted serialized fields.
        account_visible_units(2)
        details = []
        for kind, tag in _BOOK_SEMANTIC_METADATA:
            value = game.tags.get(tag, "")
            if not value.strip():
                continue
            label = safe(labels[kind], allow_empty=False,
                         max_units=_MAX_BOOK_SEMANTIC_FIELD_LABEL_UNITS)
            public_value = safe(value, allow_empty=False, max_units=1_200)
            account_visible_units(2)
            details.append({"kind": kind, "label": label, "value": public_value})
        result_label = safe(
            labels["result"],
            allow_empty=False,
            max_units=_MAX_BOOK_SEMANTIC_FIELD_LABEL_UNITS,
            count_visible=False,
        )
        variation_depth_label = safe(
            labels["variation_depth"],
            allow_empty=False,
            max_units=_MAX_BOOK_SEMANTIC_FIELD_LABEL_UNITS,
            count_visible=False,
        )
        result_text = safe(
            result,
            allow_empty=False,
            max_units=_MAX_BOOK_SEMANTIC_RESULT_UNITS,
        )
        # The result label is serialized once but rendered with the canonical
        # game result. Count that rendered copy and its separator exactly.
        account_visible_units(_utf16_units(result_label) + 2)
        intro_comments = safe_many(
            tuple(comment.text for comment in game.line.leading_comments)
        )
        outro_comments = safe_many(
            tuple(comment.text for comment in game.line.trailing_comments)
        )

        rendered_items: list[dict[str, object]] = []
        seen: dict[str, int] = {}
        active_ancestor_indices: list[int] = []
        previous_depth = 0
        for position, item in enumerate(view.items):
            if type(item) is not PgnTreeItem:
                raise _BookSemanticProjectionError("semantic item DTO is invalid")
            if (
                type(item.kind) is not str
                or len(item.kind) > 16
                or item.kind not in {"move", "variation"}
            ):
                raise _BookSemanticProjectionError("semantic item kind is invalid")
            if type(item.depth) is not int or not 0 <= item.depth <= _MAX_BOOK_SEMANTIC_DEPTH:
                raise _BookSemanticProjectionError("semantic item depth is invalid")
            if (
                (item.kind == "move" and item.depth % 2 != 0)
                or (item.kind == "variation" and item.depth % 2 != 1)
            ):
                raise _BookSemanticProjectionError("semantic item kind/depth is inconsistent")
            if position == 0 and item.depth != 0:
                raise _BookSemanticProjectionError("semantic root depth is invalid")
            if position > 0 and item.depth > previous_depth + 1:
                raise _BookSemanticProjectionError("semantic item depth jumps unexpectedly")
            if (
                type(item.node_id) is not str
                or not item.node_id
                or len(item.node_id) > _MAX_BOOK_SEMANTIC_NODE_ID_CHARS
            ):
                raise _BookSemanticProjectionError("semantic item identity is invalid")
            if item.node_id in seen:
                raise _BookSemanticProjectionError("semantic item identity is invalid")

            if item.depth == 0:
                if item.parent_id is not None:
                    raise _BookSemanticProjectionError("semantic root parent is invalid")
                parent_index: int | None = None
            else:
                if (
                    type(item.parent_id) is not str
                    or len(item.parent_id) > _MAX_BOOK_SEMANTIC_NODE_ID_CHARS
                ):
                    raise _BookSemanticProjectionError("semantic parent is unavailable")
                if item.parent_id not in seen:
                    raise _BookSemanticProjectionError("semantic parent is unavailable")
                parent_index = seen[item.parent_id]
                if rendered_items[parent_index]["depth"] != item.depth - 1:
                    raise _BookSemanticProjectionError("semantic parent depth is inconsistent")
                if (
                    len(active_ancestor_indices) < item.depth
                    or active_ancestor_indices[item.depth - 1] != parent_index
                ):
                    raise _BookSemanticProjectionError(
                        "semantic parent does not match active ancestry"
                    )
                parent_kind = rendered_items[parent_index]["kind"]
                expected_parent_kind = "move" if item.kind == "variation" else "variation"
                if parent_kind != expected_parent_kind:
                    raise _BookSemanticProjectionError("semantic parent kind is invalid")

            if item.kind == "move":
                if (
                    type(item.comments) is not tuple
                    or type(item.comments_before) is not tuple
                    or type(item.comments_after) is not tuple
                    or type(item.trailing_comments) is not tuple
                ):
                    raise _BookSemanticProjectionError("semantic move comment slots are invalid")
                aggregate_units = preflight_view_comments(item.comments)
                before_units = preflight_view_comments(item.comments_before)
                after_units = preflight_view_comments(item.comments_after)
                preflight_view_comments(item.trailing_comments)
                if (
                    len(item.comments_before) + len(item.comments_after)
                    > _MAX_BOOK_SEMANTIC_TEXT_ENTRIES
                    or before_units + after_units > _MAX_BOOK_BLOCK_VISIBLE_CHARS
                    or aggregate_units > _MAX_BOOK_BLOCK_VISIBLE_CHARS
                    or len(item.comments)
                    != len(item.comments_before) + len(item.comments_after)
                ):
                    raise _BookSemanticProjectionError(
                        "semantic move comment aggregate is inconsistent"
                    )
                for comment_index, aggregate_comment in enumerate(item.comments):
                    if comment_index < len(item.comments_before):
                        expected_comment = item.comments_before[comment_index]
                    else:
                        expected_comment = item.comments_after[
                            comment_index - len(item.comments_before)
                        ]
                    if aggregate_comment != expected_comment:
                        raise _BookSemanticProjectionError(
                            "semantic move comment aggregate is inconsistent"
                        )
                if item.trailing_comments:
                    raise _BookSemanticProjectionError(
                        "semantic move unexpectedly carries line trailing comments"
                    )
                if item.result is not None:
                    raise _BookSemanticProjectionError(
                        "semantic move unexpectedly carries a line result"
                    )
                leading_comments: tuple[str, ...] = ()
                comments_before = safe_many(item.comments_before)
                comments_after = safe_many(item.comments_after)
                trailing_comments: tuple[str, ...] = ()
                item_result = safe(
                    "",
                    max_units=_MAX_BOOK_SEMANTIC_RESULT_UNITS,
                )
            else:
                if (
                    type(item.comments) is not tuple
                    or type(item.comments_before) is not tuple
                    or type(item.comments_after) is not tuple
                    or type(item.trailing_comments) is not tuple
                ):
                    raise _BookSemanticProjectionError(
                        "semantic variation comment slots are invalid"
                    )
                preflight_view_comments(item.comments)
                preflight_view_comments(item.comments_before)
                preflight_view_comments(item.comments_after)
                preflight_view_comments(item.trailing_comments)
                if item.comments_before or item.comments_after:
                    raise _BookSemanticProjectionError(
                        "semantic variation unexpectedly carries move comment slots"
                    )
                leading_comments = safe_many(item.comments)
                comments_before = ()
                comments_after = ()
                trailing_comments = safe_many(item.trailing_comments)
                if item.result is None:
                    item_result = safe(
                        "",
                        max_units=_MAX_BOOK_SEMANTIC_RESULT_UNITS,
                    )
                else:
                    if type(item.result) is not str:
                        raise _BookSemanticProjectionError(
                            "semantic variation result is invalid"
                        )
                    item_result = safe(
                        item.result,
                        allow_empty=False,
                        max_units=_MAX_BOOK_SEMANTIC_RESULT_UNITS,
                    )
                    if item_result not in _BOOK_SEMANTIC_RESULTS:
                        raise _BookSemanticProjectionError(
                            "semantic variation result is invalid"
                        )

                # Variation depth is generated by the browser from canonical
                # depth. Its label is serialized once but repeated for every
                # variation, so account for every rendered copy, punctuation
                # and decimal level before publication.
                variation_level = (item.depth + 1) // 2
                account_visible_units(
                    3
                    + _utf16_units(variation_depth_label)
                    + 2
                    + _utf16_units(str(variation_level))
                )
                if item_result:
                    # Each terminated variation renders the shared result
                    # label again before the already-counted result token.
                    account_visible_units(_utf16_units(result_label) + 2)

            rendered_items.append(
                {
                    "kind": item.kind,
                    "depth": item.depth,
                    "parent_index": parent_index,
                    "label": safe(
                        item.label,
                        allow_empty=False,
                        max_units=_MAX_BOOK_SEMANTIC_ITEM_LABEL_UNITS,
                    ),
                    "leading_comments": leading_comments,
                    "comments_before": comments_before,
                    "comments_after": comments_after,
                    "trailing_comments": trailing_comments,
                    "result": item_result,
                }
            )
            seen[item.node_id] = position
            del active_ancestor_indices[item.depth :]
            active_ancestor_indices.append(position)
            previous_depth = item.depth

        return {
            "_recovery_warning_count": len(workflow_warnings),
            "kind": mode.value,
            "label": semantic_label,
            "players_label": players_label,
            "players": players,
            "details": tuple(details),
            "result_label": result_label,
            "variation_depth_label": variation_depth_label,
            "result": result_text,
            "intro_comments": intro_comments,
            "outro_comments": outro_comments,
            "items": tuple(rendered_items),
        }

    def _workflow_presentation_state(self) -> tuple[bool, int]:
        revision_before = self._workflow.revision
        active = self._workflow.active
        revision_after = self._workflow.revision
        if revision_before != revision_after:
            raise BookBoardWorkflowError(
                "Book Board state changed while preparing semantic reading",
                code=BookBoardWorkflowCode.RETURN_FAILED,
            )
        return active, revision_after

    def _snapshot_from_block(self, block):
        snapshot = super()._snapshot_from_block(block)
        # Reuse the reader-owned detached revision. Never re-read the live mutable
        # BookDocument after the presenter has validated a ReadingLocation.
        semantic, book_title, book_author, source_language = self._reader.block_reading_snapshot(block.index)
        valid_source_language = (type(source_language) is str and len(source_language) <= 63
                                 and re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", source_language))
        def reading_metadata(value):
            if value is None:
                return ""
            # Metadata stays complete in BookDocument; indicate the bounded
            # presentation excerpt rather than scanning a source-sized scalar.
            excerpt = value if len(value) <= 359 else value[:358] + "…"
            return _safe_text(excerpt, language=self.language, limit=360)
        snapshot["book_metadata"] = {
            "title": reading_metadata(book_title),
            "author": reading_metadata(book_author),
            "language": source_language if valid_source_language else "",
        }
        if block.kind in {"Heading", "Paragraph", "List"}:
            # Source metadata is not a UI locale. Publish a bounded language
            # token only for narrative content; chess controls keep UI language.
            if valid_source_language:
                snapshot["block"]["content_language"] = source_language
        board_active, workflow_revision = self._workflow_presentation_state()
        can_open_position = isinstance(
            semantic,
            (Position, Diagram, Exercise, VariationTree),
        )
        can_open_game = isinstance(semantic, Game)
        if isinstance(semantic, (Game, VariationTree)):
            recovery_warning_count = 0
            try:
                semantic_tree = self._semantic_tree_snapshot(block.index)
                if type(semantic_tree) is not dict:
                    raise _BookSemanticProjectionError("semantic GameTree snapshot is invalid")
                recovery_warning_count = semantic_tree.pop(
                    "_recovery_warning_count",
                    0,
                )
                if (
                    type(recovery_warning_count) is not int
                    or not 0 <= recovery_warning_count <= _MAX_BOOK_SEMANTIC_TEXT_ENTRIES
                ):
                    raise _BookSemanticProjectionError(
                        "semantic recovery warning count is invalid"
                    )
                expected_kind = "game" if isinstance(semantic, Game) else "variation"
                if semantic_tree.get("kind") != expected_kind:
                    raise _BookSemanticProjectionError(
                        "semantic GameTree mode disagrees with the Book block"
                    )
                snapshot["semantic_tree"] = semantic_tree
            except BookBoardWorkflowError as error:
                if error.code not in {
                    BookBoardWorkflowCode.CONTENT_UNAVAILABLE,
                    BookBoardWorkflowCode.INVALID_GAME,
                    BookBoardWorkflowCode.INVALID_POSITION,
                }:
                    raise
                snapshot["semantic_tree"] = None
                snapshot["block"]["warning"] = _SEMANTIC_LABELS[self.language]["content_unavailable"]
                if isinstance(semantic, Game):
                    can_open_game = False
                else:
                    can_open_position = False
            except (_BookSemanticProjectionError, AttributeError, TypeError, ValueError):
                snapshot["semantic_tree"] = None
                snapshot["block"]["warning"] = _SEMANTIC_LABELS[self.language]["reading_unavailable"]
            else:
                if recovery_warning_count:
                    recovery_warning = _SEMANTIC_LABELS[self.language][
                        "recovery_warnings"
                    ].format(count=recovery_warning_count)
                    existing_warning = snapshot["block"]["warning"]
                    combined_warning = (
                        f"{recovery_warning} {existing_warning}"
                        if existing_warning
                        else recovery_warning
                    )
                    snapshot["block"]["warning"] = _safe_text(
                        combined_warning,
                        language=self.language,
                        limit=1000,
                    )
        final_board_active, final_workflow_revision = self._workflow_presentation_state()
        if (
            final_board_active != board_active
            or final_workflow_revision != workflow_revision
        ):
            raise BookBoardWorkflowError(
                "Book Board state changed while preparing semantic reading",
                code=BookBoardWorkflowCode.RETURN_FAILED,
            )

        actions = []
        for original in snapshot["actions"]:
            action = dict(original)
            if action["command"] == "book.open_position":
                # The WebView exposes a semantic position control. Native/menu
                # compatibility may still invoke book.open_position for a Game,
                # but the browser gets one unambiguous Game-specific action.
                action["enabled"] = can_open_position and not board_active
                action["label"] = "Відкрити на шахівниці" if self.language is UILanguage.UA else "Open on board"
            elif action["command"] == "book.open_game":
                action["enabled"] = can_open_game and not board_active
            elif action["command"] == "book.return_from_board":
                action["enabled"] = board_active
            actions.append(action)
        snapshot["actions"] = tuple(actions)
        snapshot["board_active"] = board_active
        return snapshot

    def _workflow_action(self, action: str, expected: BookBoardUiEventKind) -> bool:
        try:
            result = self._dispatch(action, {})
        except BaseException:
            # The provider is a host/application boundary. Never let a host abort
            # bypass the Book bridge's sanitized accessible failure result.
            return False
        # A canonical router returns exact ActionDispatchResult while a composed
        # callback may already return the exact UI event. Keep this boundary
        # passive: never probe arbitrary wrappers for a value attribute, and
        # never read fields from provider-defined BookBoardUiEvent subclasses.
        if type(result) is ActionDispatchResult:
            if (
                type(result.action_id) is not str
                or result.action_id != action
                or type(result.handled_by_shell) is not bool
                or result.handled_by_shell
                or result.route_id is not None
                or result.focus_target is not None
            ):
                return False
            result = result.value
        if type(result) is not BookBoardUiEvent:
            return False
        if (
            type(result.kind) is not BookBoardUiEventKind
            or type(result.action_id) is not str
            or type(result.revision) is not int
        ):
            return False
        try:
            workflow_active, workflow_revision = self._workflow_presentation_state()
        except BookBoardWorkflowError:
            return False
        if (
            result.kind is not expected
            or result.action_id != action
            or result.revision != workflow_revision
        ):
            return False
        if expected is BookBoardUiEventKind.BOARD_OPENED:
            return workflow_active
        if expected is BookBoardUiEventKind.RETURNED_TO_BOOK:
            return not workflow_active
        return True

    def open_position(self) -> BookWebViewEvent:
        announcement = self._result_announcement("opened")
        if not self._workflow_action("book.open_position", BookBoardUiEventKind.BOARD_OPENED):
            return self.generic_error()
        return BookWebViewEvent(
            "delegated",
            {
                "action": "book.open_position",
                "announcement": announcement,
            },
        )

    def open_game(self) -> BookWebViewEvent:
        announcement = self._result_announcement("game_opened")
        if not self._workflow_action("book.open_game", BookBoardUiEventKind.BOARD_OPENED):
            return self.generic_error()
        return BookWebViewEvent(
            "delegated",
            {
                "action": "book.open_game",
                "announcement": announcement,
            },
        )

    def return_from_board(self) -> BookWebViewEvent:
        announcement = self._result_announcement("returned")
        if not self._workflow_action("book.return", BookBoardUiEventKind.RETURNED_TO_BOOK):
            return self.generic_error()
        return self._render(
            self._presenter.current(),
            announcement=announcement,
        )


def build_version2_book_webview(reader, workflow, dispatch, *, language=UILanguage.UA) -> BookWebViewBridge:
    return BookWebViewBridge(Version2BookWebViewProjection(reader, workflow, dispatch, language=language))
