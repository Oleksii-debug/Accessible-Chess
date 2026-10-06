"""V2 command composition for the canonical PGN workspace and selection writer."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path

from .gametree import Comment, PgnGame, VariationLine, serialize_game
from .gametree_annotations import LineAnnotationPatch, LineAnnotationTarget, MoveAnnotationPatch, MoveAnnotationTarget
from .gametree_editing import VariationEditTarget
from .gametree_insertion import variation_insert_target
from .gametree_legality import validate_game_legality
from .pgn_roundtrip import parse_pgn_text
from .gametree_navigation import GameTreeCursor, MoveAddress, VariationStep, resolve_line, validate_cursor
from .search_policy import normalize_search_term, normalize_search_text, search_fold
from .pgn_document import PgnDocumentSession
from .pgn_service import export_game_atomic
from .version2_windows_pgn_export import PgnSelectionExportRequest


_TARGET_FIELDS = {"game_index", "line_path", "move_index", "expected_record_digest", "content_revision"}
_NAVIGATION_TARGET_FIELDS = _TARGET_FIELDS | {"expected_content_digest"}


@dataclass(frozen=True, slots=True)
class _PgnNavigationTarget:
    """Navigation identity that also permits the valid main-line root cursor.

    ``PgnSelectionExportRequest`` deliberately rejects a root cursor because
    exporting a selection requires a concrete game-tree item.  Previous/next
    game navigation has a different contract: the main-line root is a normal
    workspace state.  Keep that exception private to game navigation instead
    of weakening edit/copy/export selection semantics.
    """

    game_index: int
    line_path: tuple[tuple[int, int], ...]
    move_index: int | None
    expected_record_digest: str
    expected_content_digest: str
    content_revision: int

    def __post_init__(self) -> None:
        if type(self.game_index) is not int or self.game_index < 0:
            raise ValueError("PGN navigation game index is invalid")
        if type(self.content_revision) is not int or self.content_revision < 0:
            raise ValueError("PGN navigation content revision is invalid")
        if self.move_index is not None and (
            type(self.move_index) is not int or self.move_index < 0
        ):
            raise ValueError("PGN navigation move index is invalid")
        if type(self.line_path) is not tuple:
            raise TypeError("PGN navigation line path must be a tuple")
        for step in self.line_path:
            if (
                type(step) is not tuple
                or len(step) != 2
                or type(step[0]) is not int
                or type(step[1]) is not int
                or step[0] < 0
                or step[1] < 0
            ):
                raise ValueError("PGN navigation line path is invalid")
        digest = self.expected_record_digest
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("PGN navigation record digest is invalid")
        document_digest = self.expected_content_digest
        if (
            type(document_digest) is not str
            or len(document_digest) != 64
            or any(character not in "0123456789abcdef" for character in document_digest)
        ):
            raise ValueError("PGN navigation content digest is invalid")

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "_PgnNavigationTarget":
        if not isinstance(payload, Mapping):
            raise TypeError("PGN navigation target must be a mapping")
        if set(payload) != _NAVIGATION_TARGET_FIELDS:
            raise ValueError("PGN navigation target contains missing or untrusted fields")
        line_path = payload["line_path"]
        if type(line_path) is not tuple:
            raise TypeError("PGN navigation line path must be a tuple")
        return cls(
            game_index=payload["game_index"],  # type: ignore[arg-type]
            line_path=line_path,  # type: ignore[arg-type]
            move_index=payload["move_index"],  # type: ignore[arg-type]
            expected_record_digest=payload["expected_record_digest"],  # type: ignore[arg-type]
            expected_content_digest=payload["expected_content_digest"],  # type: ignore[arg-type]
            content_revision=payload["content_revision"],  # type: ignore[arg-type]
        )


class Version2PgnCommands:
    def __init__(self, get_session, *, copy_text=lambda _: None):
        self._get_session = get_session
        self._copy_text = copy_text

    def _session(self):
        session = self._get_session()
        if not isinstance(session, PgnDocumentSession):
            raise ValueError("no PGN document")
        return session

    def _target(self, payload, *, require_current=True, workspace=None, allow_root=False):
        target_fields = _NAVIGATION_TARGET_FIELDS if allow_root else _TARGET_FIELDS
        target_payload = {key: payload[key] for key in target_fields}
        if allow_root:
            request = _PgnNavigationTarget.from_payload(target_payload)
        else:
            request = PgnSelectionExportRequest.from_payload(target_payload)
        if workspace is None:
            workspace = self._session().workspace
        view = workspace.view()
        if allow_root and request.expected_content_digest != view.content_digest:
            raise ValueError("PGN document is stale")
        if not allow_root and "expected_content_digest" in payload:
            expected_content_digest = payload["expected_content_digest"]
            if (
                type(expected_content_digest) is not str
                or len(expected_content_digest) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in expected_content_digest
                )
            ):
                raise ValueError("PGN command content digest is invalid")
            if expected_content_digest != view.content_digest:
                raise ValueError("PGN document is stale")
        if (request.game_index, request.content_revision, request.expected_record_digest) != (
            view.selected_game_index, view.content_revision, view.current_record_digest
        ):
            raise ValueError("PGN selection is stale")
        path = tuple(VariationStep(*step) for step in request.line_path)
        cursor = GameTreeCursor(path, 0 if request.move_index is None else request.move_index + 1)
        validate_cursor(workspace.current_game(), cursor)
        if require_current and cursor != workspace.cursor:
            raise ValueError("PGN cursor is stale")
        return request, cursor

    def _selection_game(self, request: PgnSelectionExportRequest, workspace) -> PgnGame:
        request, cursor = self._target(asdict(request), workspace=workspace)
        game = workspace.current_game()
        if not cursor.line_path:
            return game
        # A RAV begins before its owning move. The canonical legality projection
        # supplies that exact FEN; no move replay or chess rules are copied here.
        step = cursor.line_path[-1]
        address = MoveAddress(cursor.line_path[:-1], step.parent_move_index)
        report = validate_game_legality(game)
        owner = next((move for move in report.moves if move.address == address), None)
        if owner is None:
            raise ValueError("variation has no validated starting position")
        line = deepcopy(resolve_line(game, cursor.line_path))
        line.result = line.result or "*"
        tags = dict(game.tags)
        tags.update(SetUp="1", FEN=owner.fen_before, Result=line.result)
        return PgnGame(tags=tags, line=line, source_index=0)

    def selection_game(self, request: PgnSelectionExportRequest) -> PgnGame:
        workspace = self._session().workspace
        return self._selection_game(request, workspace)

    @staticmethod
    def _line_search_targets(line: VariationLine, path: tuple[VariationStep, ...]):
        line_text = " ".join(
            [comment.text for comment in line.leading_comments]
            + [comment.text for comment in line.trailing_comments]
        )
        if line_text.strip():
            yield GameTreeCursor(path, 0), line_text
        for index, move in enumerate(line.moves):
            text = " ".join(
                [move.san]
                + list(move.nags)
                + [comment.text for comment in move.comments_before]
                + [comment.text for comment in move.comments_after]
            )
            yield GameTreeCursor(path, index + 1), text
            for variation_index, variation in enumerate(move.variations):
                child_path = path + (VariationStep(index, variation_index),)
                yield from Version2PgnCommands._line_search_targets(variation, child_path)

    @staticmethod
    def _search_pgn(workspace, query: str):
        normalized = normalize_search_term(query, name="PGN search")
        if normalized is None:
            raise ValueError("PGN search text must not be empty")
        needle = search_fold(normalized)
        assert needle is not None
        games = workspace.games()
        current_game = workspace.selected_game_index
        current_cursor = workspace.cursor
        targets = []
        for game_index, game in enumerate(games):
            tag_text = " ".join(
                f"{name} {value}" for name, value in game.tags.items()
            )
            targets.append((game_index, GameTreeCursor(), tag_text))
            for cursor, text in Version2PgnCommands._line_search_targets(game.line, ()):
                targets.append((game_index, cursor, text))
        if not targets:
            raise ValueError("PGN contains no searchable content")
        current_key = (current_game, current_cursor)
        start = -1
        for index, (game_index, cursor, _text) in enumerate(targets):
            if (game_index, cursor) == current_key:
                start = index
        ordered = targets[start + 1 :] + targets[: start + 1]
        for game_index, cursor, text in ordered:
            folded = search_fold(normalize_search_text(text))
            if folded is not None and needle in folded:
                return workspace.select_game_cursor(game_index, cursor)
        raise ValueError("PGN search found no match")

    @staticmethod
    def _selected_move_origin_fen(workspace, cursor: GameTreeCursor) -> str:
        if cursor.next_move_index <= 0:
            raise ValueError("select a PGN move first")
        report = validate_game_legality(workspace.current_game())
        address = MoveAddress(cursor.line_path, cursor.next_move_index - 1)
        move = next((item for item in report.moves if item.address == address), None)
        if move is None:
            raise ValueError("selected PGN move has no canonical position")
        return move.fen_before

    @staticmethod
    def _variation_from_text(text: str, *, origin_fen: str) -> VariationLine:
        if type(text) is not str or not text.strip() or len(text) > 8192 or "\x00" in text:
            raise ValueError("invalid PGN variation text")
        fields = origin_fen.split()
        if len(fields) != 6 or fields[1] not in {"w", "b"}:
            raise ValueError("variation origin is not canonical FEN")
        try:
            fullmove = int(fields[5])
        except ValueError as exc:
            raise ValueError("variation origin has invalid move counter") from exc
        prefix = f"{fullmove}." if fields[1] == "w" else f"{fullmove}..."
        synthetic = (
            f'[SetUp "1"]\n[FEN "{origin_fen}"]\n[Result "*"]\n\n'
            f"{prefix} {text.strip()} *"
        )
        games = parse_pgn_text(synthetic, strict=True)
        if len(games) != 1 or not games[0].line.moves:
            raise ValueError("variation text contains no canonical moves")
        report = validate_game_legality(games[0])
        if not report.complete or report.issues:
            raise ValueError("variation contains an illegal or unsupported move")
        line = games[0].line
        line.result = None
        return line

    def current_fen(self) -> str:
        workspace = self._session().workspace
        cursor = workspace.cursor
        report = validate_game_legality(workspace.current_game())
        if cursor.next_move_index:
            address = MoveAddress(cursor.line_path, cursor.next_move_index - 1)
            move = next((item for item in report.moves if item.address == address), None)
            if move is None: raise ValueError("selected PGN move is not legal")
            return move.fen_after
        if cursor.line_path:
            step = cursor.line_path[-1]
            address = MoveAddress(cursor.line_path[:-1], step.parent_move_index)
            owner = next((item for item in report.moves if item.address == address), None)
            if owner is None: raise ValueError("PGN variation has no legal origin")
            return owner.fen_before
        if report.start_fen is None: raise ValueError("PGN has no legal start")
        return report.start_fen

    def export_selected(self, request: PgnSelectionExportRequest, destination: Path):
        session = self._session()
        game = self._selection_game(request, session.workspace)
        expected = session.expected_destination_sha256(destination)
        return export_game_atomic(destination, game, overwrite=expected is not None, expected_sha256=expected)

    def __call__(self, action_id, payload):
        session = self._session()
        workspace = session.workspace
        if action_id in {"pgn.previous_game", "pgn.next_game"}:
            if payload:
                if set(payload) != _NAVIGATION_TARGET_FIELDS:
                    raise ValueError("invalid PGN game navigation payload")
                self._target(
                    payload,
                    require_current=True,
                    workspace=workspace,
                    allow_root=True,
                )
            return workspace.previous_game() if action_id.endswith("previous_game") else workspace.next_game()
        if action_id == "pgn.search":
            if set(payload) not in ({* _TARGET_FIELDS, "text"}, {* _TARGET_FIELDS, "expected_content_digest", "text"}):
                raise ValueError("invalid PGN search payload")
            request, _cursor = self._target(payload, require_current=True, workspace=workspace)
            text = payload.get("text", "")
            if type(text) is not str:
                raise ValueError("invalid PGN search text")
            return self._search_pgn(workspace, text)
        navigation = {"pgn.select_item", "pgn.previous_item", "pgn.next_item", "pgn.parent_variation"}
        allowed = set(_TARGET_FIELDS)
        if action_id in {"pgn.comment_edit", "pgn.nag_edit", "pgn.variation_add"}:
            allowed.add("text")
        if action_id in {"pgn.variation_delete", "pgn.variation_promote"}:
            allowed.update({"parent_path", "parent_move_index", "variation_index"})
        payload_fields = set(payload)
        if (
            payload_fields != allowed
            and payload_fields != allowed | {"expected_content_digest"}
        ):
            raise ValueError("invalid PGN command payload")
        request, cursor = self._target(
            payload,
            require_current=action_id not in navigation,
            workspace=workspace,
        )
        if action_id in navigation:
            return workspace.set_cursor(cursor)
        if action_id in {"pgn.comment_edit", "pgn.comment_delete"}:
            text = payload.get("text", "")
            if type(text) is not str or len(text) > 8000:
                raise ValueError("invalid PGN comment")
            comments = (Comment(text),) if text.strip() else ()
            if request.move_index is None:
                return workspace.edit_line_annotations(
                    LineAnnotationTarget(cursor.line_path, request.expected_record_digest),
                    LineAnnotationPatch(leading_comments=comments),
                )
            return workspace.edit_move_annotations(
                MoveAnnotationTarget(cursor.line_path, request.move_index, request.expected_record_digest),
                MoveAnnotationPatch(comments_before=(), comments_after=comments),
            )
        if action_id == "pgn.nag_edit":
            if request.move_index is None:
                raise ValueError("NAG editing requires a selected move")
            text = payload.get("text", "")
            if type(text) is not str or len(text) > 512 or "\x00" in text:
                raise ValueError("invalid PGN NAG text")
            tokens = tuple(token for token in text.split() if token)
            if len(tokens) > 64:
                raise ValueError("too many PGN NAG annotations")
            return workspace.edit_move_annotations(
                MoveAnnotationTarget(cursor.line_path, request.move_index, request.expected_record_digest),
                MoveAnnotationPatch(nags=tokens),
            )
        if action_id == "pgn.variation_add":
            if request.move_index is None:
                raise ValueError("variation creation requires a selected move")
            text = payload.get("text", "")
            origin_fen = self._selected_move_origin_fen(workspace, cursor)
            variation = self._variation_from_text(text, origin_fen=origin_fen)
            target = variation_insert_target(
                workspace.current_game(),
                cursor.line_path,
                request.move_index,
            )
            return workspace.add_variation(target, variation)
        if action_id in {"pgn.variation_delete", "pgn.variation_promote"}:
            parent = tuple(VariationStep(*step) for step in payload["parent_path"])
            target = VariationEditTarget(parent, payload["parent_move_index"], payload["variation_index"], request.expected_record_digest)
            if target.child_path != cursor.line_path:
                raise ValueError("variation selection changed")
            return workspace.delete_variation(target) if action_id.endswith("delete") else workspace.promote_variation(target)
        if action_id == "pgn.copy_selection":
            self._copy_text(serialize_game(self._selection_game(request, workspace)))
            return None
        raise ValueError("unsupported PGN command")
