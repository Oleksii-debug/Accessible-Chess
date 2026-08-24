from __future__ import annotations

"""Professional in-memory PGN workspace over the canonical GameTree.

This module owns document/session orchestration only.  It deliberately reuses the
strict D06 codec plus the canonical navigation/edit/annotation/insertion APIs.
It does not own filesystem publication (D04), chess legality/Position (D02), or
presentation/UI (D01).

A workspace always contains a strict round-trip-safe document.  Callers receive
deep copies of mutable GameTree DTOs, so presentation code cannot mutate the
canonical workspace behind the revision/dirty boundary.
"""

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import hashlib
from typing import Iterable

from .game_identity import identity_for_game
from .gametree import MoveNode, PgnGame, VariationLine
from .gametree_annotations import (
    AnnotationEditResult,
    LineAnnotationPatch,
    LineAnnotationTarget,
    MoveAnnotationPatch,
    MoveAnnotationTarget,
    edit_line_annotations,
    edit_move_annotations,
)
from .gametree_editing import (
    GameTreeEditResult,
    VariationEditTarget,
    delete_variation as _delete_variation,
    promote_variation as _promote_variation,
    reorder_variation as _reorder_variation,
)
from .gametree_insertion import (
    VariationInsertResult,
    VariationInsertTarget,
    add_variation as _add_variation,
)
from .gametree_navigation import (
    GameTreeCursor,
    GameTreeNavigationError,
    VariationStep,
    advance,
    current_move as _current_move,
    enter_variation as _enter_variation,
    leave_variation as _leave_variation,
    resolve_line,
    validate_cursor,
)
from .pgn_roundtrip import (
    PgnRoundTripError,
    canonical_round_trip_bytes,
    canonical_round_trip_text,
    parse_pgn_text,
    serialize_pgn_bytes,
    serialize_pgn_text,
)


class PgnWorkspaceErrorCode(str, Enum):
    INVALID_DOCUMENT = "invalid_document"
    EMPTY_DOCUMENT = "empty_document"
    GAME_INDEX = "game_index"
    NO_PREVIOUS_GAME = "no_previous_game"
    NO_NEXT_GAME = "no_next_game"
    CURSOR = "cursor"
    NO_PREVIOUS_MOVE = "no_previous_move"
    NO_NEXT_MOVE = "no_next_move"
    NO_VARIATION = "no_variation"


class PgnWorkspaceError(ValueError):
    """Stable failure for document/session orchestration."""

    def __init__(self, message: str, *, code: PgnWorkspaceErrorCode) -> None:
        super().__init__(message)
        self.code = PgnWorkspaceErrorCode(code)


@dataclass(frozen=True, slots=True)
class PgnGameSummary:
    index: int
    source_index: int
    event: str
    white: str
    black: str
    result: str


@dataclass(frozen=True, slots=True)
class PgnWorkspaceView:
    game_count: int
    selected_game_index: int
    cursor: GameTreeCursor
    dirty: bool
    content_revision: int
    content_digest: str
    current_record_digest: str


def _workspace_error(message: str, code: PgnWorkspaceErrorCode) -> PgnWorkspaceError:
    return PgnWorkspaceError(message, code=code)


def _validate_document(games: Iterable[PgnGame]) -> list[PgnGame]:
    try:
        snapshot = tuple(deepcopy(tuple(games)))
    except TypeError as exc:
        raise _workspace_error(
            "PGN workspace requires an iterable of games",
            PgnWorkspaceErrorCode.INVALID_DOCUMENT,
        ) from exc
    if not snapshot:
        raise _workspace_error(
            "PGN workspace cannot be empty",
            PgnWorkspaceErrorCode.EMPTY_DOCUMENT,
        )
    try:
        text = serialize_pgn_text(snapshot)
        reparsed = parse_pgn_text(text, strict=True)
    except PgnRoundTripError as exc:
        raise _workspace_error(
            "PGN document is not strict round-trip safe",
            PgnWorkspaceErrorCode.INVALID_DOCUMENT,
        ) from exc
    if reparsed != snapshot:
        raise _workspace_error(
            "PGN document changes under canonical round-trip",
            PgnWorkspaceErrorCode.INVALID_DOCUMENT,
        )
    return list(reparsed)


