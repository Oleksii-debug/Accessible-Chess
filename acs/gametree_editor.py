from __future__ import annotations

"""Canonical professional GameTree editor over :mod:`acs.pgn_workspace`.

This is an orchestration layer, not a second GameTree. It reuses the canonical
``PgnGame``/``VariationLine`` graph, existing structural/annotation/insertion
services, and ``chesscore.Board`` for every move-bearing mutation.
"""

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum

from .chesscore import Board
from .game_identity import identity_for_game
from .gametree import (
    MAX_TREE_NODES,
    RESULTS,
    TAG_NAME_RE,
    Comment,
    MoveNode,
    PgnGame,
    VariationLine,
)
from .gametree_annotations import (
    AnnotationEditResult,
    LineAnnotationPatch,
    MoveAnnotationPatch,
    edit_line_annotations as _edit_line_annotations,
    edit_move_annotations as _edit_move_annotations,
    line_annotation_target,
    move_annotation_target,
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
    variation_insert_target,
)
from .gametree_legality import validate_game_legality
from .gametree_navigation import (
    GameTreeCursor,
    GameTreeNavigationError,
    VariationPath,
    VariationStep,
    resolve_line,
    validate_cursor,
)
from .pgn_roundtrip import parse_pgn_text
from .pgn_workspace import PgnWorkspace


class GameTreeEditorCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    INVALID_MOVE = "invalid_move"
    ILLEGAL_TREE = "illegal_tree"
    NO_MOVE = "no_move"
    NO_VARIATION_POINT = "no_variation_point"
    INVALID_METADATA = "invalid_metadata"
    INVALID_ANNOTATION = "invalid_annotation"
    HISTORY_EMPTY = "history_empty"
    CURSOR = "cursor"
    GRAPH_NODE_LIMIT = "graph_node_limit"


class GameTreeEditorError(ValueError):
    def __init__(self, message: str, *, code: GameTreeEditorCode) -> None:
        super().__init__(message)
        self.code = GameTreeEditorCode(code)


class GameTreeEditorOperation(str, Enum):
    ADD_MOVE = "add_move"
    CREATE_VARIATION = "create_variation"
    DELETE_MOVE = "delete_move"
    TRUNCATE_CONTINUATION = "truncate_continuation"
    REPLACE_CONTINUATION = "replace_continuation"


@dataclass(frozen=True, slots=True)
class EditorCursorRemap:
    before: GameTreeCursor
    after: GameTreeCursor | None


@dataclass(frozen=True, slots=True)
class GameTreeEditorMutation:
    game: PgnGame
    operation: GameTreeEditorOperation
    cursor_remap: tuple[EditorCursorRemap, ...]
    inserted_path: VariationPath | None = None

    def remap_cursor(self, cursor: GameTreeCursor) -> GameTreeCursor | None:
        if not isinstance(cursor, GameTreeCursor):
            raise TypeError("cursor must be a GameTreeCursor")
        for entry in self.cursor_remap:
            if entry.before == cursor:
                return entry.after
        raise GameTreeEditorError(
            "cursor was not valid in the source GameTree",
            code=GameTreeEditorCode.CURSOR,
        )


@dataclass(frozen=True, slots=True)
class _HistorySnapshot:
    text: str
    selected_game_index: int
    cursor: GameTreeCursor


@dataclass(frozen=True, slots=True)
class _LineRecord:
    path: VariationPath
    line: VariationLine


def _editor_error(message: str, code: GameTreeEditorCode) -> GameTreeEditorError:
    return GameTreeEditorError(message, code=code)


def _start_board(game: PgnGame) -> Board:
    if game.tags.get("SetUp") == "1":
        fen = game.tags.get("FEN")
        if not isinstance(fen, str) or not fen.strip():
            raise _editor_error("SetUp=1 requires a valid FEN", GameTreeEditorCode.ILLEGAL_TREE)
        try:
            return Board(fen)
        except Exception as exc:
            raise _editor_error("game start position is invalid", GameTreeEditorCode.ILLEGAL_TREE) from exc
    return Board(Board.START)


