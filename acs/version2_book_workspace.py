"""Accessible Books composition over the accepted reader and Board workflow.

The V2 projection uses the workflow's return stack for both open and return.
It never creates the legacy presenter's independent Board return point.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .book_board_workflow import (
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
)
from .bookdocument import Diagram, Exercise, Game, Position, VariationTree
from .bookreader import BookReader
from .full_product_presenters import BookReaderPresenter, PgnTreePresenter
from .full_product_ui_shell import UILanguage
from .version2_windows_book_board_adapter import BookBoardUiEvent, BookBoardUiEventKind


_MAX_BOOK_SEMANTIC_ITEMS = 10_000
_MAX_BOOK_SEMANTIC_DEPTH = 256
_MAX_BOOK_SEMANTIC_DETAILS = 4_096
_MAX_BOOK_SEMANTIC_TEXT_ENTRIES = 50_000
_BOOK_SEMANTIC_RESULTS = frozenset({"1-0", "0-1", "1/2-1/2", "*"})
_BOOK_SEMANTIC_HIDDEN_TAGS = frozenset({"white", "black", "result", "fen"})

_SEMANTIC_TREE_LABELS = {
    UILanguage.UA: {
        "moves": "Ходи та варіанти",
        "players": "Гравці",
        "result": "Результат",
        "details": "Відомості про партію",
        "event": "Подія",
        "site": "Місце",
        "date": "Дата",
        "round": "Тур",
        "comments": "Коментарі",
        "intro_comments": "Коментарі перед ходами",
        "outro_comments": "Коментарі після ходів",
        "warnings": "Попередження відновлення",
        "unavailable": "Вміст партії недоступний або некоректний; ходи не показано.",
        "reading_unavailable": (
            "Список ходів завеликий або його неможливо безпечно показати; "
            "шахівниця залишається доступною."
        ),
    },
    UILanguage.EN: {
        "moves": "Moves and variations",
        "players": "Players",
        "result": "Result",
        "details": "Game details",
        "event": "Event",
        "site": "Site",
        "date": "Date",
        "round": "Round",
        "comments": "Comments",
        "intro_comments": "Comments before moves",
        "outro_comments": "Comments after moves",
        "warnings": "Recovery warnings",
        "unavailable": "Game content is unavailable or invalid; moves are not shown.",
        "reading_unavailable": (
            "The move list is too large or cannot be displayed safely; "
            "the board remains available."
        ),
    },
}

_SEMANTIC_RECOVERY_WARNINGS = {
    UILanguage.UA: {
        "duplicate_tag": "Дубльований тег PGN відновлено; використано останнє значення.",
        "nested_comment": "Вкладені дужки коментаря PGN нормалізовано.",
        "unterminated_comment": "Незавершений коментар PGN відновлено.",
        "unmatched_brace": "Зайву закривальну дужку коментаря PGN пропущено.",
        "malformed_nag": "Некоректну числову анотацію PGN відновлено.",
        "unmatched_parenthesis": "Зайву закривальну дужку варіанта PGN пропущено.",
        "unterminated_variation": "Незавершений варіант PGN відновлено.",
        "orphan_variation": "Варіант без попереднього ходу відновлено.",
        "annotation": "Некоректну шахову анотацію PGN відновлено.",
        "unconsumed": "Частину некоректних токенів PGN пропущено під час відновлення.",
        "invalid_result": "Некоректний результат у заголовку PGN проігноровано.",
        "result_mismatch": (
            "Результат у заголовку PGN не збігався з текстом партії; "
            "використано канонічний результат."
        ),
        "missing_termination": (
            "Відсутній маркер завершення партії PGN; результат відновлено."
        ),
        "other": (
            "PGN потребував відновлення; деталі пошкодженого джерела приховано."
        ),
    },
    UILanguage.EN: {
        "duplicate_tag": "A duplicate PGN tag was recovered; the last value was used.",
        "nested_comment": "Nested PGN comment delimiters were normalized.",
        "unterminated_comment": "An unterminated PGN comment was recovered.",
        "unmatched_brace": "An unmatched PGN comment brace was ignored.",
        "malformed_nag": "A malformed numeric PGN annotation was recovered.",
        "unmatched_parenthesis": "An unmatched PGN variation parenthesis was ignored.",
        "unterminated_variation": "An unterminated PGN variation was recovered.",
        "orphan_variation": "A PGN variation without a preceding move was recovered.",
        "annotation": "A malformed PGN chess annotation was recovered.",
        "unconsumed": "Malformed PGN tokens were skipped during recovery.",
        "invalid_result": "An invalid PGN header result was ignored.",
        "result_mismatch": (
            "The PGN header result differed from movetext; the canonical result was used."
        ),
        "missing_termination": (
            "The PGN game termination marker was missing; the result was recovered."
        ),
        "other": (
            "The PGN source required recovery; damaged source details were hidden."
        ),
    },
}


def _semantic_recovery_warning(value: object, language: UILanguage) -> tuple[str, str]:
    """Classify parser recovery without publishing source-derived warning payloads."""
    if not isinstance(value, str) or not value.strip():
        raise _BookSemanticTreeError("book semantic recovery warning is invalid")
    raw = value.strip()
    if raw.startswith("duplicate tag "):
        key = "duplicate_tag"
    elif raw == "nested brace comment delimiters normalized to parentheses":
        key = "nested_comment"
    elif raw == "unterminated brace comment":
        key = "unterminated_comment"
    elif raw == "unmatched closing brace":
        key = "unmatched_brace"
    elif raw == "malformed numeric annotation glyph":
        key = "malformed_nag"
    elif raw == "unmatched closing parenthesis":
        key = "unmatched_parenthesis"
    elif raw == "unterminated variation":
        key = "unterminated_variation"
    elif raw == "variation has no preceding move":
        key = "orphan_variation"
    elif raw.startswith("numeric annotation glyph out of range ") or raw.startswith(
        "orphan annotation "
    ):
        key = "annotation"
    elif raw.endswith(" unconsumed token(s)"):
        key = "unconsumed"
    elif raw.startswith("invalid header Result "):
        key = "invalid_result"
    elif raw.startswith("header Result ") and " differs from movetext " in raw:
        key = "result_mismatch"
    elif raw.startswith("missing movetext game termination marker;"):
        key = "missing_termination"
    else:
        key = "other"
    return key, _SEMANTIC_RECOVERY_WARNINGS[language][key]


class _BookSemanticTreeError(ValueError):
    """Known fail-closed presentation error for otherwise canonical GameTree data."""


def _semantic_tree_within_limits(
    line: object,
    *,
    item_limit: int,
    depth_limit: int,
) -> bool:
    """Bound Book semantic materialization before shared presenter allocation.

    BookBoardWorkflow.semantic_game_snapshot has already returned a detached,
    serialized/legality-validated canonical GameTree. Count only the presentation
    nodes Books will create: every move plus one wrapper for each non-root RAV.
    Track the presenter's exact move/variation depth iteratively as well, so an
    adversarially deep RAV cannot reach the recursive PgnTreePresenter first.
    """
    if type(item_limit) is not int or item_limit < 0:
        raise ValueError("book semantic item limit is invalid")
    if type(depth_limit) is not int or depth_limit < 0:
        raise ValueError("book semantic depth limit is invalid")

    count = 0
    stack: list[tuple[object, int]] = [(line, 0)]
    while stack:
        current, move_depth = stack.pop()
        moves = getattr(current, "moves", ())
        if moves and move_depth > depth_limit:
            return False
        for move in moves:
            count += 1
            if count > item_limit:
                return False
            for variation in getattr(move, "variations", ()):
                variation_depth = move_depth + 1
                if variation_depth > depth_limit:
                    return False
                count += 1
                if count > item_limit:
                    return False
                stack.append((variation, move_depth + 2))
    return True


class Version2BookReaderPresenter(BookReaderPresenter):
    """V2 presentation reuses the canonical BookReader semantic block projection."""


class Version2BookWebViewProjection(BookWebViewProjection):
    def __init__(
        self,
        reader: BookReader,
        workflow: BookBoardWorkflow,
        dispatch: Callable[[str, Mapping[str, object]], Any],
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(reader, BookReader) or not isinstance(workflow, BookBoardWorkflow):
            raise TypeError("V2 Books requires the canonical reader and workflow")
        self._reader = reader
        self._workflow = workflow
        super().__init__(Version2BookReaderPresenter(reader, language=language), dispatch, language=language)

    def _semantic_tree_snapshot(self, index: int) -> dict[str, object]:
        mode, game, workflow_warnings = self._workflow.semantic_game_snapshot(index)
        if not _semantic_tree_within_limits(
            game.line,
            item_limit=_MAX_BOOK_SEMANTIC_ITEMS,
            depth_limit=_MAX_BOOK_SEMANTIC_DEPTH,
        ):
            raise _BookSemanticTreeError(
                "book semantic GameTree item/depth limit exceeded"
            )
        try:
            view = PgnTreePresenter((game,), language=self.language).view()
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise _BookSemanticTreeError(
                "book semantic GameTree presenter data is invalid"
            ) from exc
        if view.game_index != 0:
            raise _BookSemanticTreeError("book semantic GameTree projection is unavailable")

        visible_total = 0
        visible_entries = 0

        def safe(value: object) -> str:
            nonlocal visible_total, visible_entries
            visible_entries += 1
            if visible_entries > _MAX_BOOK_SEMANTIC_TEXT_ENTRIES:
                raise _BookSemanticTreeError(
                    "book semantic GameTree text-entry limit exceeded"
                )
            try:
                text = _safe_text(
                    value,
                    language=self.language,
                    limit=_MAX_BOOK_BLOCK_VISIBLE_CHARS + 1,
                )
            except (TypeError, ValueError) as exc:
                raise _BookSemanticTreeError(
                    "book semantic GameTree text is invalid"
                ) from exc
            visible_total += len(text)
            if visible_total > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
                raise _BookSemanticTreeError(
                    "book semantic GameTree exceeds the visible-text budget"
                )
            return text

        def safe_comment_text(value: object) -> str:
            try:
                raw_text = value.text
            except AttributeError as exc:
                raise _BookSemanticTreeError(
                    "book semantic GameTree comment is invalid"
                ) from exc
            return safe(raw_text)

        labels = _SEMANTIC_TREE_LABELS[self.language]
        intro_comments = tuple(
            comment
            for comment in (safe_comment_text(raw) for raw in game.line.leading_comments)
            if comment
        )

        if len(view.items) > _MAX_BOOK_SEMANTIC_ITEMS:
            raise _BookSemanticTreeError(
                "book semantic GameTree exceeds the browser item limit"
            )

        rendered_items: list[dict[str, object]] = []
        seen_node_indices: dict[str, int] = {}
        active_ancestor_indices: list[int] = []
        previous_depth = 0
        for position, item in enumerate(view.items):
            if item.kind not in {"move", "variation"}:
                raise _BookSemanticTreeError("book semantic GameTree item kind is invalid")
            if type(item.depth) is not int or item.depth < 0:
                raise _BookSemanticTreeError("book semantic GameTree depth is invalid")
            if item.depth > _MAX_BOOK_SEMANTIC_DEPTH:
                raise _BookSemanticTreeError(
                    "book semantic GameTree depth limit exceeded"
                )
            if (
                (item.kind == "move" and item.depth % 2 != 0)
                or (item.kind == "variation" and item.depth % 2 != 1)
            ):
                raise _BookSemanticTreeError(
                    "book semantic GameTree kind/depth alternation is invalid"
                )
            if position == 0 and item.depth != 0:
                raise _BookSemanticTreeError("book semantic GameTree root depth is invalid")
            if position > 0 and item.depth > previous_depth + 1:
                raise _BookSemanticTreeError("book semantic GameTree depth jumps unexpectedly")

            node_id = item.node_id
            if type(node_id) is not str or not node_id:
                raise _BookSemanticTreeError("book semantic GameTree node identity is invalid")
            if node_id in seen_node_indices:
                raise _BookSemanticTreeError("book semantic GameTree node identity is duplicated")

            if item.depth == 0:
                if item.parent_id is not None:
                    raise _BookSemanticTreeError("book semantic GameTree root parent is invalid")
                parent_index: int | None = None
            else:
                parent_id = item.parent_id
                if type(parent_id) is not str or not parent_id:
                    raise _BookSemanticTreeError("book semantic GameTree parent identity is invalid")
                parent_index = seen_node_indices.get(parent_id)
                if parent_index is None:
                    raise _BookSemanticTreeError("book semantic GameTree parent is unavailable")
                if (
                    len(active_ancestor_indices) < item.depth
                    or active_ancestor_indices[item.depth - 1] != parent_index
                ):
                    raise _BookSemanticTreeError(
                        "book semantic GameTree parent does not match active ancestry"
                    )
                parent_kind = rendered_items[parent_index]["kind"]
                expected_parent_kind = "move" if item.kind == "variation" else "variation"
                if parent_kind != expected_parent_kind:
                    raise _BookSemanticTreeError(
                        "book semantic GameTree parent kind is invalid"
                    )

            label = safe(item.label)
            if not label:
                raise _BookSemanticTreeError("book semantic GameTree item label is empty")
            if item.kind == "move":
                comments_before = tuple(
                    comment
                    for comment in (safe(raw) for raw in item.comments_before)
                    if comment
                )
                comments_after = tuple(
                    comment
                    for comment in (safe(raw) for raw in item.comments_after)
                    if comment
                )
                comments = ()
            else:
                comments_before = ()
                comments_after = ()
                comments = tuple(
                    comment
                    for comment in (safe(raw) for raw in item.comments)
                    if comment
                )
            trailing_comments = tuple(
                comment
                for comment in (safe(raw) for raw in item.trailing_comments)
                if comment
            )
            try:
                line_result = item.result
            except AttributeError as exc:
                raise _BookSemanticTreeError(
                    "book semantic GameTree item result is unavailable"
                ) from exc
            result = ""
            if line_result is not None:
                if item.kind != "variation":
                    raise _BookSemanticTreeError(
                        "book semantic move unexpectedly carries a line result"
                    )
                result = safe(line_result)
                if result not in _BOOK_SEMANTIC_RESULTS:
                    raise _BookSemanticTreeError(
                        "book semantic variation result is invalid"
                    )
            rendered_items.append(
                {
                    "kind": item.kind,
                    "depth": item.depth,
                    "parent_index": parent_index,
                    "label": label,
                    "comments": comments,
                    "comments_before": comments_before,
                    "comments_after": comments_after,
                    "result": result,
                    "trailing_comments": trailing_comments,
                }
            )
            seen_node_indices[node_id] = position
            del active_ancestor_indices[item.depth:]
            active_ancestor_indices.append(position)
            previous_depth = item.depth

        outro_comments = tuple(
            comment
            for comment in (safe_comment_text(raw) for raw in game.line.trailing_comments)
            if comment
        )
        rendered_warnings: list[str] = []
        seen_warning_kinds: set[str] = set()
        for raw_warning in workflow_warnings:
            warning_kind, warning_text = _semantic_recovery_warning(
                raw_warning,
                self.language,
            )
            if warning_kind in seen_warning_kinds:
                continue
            seen_warning_kinds.add(warning_kind)
            rendered_warnings.append(safe(warning_text))
        warnings = tuple(rendered_warnings)
        players = safe(view.title)
        if players == "? — ?":
            players = ""

        try:
            view_tags = view.tags
        except AttributeError as exc:
            raise _BookSemanticTreeError(
                "book semantic GameTree metadata is unavailable"
            ) from exc
        if type(view_tags) is not tuple:
            raise _BookSemanticTreeError(
                "book semantic GameTree metadata must be a tuple"
            )
        if len(view_tags) > _MAX_BOOK_SEMANTIC_DETAILS:
            raise _BookSemanticTreeError(
                "book semantic GameTree exceeds the metadata detail limit"
            )
        localized_detail_labels = {
            "Event": ("event", labels["event"]),
            "Site": ("site", labels["site"]),
            "Date": ("date", labels["date"]),
            "Round": ("round", labels["round"]),
        }
        details: list[dict[str, str]] = []
        seen_detail_kinds: set[str] = set()
        for detail in view_tags:
            if type(detail) is not tuple or len(detail) != 2:
                raise _BookSemanticTreeError(
                    "book semantic metadata entry is invalid"
                )
            tag_name, raw_value = detail
            if type(tag_name) is not str or not tag_name.strip():
                raise _BookSemanticTreeError(
                    "book semantic metadata tag name is invalid"
                )
            if tag_name.casefold() in _BOOK_SEMANTIC_HIDDEN_TAGS:
                continue
            localized = localized_detail_labels.get(tag_name)
            if localized is None:
                detail_label = safe(tag_name)
                if not detail_label.strip():
                    raise _BookSemanticTreeError(
                        "book semantic metadata tag label is empty"
                    )
                detail_kind = f"custom:{detail_label}"
            else:
                detail_kind, detail_label = localized
            if detail_kind in seen_detail_kinds:
                raise _BookSemanticTreeError(
                    "book semantic metadata identity is duplicated"
                )
            seen_detail_kinds.add(detail_kind)
            details.append(
                {
                    "kind": detail_kind,
                    "label": detail_label,
                    "value": safe(raw_value),
                }
            )

        result = safe(view.result)
        if result not in _BOOK_SEMANTIC_RESULTS:
            raise _BookSemanticTreeError("book semantic GameTree result is invalid")

        return {
            "kind": mode.value,
            "label": labels["moves"],
            "players_label": labels["players"],
            "players": players,
            "result_label": labels["result"],
            "result": result,
            "details_label": labels["details"],
            "details": tuple(details),
            "comments_label": labels["comments"],
            "intro_comments_label": labels["intro_comments"],
            "intro_comments": intro_comments,
            "outro_comments_label": labels["outro_comments"],
            "outro_comments": outro_comments,
            "warnings_label": labels["warnings"],
            "warnings": warnings,
            "items": tuple(rendered_items),
        }

    def _snapshot_from_block(self, block):
        snapshot = super()._snapshot_from_block(block)
        # Reuse the reader-owned detached revision. Never re-read the live mutable
        # BookDocument after the presenter has validated a ReadingLocation.
        semantic = self._reader.block_snapshot(block.index)
        can_open = isinstance(semantic, (Position, Diagram, Exercise, Game, VariationTree))
        if isinstance(semantic, (Game, VariationTree)):
            try:
                snapshot["block"]["semantic_tree"] = self._semantic_tree_snapshot(block.index)
            except _BookSemanticTreeError:
                # The canonical game is valid, but its semantic reading surface
                # exceeded a presentation invariant/budget. Fail closed only for
                # the move-list projection; the canonical Board workflow remains
                # available and no partial semantic tree is published.
                snapshot["block"]["warning"] = _SEMANTIC_TREE_LABELS[
                    self.language
                ]["reading_unavailable"]
            except BookBoardWorkflowError as error:
                if error.code not in {
                    BookBoardWorkflowCode.CONTENT_UNAVAILABLE,
                    BookBoardWorkflowCode.INVALID_GAME,
                }:
                    raise
                # Invalid/unresolvable chess content is a content state, not a
                # reason to crash the whole V2 application snapshot. Publish no
                # invented moves and disable Board open for this exact block.
                can_open = False
                snapshot["block"]["warning"] = _SEMANTIC_TREE_LABELS[
                    self.language
                ]["unavailable"]
        actions = []
        for original in snapshot["actions"]:
            action = dict(original)
            if action["command"] == "book.open_position":
                action["enabled"] = can_open and not self._workflow.active
                action["label"] = "Відкрити на шахівниці" if self.language is UILanguage.UA else "Open on board"
            elif action["command"] == "book.return_from_board":
                action["enabled"] = self._workflow.active
            actions.append(action)
        snapshot["actions"] = tuple(actions)
        return snapshot

    def _workflow_action(self, action: str, expected: BookBoardUiEventKind) -> bool:
        result = self._dispatch(action, {})
        # A canonical router returns ActionDispatchResult; a composed callback
        # may already unwrap it. A transition is successful only when the event
        # belongs to the action we dispatched and the canonical workflow reached
        # the corresponding state. This prevents stale/misrouted success DTOs
        # from producing false NVDA success announcements.
        result = getattr(result, "value", result)
        if (
            not isinstance(result, BookBoardUiEvent)
            or result.kind is not expected
            or result.action_id != action
            or result.revision != self._workflow.revision
        ):
            return False
        if expected is BookBoardUiEventKind.BOARD_OPENED:
            return self._workflow.active
        if expected is BookBoardUiEventKind.RETURNED_TO_BOOK:
            return not self._workflow.active
        return True

    def open_position(self) -> BookWebViewEvent:
        if not self._workflow_action("book.open_position", BookBoardUiEventKind.BOARD_OPENED):
            return self.generic_error()
        return BookWebViewEvent(
            "delegated",
            {
                "action": "book.open_position",
                "announcement": self._result_announcement("opened"),
            },
        )

    def return_from_board(self) -> BookWebViewEvent:
        if not self._workflow_action("book.return", BookBoardUiEventKind.RETURNED_TO_BOOK):
            return self.generic_error()
        return self._render(
            self._presenter.current(),
            announcement=self._result_announcement("returned"),
        )


def build_version2_book_webview(reader, workflow, dispatch, *, language=UILanguage.UA) -> BookWebViewBridge:
    return BookWebViewBridge(Version2BookWebViewProjection(reader, workflow, dispatch, language=language))