def _digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="strict")).hexdigest()


class PgnWorkspace:
    """One strict multi-game PGN editing/navigation session.

    Navigation and game selection are session state and do not mark the document
    dirty.  Structural/annotation edits increment ``content_revision`` and mark
    dirty relative to the last ``mark_saved()`` checkpoint.
    """

    def __init__(self, games: Iterable[PgnGame]) -> None:
        self._games = _validate_document(games)
        self._selected_game_index = 0
        self._cursor = GameTreeCursor()
        self._content_revision = 0
        self._baseline_digest = self.content_digest
        self._dirty = False

    @classmethod
    def from_text(cls, text: object) -> "PgnWorkspace":
        try:
            result = canonical_round_trip_text(text)
        except PgnRoundTripError as exc:
            raise _workspace_error(
                "PGN text is not strict round-trip safe",
                PgnWorkspaceErrorCode.INVALID_DOCUMENT,
            ) from exc
        return cls(result.games)

    @classmethod
    def from_bytes(cls, data: object) -> "PgnWorkspace":
        try:
            _, games = canonical_round_trip_bytes(data)
        except PgnRoundTripError as exc:
            raise _workspace_error(
                "PGN bytes are not strict round-trip safe",
                PgnWorkspaceErrorCode.INVALID_DOCUMENT,
            ) from exc
        return cls(games)

    @property
    def game_count(self) -> int:
        return len(self._games)

    @property
    def selected_game_index(self) -> int:
        return self._selected_game_index

    @property
    def cursor(self) -> GameTreeCursor:
        return self._cursor

    @property
    def content_revision(self) -> int:
        return self._content_revision

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def content_digest(self) -> str:
        return _digest_text(serialize_pgn_text(tuple(self._games)))

    def view(self) -> PgnWorkspaceView:
        game = self._current_game_ref()
        return PgnWorkspaceView(
            game_count=self.game_count,
            selected_game_index=self._selected_game_index,
            cursor=self._cursor,
            dirty=self._dirty,
            content_revision=self._content_revision,
            content_digest=self.content_digest,
            current_record_digest=identity_for_game(game).record_digest,
        )

    def summaries(self) -> tuple[PgnGameSummary, ...]:
        out: list[PgnGameSummary] = []
        for index, game in enumerate(self._games):
            out.append(
                PgnGameSummary(
                    index=index,
                    source_index=game.source_index,
                    event=game.tags.get("Event", ""),
                    white=game.tags.get("White", ""),
                    black=game.tags.get("Black", ""),
                    result=game.result,
                )
            )
        return tuple(out)

    def games(self) -> tuple[PgnGame, ...]:
        """Return a detached document snapshot."""

        return tuple(deepcopy(self._games))

    def current_game(self) -> PgnGame:
        """Return a detached copy of the selected canonical game."""

        return deepcopy(self._current_game_ref())

    def current_move(self) -> MoveNode | None:
        move = _current_move(self._current_game_ref(), self._cursor)
        return deepcopy(move) if move is not None else None

    def to_text(self) -> str:
        return serialize_pgn_text(tuple(self._games))

    def to_bytes(self) -> bytes:
        return serialize_pgn_bytes(tuple(self._games))

    def mark_saved(self) -> PgnWorkspaceView:
        self._baseline_digest = self.content_digest
        self._dirty = False
        return self.view()

    def _current_game_ref(self) -> PgnGame:
        return self._games[self._selected_game_index]

    def _require_game_index(self, index: object) -> int:
        if type(index) is not int or index < 0 or index >= len(self._games):
            raise _workspace_error(
                "game index is out of range",
                PgnWorkspaceErrorCode.GAME_INDEX,
            )
        return index

    def select_game(self, index: object) -> PgnWorkspaceView:
        self._selected_game_index = self._require_game_index(index)
        self._cursor = GameTreeCursor()
        return self.view()

    def next_game(self) -> PgnWorkspaceView:
        if self._selected_game_index + 1 >= len(self._games):
            raise _workspace_error(
                "already at the last game",
                PgnWorkspaceErrorCode.NO_NEXT_GAME,
            )
        return self.select_game(self._selected_game_index + 1)

    def previous_game(self) -> PgnWorkspaceView:
        if self._selected_game_index == 0:
            raise _workspace_error(
                "already at the first game",
                PgnWorkspaceErrorCode.NO_PREVIOUS_GAME,
            )
        return self.select_game(self._selected_game_index - 1)

    def set_cursor(self, cursor: GameTreeCursor) -> PgnWorkspaceView:
        try:
            self._cursor = validate_cursor(self._current_game_ref(), cursor)
        except (TypeError, GameTreeNavigationError) as exc:
            raise _workspace_error(
                "cursor is not valid in the selected game",
                PgnWorkspaceErrorCode.CURSOR,
            ) from exc
        return self.view()

    def line_start(self) -> PgnWorkspaceView:
        self._cursor = GameTreeCursor(self._cursor.line_path, 0)
        return self.view()

    def line_end(self) -> PgnWorkspaceView:
        line = resolve_line(self._current_game_ref(), self._cursor.line_path)
        self._cursor = GameTreeCursor(self._cursor.line_path, len(line.moves))
        return self.view()

    def document_start(self) -> PgnWorkspaceView:
        self._selected_game_index = 0
        self._cursor = GameTreeCursor()
        return self.view()

    def document_end(self) -> PgnWorkspaceView:
        self._selected_game_index = len(self._games) - 1
        line = self._current_game_ref().line
        self._cursor = GameTreeCursor((), len(line.moves))
        return self.view()

    def next_move(self) -> PgnWorkspaceView:
        try:
            self._cursor = advance(self._current_game_ref(), self._cursor)
        except GameTreeNavigationError as exc:
            raise _workspace_error(
                "already at the end of this variation",
                PgnWorkspaceErrorCode.NO_NEXT_MOVE,
            ) from exc
        return self.view()

    def previous_move(self) -> PgnWorkspaceView:
        try:
            validate_cursor(self._current_game_ref(), self._cursor)
        except GameTreeNavigationError as exc:
            raise _workspace_error(
                "cursor is not valid in the selected game",
                PgnWorkspaceErrorCode.CURSOR,
            ) from exc
        if self._cursor.next_move_index == 0:
            raise _workspace_error(
                "already at the start of this variation",
                PgnWorkspaceErrorCode.NO_PREVIOUS_MOVE,
            )
        self._cursor = GameTreeCursor(
            self._cursor.line_path,
            self._cursor.next_move_index - 1,
        )
        return self.view()

    def enter_variation(self, variation_index: int = 0) -> PgnWorkspaceView:
        try:
            self._cursor = _enter_variation(
                self._current_game_ref(), self._cursor, variation_index
            )
        except (TypeError, ValueError, GameTreeNavigationError) as exc:
            raise _workspace_error(
                "requested variation is not available at the cursor",
                PgnWorkspaceErrorCode.NO_VARIATION,
            ) from exc
        return self.view()

    def leave_variation(self) -> PgnWorkspaceView:
        try:
            self._cursor = _leave_variation(self._current_game_ref(), self._cursor)
        except GameTreeNavigationError as exc:
            raise _workspace_error(
                "cursor is not inside a variation",
                PgnWorkspaceErrorCode.NO_VARIATION,
            ) from exc
        return self.view()

    def sibling_variation(self, offset: int) -> PgnWorkspaceView:
        if type(offset) is not int or offset == 0:
            raise _workspace_error(
                "sibling variation offset must be a non-zero exact integer",
                PgnWorkspaceErrorCode.NO_VARIATION,
            )
        if not self._cursor.line_path:
            raise _workspace_error(
                "root line has no sibling variation",
                PgnWorkspaceErrorCode.NO_VARIATION,
            )
        current_step = self._cursor.line_path[-1]
        parent_path = self._cursor.line_path[:-1]
        parent = resolve_line(self._current_game_ref(), parent_path)
        owner = parent.moves[current_step.parent_move_index]
        sibling_index = current_step.variation_index + offset
        if sibling_index < 0 or sibling_index >= len(owner.variations):
            raise _workspace_error(
                "requested sibling variation does not exist",
                PgnWorkspaceErrorCode.NO_VARIATION,
            )
        self._cursor = GameTreeCursor(
            parent_path
            + (VariationStep(current_step.parent_move_index, sibling_index),),
            0,
        )
        return self.view()

    def _commit_current_game(
        self,
        game: PgnGame,
        *,
        cursor: GameTreeCursor | None = None,
    ) -> PgnWorkspaceView:
        candidate = list(self._games)
        candidate[self._selected_game_index] = game
        validated = _validate_document(candidate)
        next_cursor = self._cursor if cursor is None else cursor
        try:
            validate_cursor(validated[self._selected_game_index], next_cursor)
        except GameTreeNavigationError as exc:
            raise _workspace_error(
                "edit produced an invalid navigation cursor",
                PgnWorkspaceErrorCode.CURSOR,
            ) from exc
        self._games = validated
        self._cursor = next_cursor
        self._content_revision += 1
        self._dirty = self.content_digest != self._baseline_digest
        return self.view()

    def edit_move_annotations(
        self,
        target: MoveAnnotationTarget,
        patch: MoveAnnotationPatch,
    ) -> AnnotationEditResult:
        result = edit_move_annotations(self._current_game_ref(), target, patch)
        self._commit_current_game(result.game)
        return result

    def edit_line_annotations(
        self,
        target: LineAnnotationTarget,
        patch: LineAnnotationPatch,
    ) -> AnnotationEditResult:
        result = edit_line_annotations(self._current_game_ref(), target, patch)
        self._commit_current_game(result.game)
        return result

    def add_variation(
        self,
        target: VariationInsertTarget,
        variation: VariationLine,
    ) -> VariationInsertResult:
        result = _add_variation(self._current_game_ref(), target, variation)
        self._commit_current_game(result.game, cursor=result.remap_cursor(self._cursor))
        return result

    def reorder_variation(
        self,
        target: VariationEditTarget,
        new_index: int,
    ) -> GameTreeEditResult:
        result = _reorder_variation(self._current_game_ref(), target, new_index)
        remapped = result.remap_cursor(self._cursor)
        if remapped is None:
            raise _workspace_error(
                "reorder unexpectedly removed the active cursor",
                PgnWorkspaceErrorCode.CURSOR,
            )
        self._commit_current_game(result.game, cursor=remapped)
        return result

    def delete_variation(self, target: VariationEditTarget) -> GameTreeEditResult:
        result = _delete_variation(self._current_game_ref(), target)
        remapped = result.remap_cursor(self._cursor)
        if remapped is None:
            remapped = GameTreeCursor(
                target.parent_path,
                target.parent_move_index + 1,
            )
        self._commit_current_game(result.game, cursor=remapped)
        return result

    def promote_variation(self, target: VariationEditTarget) -> GameTreeEditResult:
        result = _promote_variation(self._current_game_ref(), target)
        remapped = result.remap_cursor(self._cursor)
        if remapped is None:
            raise _workspace_error(
                "promotion unexpectedly removed the active cursor",
                PgnWorkspaceErrorCode.CURSOR,
            )
        self._commit_current_game(result.game, cursor=remapped)
        return result