def _push_existing(board: Board, node: MoveNode) -> None:
    try:
        board.push_text(node.san)
    except Exception as exc:
        raise _editor_error(
            "existing GameTree contains a move that is illegal in canonical chess state",
            GameTreeEditorCode.ILLEGAL_TREE,
        ) from exc


def board_at_cursor(game: PgnGame, cursor: GameTreeCursor) -> Board:
    """Return a private canonical Board for the exact structural cursor."""

    try:
        validate_cursor(game, cursor)
    except (TypeError, GameTreeNavigationError) as exc:
        raise _editor_error("cursor is invalid", GameTreeEditorCode.CURSOR) from exc

    board = _start_board(game)
    line = game.line
    for step in cursor.line_path:
        if step.parent_move_index >= len(line.moves):
            raise _editor_error("cursor path is invalid", GameTreeEditorCode.CURSOR)
        for move_index in range(step.parent_move_index):
            _push_existing(board, line.moves[move_index])
        owner = line.moves[step.parent_move_index]
        if step.variation_index >= len(owner.variations):
            raise _editor_error("cursor path is invalid", GameTreeEditorCode.CURSOR)
        line = owner.variations[step.variation_index]

    for move_index in range(cursor.next_move_index):
        _push_existing(board, line.moves[move_index])
    return board


def _move_number(board: Board) -> str:
    return f"{board.fullmove}." if board.turn == "w" else f"{board.fullmove}..."


def _canonical_nodes(board: Board, moves: Iterable[str]) -> list[MoveNode]:
    if isinstance(moves, (str, bytes)):
        raise _editor_error("move sequence must be an iterable of move strings", GameTreeEditorCode.INVALID_INPUT)
    try:
        snapshot = tuple(moves)
    except TypeError as exc:
        raise _editor_error("move sequence must be iterable", GameTreeEditorCode.INVALID_INPUT) from exc
    if not snapshot:
        raise _editor_error("move sequence must contain at least one move", GameTreeEditorCode.INVALID_INPUT)
    out: list[MoveNode] = []
    current = board.clone()
    for raw in snapshot:
        if not isinstance(raw, str) or not raw.strip() or raw != raw.strip():
            raise _editor_error("move must be non-empty text", GameTreeEditorCode.INVALID_MOVE)
        number = _move_number(current)
        try:
            canonical = current.push_text(raw)
        except Exception as exc:
            raise _editor_error("move is illegal in the target position", GameTreeEditorCode.INVALID_MOVE) from exc
        out.append(MoveNode(canonical, move_number=number))
    return out


def _require_legal(game: PgnGame) -> None:
    report = validate_game_legality(game)
    if not report.complete:
        raise _editor_error("edit would create an illegal GameTree", GameTreeEditorCode.ILLEGAL_TREE)


def _collect_lines(root: VariationLine) -> list[_LineRecord]:
    out: list[_LineRecord] = []
    stack: list[tuple[VariationPath, VariationLine]] = [((), root)]
    seen: set[int] = set()
    while stack:
        path, line = stack.pop()
        if id(line) in seen:
            raise _editor_error("GameTree reuses a variation line", GameTreeEditorCode.ILLEGAL_TREE)
        seen.add(id(line))
        out.append(_LineRecord(path, line))
        if len(out) > MAX_TREE_NODES:
            raise _editor_error("GameTree exceeds the editor node limit", GameTreeEditorCode.GRAPH_NODE_LIMIT)
        for move_index in range(len(line.moves) - 1, -1, -1):
            move = line.moves[move_index]
            for variation_index in range(len(move.variations) - 1, -1, -1):
                stack.append((path + (VariationStep(move_index, variation_index),), move.variations[variation_index]))
    return out


def _new_line_paths(root: VariationLine) -> dict[int, VariationPath]:
    return {id(record.line): record.path for record in _collect_lines(root)}


