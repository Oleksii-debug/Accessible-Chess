"""V2 command composition for the canonical PGN workspace and selection writer."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from .gametree import Comment, PgnGame, serialize_game
from .gametree_annotations import LineAnnotationPatch, LineAnnotationTarget, MoveAnnotationPatch, MoveAnnotationTarget
from .gametree_editing import VariationEditTarget
from .gametree_legality import validate_game_legality
from .gametree_navigation import GameTreeCursor, MoveAddress, VariationStep, resolve_line, validate_cursor
from .pgn_document import PgnDocumentSession
from .pgn_service import export_game_atomic
from .version2_windows_pgn_export import PgnSelectionExportRequest


_TARGET_FIELDS = {"game_index", "line_path", "move_index", "expected_record_digest", "content_revision"}


class Version2PgnCommands:
    def __init__(self, get_session, *, copy_text=lambda _: None):
        self._get_session = get_session
        self._copy_text = copy_text

    def _session(self):
        session = self._get_session()
        if not isinstance(session, PgnDocumentSession):
            raise ValueError("no PGN document")
        return session

    def _target(self, payload, *, require_current=True):
        request = PgnSelectionExportRequest.from_payload({key: payload[key] for key in _TARGET_FIELDS})
        workspace = self._session().workspace
        view = workspace.view()
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

    def selection_game(self, request: PgnSelectionExportRequest) -> PgnGame:
        request, cursor = self._target(asdict(request))
        game = self._session().workspace.current_game()
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
        game = self.selection_game(request)
        expected = self._session().expected_destination_sha256(destination)
        return export_game_atomic(destination, game, overwrite=expected is not None, expected_sha256=expected)

    def __call__(self, action_id, payload):
        workspace = self._session().workspace
        if action_id in {"pgn.previous_game", "pgn.next_game"}:
            if payload:
                raise ValueError("game navigation accepts no payload")
            return workspace.previous_game() if action_id.endswith("previous_game") else workspace.next_game()
        navigation = {"pgn.select_item", "pgn.previous_item", "pgn.next_item", "pgn.parent_variation"}
        allowed = set(_TARGET_FIELDS)
        if action_id == "pgn.comment_edit": allowed.add("text")
        if action_id in {"pgn.variation_delete", "pgn.variation_promote"}:
            allowed.update({"parent_path", "parent_move_index", "variation_index"})
        if set(payload) != allowed:
            raise ValueError("invalid PGN command payload")
        request, cursor = self._target(payload, require_current=action_id not in navigation)
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
        if action_id in {"pgn.variation_delete", "pgn.variation_promote"}:
            parent = tuple(VariationStep(*step) for step in payload["parent_path"])
            target = VariationEditTarget(parent, payload["parent_move_index"], payload["variation_index"], request.expected_record_digest)
            if target.child_path != cursor.line_path:
                raise ValueError("variation selection changed")
            return workspace.delete_variation(target) if action_id.endswith("delete") else workspace.promote_variation(target)
        if action_id == "pgn.copy_selection":
            self._copy_text(serialize_game(self.selection_game(request)))
            return None
        raise ValueError("unsupported PGN command")