def _remap_after_clone(
    records: list[_LineRecord],
    memo: dict[int, object],
    edited: PgnGame,
    target_source: VariationLine | None = None,
    target_mapper=None,
) -> tuple[EditorCursorRemap, ...]:
    paths = _new_line_paths(edited.line)
    entries: list[EditorCursorRemap] = []
    for record in records:
        cloned = memo.get(id(record.line))
        new_path = paths.get(id(cloned)) if cloned is not None else None
        for next_index in range(len(record.line.moves) + 1):
            before = GameTreeCursor(record.path, next_index)
            if record.line is target_source and target_mapper is not None:
                after = target_mapper(next_index, new_path)
            elif new_path is None:
                after = None
            else:
                after = GameTreeCursor(new_path, next_index)
            entries.append(EditorCursorRemap(before, after))
            if len(entries) > MAX_TREE_NODES:
                raise _editor_error("cursor remap exceeds the editor node limit", GameTreeEditorCode.GRAPH_NODE_LIMIT)
    return tuple(entries)


class CanonicalGameTreeEditor(PgnWorkspace):
    """Professional mutation/history façade over the existing canonical workspace."""

    HISTORY_LIMIT = 256

    def __init__(self, games: Iterable[PgnGame]) -> None:
        super().__init__(games)
        self._undo_stack: list[_HistorySnapshot] = []
        self._redo_stack: list[_HistorySnapshot] = []

    @classmethod
    def from_text(cls, text: object) -> "CanonicalGameTreeEditor":
        workspace = PgnWorkspace.from_text(text)
        return cls(workspace.games())

    @classmethod
    def from_bytes(cls, data: object) -> "CanonicalGameTreeEditor":
        workspace = PgnWorkspace.from_bytes(data)
        return cls(workspace.games())

    def _history_snapshot(self) -> _HistorySnapshot:
        return _HistorySnapshot(self.to_text(), self.selected_game_index, self.cursor)

    def _commit_current_game(self, game: PgnGame, *, cursor: GameTreeCursor | None = None):
        before = self._history_snapshot() if hasattr(self, "_undo_stack") else None
        view = super()._commit_current_game(game, cursor=cursor)
        if before is not None:
            self._undo_stack.append(before)
            if len(self._undo_stack) > self.HISTORY_LIMIT:
                del self._undo_stack[0]
            self._redo_stack.clear()
        return view

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def _restore_history(self, snapshot: _HistorySnapshot):
        try:
            games = list(parse_pgn_text(snapshot.text, strict=True))
            game = games[snapshot.selected_game_index]
            validate_cursor(game, snapshot.cursor)
        except Exception as exc:
            raise _editor_error("editor history snapshot is invalid", GameTreeEditorCode.ILLEGAL_TREE) from exc
        self._games = games
        self._selected_game_index = snapshot.selected_game_index
        self._cursor = snapshot.cursor
        self._content_revision += 1
        self._dirty = self.content_digest != self._baseline_digest
        return self.view()

    def undo(self):
        if not self._undo_stack:
            raise _editor_error("nothing to undo", GameTreeEditorCode.HISTORY_EMPTY)
        current = self._history_snapshot()
        target = self._undo_stack[-1]
        view = self._restore_history(target)
        self._undo_stack.pop()
        self._redo_stack.append(current)
        return view

    def redo(self):
        if not self._redo_stack:
            raise _editor_error("nothing to redo", GameTreeEditorCode.HISTORY_EMPTY)
        current = self._history_snapshot()
        target = self._redo_stack[-1]
        view = self._restore_history(target)
        self._redo_stack.pop()
        self._undo_stack.append(current)
        return view

    def current_fen(self) -> str:
        return board_at_cursor(self._current_game_ref(), self.cursor).fen()

    def add_variation(self, target: VariationInsertTarget, variation: VariationLine) -> VariationInsertResult:
        result = _add_variation(self._current_game_ref(), target, variation)
        _require_legal(result.game)
        self._commit_current_game(result.game, cursor=result.remap_cursor(self.cursor))
        return result

    def reorder_variation(self, target: VariationEditTarget, new_index: int) -> GameTreeEditResult:
        result = _reorder_variation(self._current_game_ref(), target, new_index)
        _require_legal(result.game)
        remapped = result.remap_cursor(self.cursor)
        if remapped is None:
            raise _editor_error("reorder removed the active cursor", GameTreeEditorCode.CURSOR)
        self._commit_current_game(result.game, cursor=remapped)
        return result

    def delete_variation(self, target: VariationEditTarget) -> GameTreeEditResult:
        result = _delete_variation(self._current_game_ref(), target)
        _require_legal(result.game)
        remapped = result.remap_cursor(self.cursor)
        if remapped is None:
            remapped = GameTreeCursor(target.parent_path, target.parent_move_index + 1)
        self._commit_current_game(result.game, cursor=remapped)
        return result

    def promote_variation(self, target: VariationEditTarget) -> GameTreeEditResult:
        result = _promote_variation(self._current_game_ref(), target)
        _require_legal(result.game)
        remapped = result.remap_cursor(self.cursor)
        if remapped is None:
            raise _editor_error("promotion removed the active cursor", GameTreeEditorCode.CURSOR)
        self._commit_current_game(result.game, cursor=remapped)
        return result

    def add_move(self, san: str) -> GameTreeEditorMutation:
        game = self._current_game_ref()
        source_cursor = self.cursor
        source_line = resolve_line(game, source_cursor.line_path)
        nodes = _canonical_nodes(board_at_cursor(game, source_cursor), (san,))
        if source_cursor.next_move_index < len(source_line.moves):
            target = variation_insert_target(game, source_cursor.line_path, source_cursor.next_move_index)
            inserted = _add_variation(game, target, VariationLine(moves=nodes))
            _require_legal(inserted.game)
            mapped = tuple(EditorCursorRemap(entry.before, entry.after) for entry in inserted.cursor_remap)
            active = GameTreeCursor(inserted.inserted_path, 1)
            self._commit_current_game(inserted.game, cursor=active)
            return GameTreeEditorMutation(
                inserted.game,
                GameTreeEditorOperation.ADD_MOVE,
                mapped,
                inserted.inserted_path,
            )

        records = _collect_lines(game.line)
        memo: dict[int, object] = {}
        edited = deepcopy(game, memo)
        line = resolve_line(edited, source_cursor.line_path)
        line.moves.extend(deepcopy(nodes))
        _require_legal(edited)
        remap = _remap_after_clone(records, memo, edited)
        self._commit_current_game(
            edited,
            cursor=GameTreeCursor(source_cursor.line_path, source_cursor.next_move_index + 1),
        )
        return GameTreeEditorMutation(edited, GameTreeEditorOperation.ADD_MOVE, remap)

    def create_variation(
        self,
        moves: Iterable[str],
        *,
        insert_index: int | None = None,
    ) -> GameTreeEditorMutation:
        game = self._current_game_ref()
        cursor = self.cursor
        line = resolve_line(game, cursor.line_path)
        if cursor.next_move_index >= len(line.moves):
            raise _editor_error(
                "a variation requires an existing continuation to branch from",
                GameTreeEditorCode.NO_VARIATION_POINT,
            )
        nodes = _canonical_nodes(board_at_cursor(game, cursor), moves)
        target = variation_insert_target(game, cursor.line_path, cursor.next_move_index, insert_index)
        result = _add_variation(game, target, VariationLine(moves=nodes))
        _require_legal(result.game)
        active = GameTreeCursor(result.inserted_path, len(nodes))
        self._commit_current_game(result.game, cursor=active)
        return GameTreeEditorMutation(
            result.game,
            GameTreeEditorOperation.CREATE_VARIATION,
            tuple(EditorCursorRemap(entry.before, entry.after) for entry in result.cursor_remap),
            result.inserted_path,
        )

    def delete_move(self) -> GameTreeEditorMutation:
        game = self._current_game_ref()
        cursor = self.cursor
        source_line = resolve_line(game, cursor.line_path)
        cut = cursor.next_move_index
        if cut >= len(source_line.moves):
            raise _editor_error("there is no move at the cursor", GameTreeEditorCode.NO_MOVE)

        records = _collect_lines(game.line)
        memo: dict[int, object] = {}
        edited = deepcopy(game, memo)
        cloned_line = memo[id(source_line)]
        assert isinstance(cloned_line, VariationLine)
        cloned_line.moves.pop(cut)
        _require_legal(edited)

        def mapper(index: int, new_path: VariationPath | None):
            if new_path is None:
                return None
            return GameTreeCursor(new_path, index if index <= cut else index - 1)

        remap = _remap_after_clone(records, memo, edited, source_line, mapper)
        active = GameTreeCursor(cursor.line_path, cut)
        self._commit_current_game(edited, cursor=active)
        return GameTreeEditorMutation(edited, GameTreeEditorOperation.DELETE_MOVE, remap)

    def truncate_continuation(self) -> GameTreeEditorMutation:
        game = self._current_game_ref()
        cursor = self.cursor
        source_line = resolve_line(game, cursor.line_path)
        cut = cursor.next_move_index
        if cut >= len(source_line.moves):
            raise _editor_error("there is no continuation to truncate", GameTreeEditorCode.NO_MOVE)

        records = _collect_lines(game.line)
        memo: dict[int, object] = {}
        edited = deepcopy(game, memo)
        cloned_line = memo[id(source_line)]
        assert isinstance(cloned_line, VariationLine)
        del cloned_line.moves[cut:]
        _require_legal(edited)

        def mapper(index: int, new_path: VariationPath | None):
            if new_path is None or index > cut:
                return None
            return GameTreeCursor(new_path, index)

        remap = _remap_after_clone(records, memo, edited, source_line, mapper)
        self._commit_current_game(edited, cursor=GameTreeCursor(cursor.line_path, cut))
        return GameTreeEditorMutation(edited, GameTreeEditorOperation.TRUNCATE_CONTINUATION, remap)

    def replace_continuation(self, moves: Iterable[str]) -> GameTreeEditorMutation:
        game = self._current_game_ref()
        cursor = self.cursor
        source_line = resolve_line(game, cursor.line_path)
        cut = cursor.next_move_index
        nodes = _canonical_nodes(board_at_cursor(game, cursor), moves)

        records = _collect_lines(game.line)
        memo: dict[int, object] = {}
        edited = deepcopy(game, memo)
        cloned_line = memo[id(source_line)]
        assert isinstance(cloned_line, VariationLine)
        cloned_line.moves = cloned_line.moves[:cut] + deepcopy(nodes)
        _require_legal(edited)

        def mapper(index: int, new_path: VariationPath | None):
            if new_path is None or index > cut:
                return None
            return GameTreeCursor(new_path, index)

        remap = _remap_after_clone(records, memo, edited, source_line, mapper)
        active = GameTreeCursor(cursor.line_path, cut + len(nodes))
        self._commit_current_game(edited, cursor=active)
        return GameTreeEditorMutation(edited, GameTreeEditorOperation.REPLACE_CONTINUATION, remap)

    def edit_move_comments(
        self,
        line_path: VariationPath,
        move_index: int,
        *,
        comments_before: Iterable[Comment] | None = None,
        comments_after: Iterable[Comment] | None = None,
    ) -> AnnotationEditResult:
        if comments_before is None and comments_after is None:
            raise _editor_error("at least one comment field must be supplied", GameTreeEditorCode.INVALID_ANNOTATION)
        try:
            patch = MoveAnnotationPatch(
                comments_before=None if comments_before is None else tuple(comments_before),
                comments_after=None if comments_after is None else tuple(comments_after),
            )
            game = self._current_game_ref()
            target = move_annotation_target(game, line_path, move_index)
            result = _edit_move_annotations(game, target, patch)
        except (TypeError, ValueError) as exc:
            raise _editor_error("invalid move comment edit", GameTreeEditorCode.INVALID_ANNOTATION) from exc
        self._commit_current_game(result.game)
        return result

    def edit_line_comments(
        self,
        line_path: VariationPath,
        *,
        leading_comments: Iterable[Comment] | None = None,
        trailing_comments: Iterable[Comment] | None = None,
    ) -> AnnotationEditResult:
        if leading_comments is None and trailing_comments is None:
            raise _editor_error("at least one comment field must be supplied", GameTreeEditorCode.INVALID_ANNOTATION)
        try:
            patch = LineAnnotationPatch(
                leading_comments=None if leading_comments is None else tuple(leading_comments),
                trailing_comments=None if trailing_comments is None else tuple(trailing_comments),
            )
            game = self._current_game_ref()
            target = line_annotation_target(game, line_path)
            result = _edit_line_annotations(game, target, patch)
        except (TypeError, ValueError) as exc:
            raise _editor_error("invalid line comment edit", GameTreeEditorCode.INVALID_ANNOTATION) from exc
        self._commit_current_game(result.game)
        return result

    def add_nag(self, line_path: VariationPath, move_index: int, nag: str) -> AnnotationEditResult:
        game = self._current_game_ref()
        try:
            target = move_annotation_target(game, line_path, move_index)
            move = resolve_line(game, line_path).moves[move_index]
            if nag in move.nags:
                raise _editor_error("NAG is already present", GameTreeEditorCode.INVALID_ANNOTATION)
            result = _edit_move_annotations(
                game,
                target,
                MoveAnnotationPatch(nags=tuple(move.nags) + (nag,)),
            )
        except GameTreeEditorError:
            raise
        except (TypeError, ValueError) as exc:
            raise _editor_error("invalid NAG", GameTreeEditorCode.INVALID_ANNOTATION) from exc
        self._commit_current_game(result.game)
        return result

    def remove_nag(self, line_path: VariationPath, move_index: int, nag: str) -> AnnotationEditResult:
        game = self._current_game_ref()
        try:
            target = move_annotation_target(game, line_path, move_index)
            move = resolve_line(game, line_path).moves[move_index]
            if nag not in move.nags:
                raise _editor_error("NAG is not present", GameTreeEditorCode.INVALID_ANNOTATION)
            result = _edit_move_annotations(
                game,
                target,
                MoveAnnotationPatch(nags=tuple(item for item in move.nags if item != nag)),
            )
        except GameTreeEditorError:
            raise
        except (TypeError, ValueError) as exc:
            raise _editor_error("invalid NAG removal", GameTreeEditorCode.INVALID_ANNOTATION) from exc
        self._commit_current_game(result.game)
        return result

    def edit_metadata(self, patch: Mapping[str, str | None]):
        if not isinstance(patch, Mapping) or not patch:
            raise _editor_error("metadata patch must be a non-empty mapping", GameTreeEditorCode.INVALID_METADATA)
        edited = deepcopy(self._current_game_ref())
        touches_start = False
        try:
            for key, value in patch.items():
                if not isinstance(key, str) or TAG_NAME_RE.fullmatch(key) is None:
                    raise ValueError("invalid tag name")
                if value is not None and (not isinstance(value, str) or "\r" in value or "\n" in value):
                    raise ValueError("invalid tag value")
                if key in {"SetUp", "FEN"}:
                    touches_start = True
                if key == "Result":
                    if value is None:
                        edited.tags.pop("Result", None)
                        edited.line.result = "*"
                    else:
                        if value not in RESULTS:
                            raise ValueError("invalid result")
                        edited.tags["Result"] = value
                        edited.line.result = value
                    continue
                if value is None:
                    edited.tags.pop(key, None)
                else:
                    edited.tags[key] = value

            if edited.tags.get("SetUp") == "1":
                fen = edited.tags.get("FEN")
                if not isinstance(fen, str) or not fen.strip():
                    raise ValueError("SetUp=1 requires FEN")
            elif "FEN" in edited.tags:
                raise ValueError("FEN requires SetUp=1 in an editable canonical game")
            if touches_start:
                _require_legal(edited)
        except GameTreeEditorError:
            raise
        except (TypeError, ValueError) as exc:
            raise _editor_error("invalid PGN metadata edit", GameTreeEditorCode.INVALID_METADATA) from exc

        self._commit_current_game(edited)
        return self.view()

    def semantic_record_digest(self) -> str:
        return identity_for_game(self._current_game_ref()).record_digest
