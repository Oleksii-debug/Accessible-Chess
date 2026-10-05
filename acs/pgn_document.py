from __future__ import annotations

"""Professional file/session workflow for canonical PGN documents.

The document session composes the existing strict :mod:`pgn_workspace` and the
existing atomic :mod:`pgn_service` publication boundary.  It does not introduce
another GameTree, parser, serializer, legality engine, or filesystem writer.

A session can be opened from a real PGN, created as a new game, or populated
from pasted PGN text.  Save uses the fingerprint captured at open time and
therefore fails closed on an external modification.  Save As/export never
silently replace an existing destination: an explicit expected destination
fingerprint is required for overwrite.
"""

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from .chesscore import Board
from .gametree import PgnGame, RESULTS, VariationLine
from .gametree_navigation import GameTreeCursor, MAX_VARIATION_DEPTH, VariationStep
from .import_contract import SourceFingerprint, fingerprint
from .position_editor import PositionState
from .pgn_service import (
    PgnConcurrentWriteError,
    PgnOpenResult,
    _same_direct_path,
    _validated_expected_sha256,
    export_game_atomic,
    open_pgn,
    save_pgn_atomic,
)
from .pgn_workspace import PgnWorkspace, PgnWorkspaceError, PgnWorkspaceView


class PgnDocumentErrorCode(str, Enum):
    NO_SOURCE = "no_source"
    SOURCE_REQUIRES_SAVE_AS = "source_requires_save_as"
    RECOVERY_SOURCE_REQUIRES_DIFFERENT_DESTINATION = (
        "recovery_source_requires_different_destination"
    )
    DESTINATION_VERSION_REQUIRED = "destination_version_required"
    SAVE_COMMIT_FAILED = "save_commit_failed"
    INVALID_TAG = "invalid_tag"
    INVALID_RESULT = "invalid_result"
    INVALID_POSITION = "invalid_position"
    CONTEXT_STALE = "context_stale"


class PgnDocumentError(ValueError):
    def __init__(self, message: str, *, code: PgnDocumentErrorCode) -> None:
        super().__init__(message)
        self.code = PgnDocumentErrorCode(code)


@dataclass(frozen=True, slots=True)
class PgnDocumentContext:
    """Exact non-mutating return point for Engine/Board/other temporary views."""

    content_digest: str
    selected_game_index: int
    cursor: GameTreeCursor


@dataclass(frozen=True, slots=True)
class PgnDocumentView:
    source_path: str | None
    source_sha256: str | None
    game_count: int
    selected_game_index: int
    cursor: GameTreeCursor
    dirty: bool
    document_revision: int
    source_overwrite_safe: bool
    global_warnings: tuple[str, ...]


_STANDARD_TAGS = {
    "Event": "?",
    "Site": "?",
    "Date": "????.??.??",
    "Round": "?",
    "White": "?",
    "Black": "?",
    "Result": "*",
}

# These two tags jointly define chess state, not ordinary descriptive metadata.
# Allowing the generic tag editor to change only one of them can convert a
# valid custom-start game into a different standard-start game.  The canonical
# Position workflow owns atomic start-position changes.
_POSITION_TAGS = frozenset(("SetUp", "FEN"))


def _error(message: str, code: PgnDocumentErrorCode) -> PgnDocumentError:
    return PgnDocumentError(message, code=code)


def _passive_context_cursor(cursor: object) -> GameTreeCursor:
    """Detach one saved cursor without executing caller-controlled nested hooks."""

    if type(cursor) is not GameTreeCursor:
        raise _error(
            "saved PGN context cursor is not canonical",
            PgnDocumentErrorCode.CONTEXT_STALE,
        )
    line_path = cursor.line_path
    next_move_index = cursor.next_move_index
    if (
        type(line_path) is not tuple
        or len(line_path) > MAX_VARIATION_DEPTH
        or type(next_move_index) is not int
        or next_move_index < 0
    ):
        raise _error(
            "saved PGN context cursor is not canonical",
            PgnDocumentErrorCode.CONTEXT_STALE,
        )

    detached_steps: list[VariationStep] = []
    for step in line_path:
        if type(step) is not VariationStep:
            raise _error(
                "saved PGN context cursor is not canonical",
                PgnDocumentErrorCode.CONTEXT_STALE,
            )
        parent_move_index = step.parent_move_index
        variation_index = step.variation_index
        if (
            type(parent_move_index) is not int
            or parent_move_index < 0
            or type(variation_index) is not int
            or variation_index < 0
        ):
            raise _error(
                "saved PGN context cursor is not canonical",
                PgnDocumentErrorCode.CONTEXT_STALE,
            )
        detached_steps.append(
            VariationStep(
                parent_move_index=parent_move_index,
                variation_index=variation_index,
            )
        )
    return GameTreeCursor(
        line_path=tuple(detached_steps),
        next_move_index=next_move_index,
    )


def _passive_position_state(position: object) -> PositionState:
    """Re-detach a canonical position without executing tampered nested hooks."""

    if type(position) is not PositionState:
        raise _error(
            "PGN start position must be canonical PositionState",
            PgnDocumentErrorCode.INVALID_POSITION,
        )
    pieces = position.pieces
    turn = position.turn
    castling = position.castling
    en_passant = position.en_passant
    halfmove = position.halfmove
    fullmove = position.fullmove
    if (
        type(pieces) is not tuple
        or len(pieces) != 64
        or any(piece is not None and type(piece) is not str for piece in pieces)
        or type(turn) is not str
        or type(castling) is not str
        or type(en_passant) is not str
        or type(halfmove) is not int
        or type(fullmove) is not int
    ):
        raise _error(
            "PGN start position is not canonical",
            PgnDocumentErrorCode.INVALID_POSITION,
        )
    try:
        return PositionState(
            pieces=tuple(pieces),
            turn=turn,
            castling=castling,
            en_passant=en_passant,
            halfmove=halfmove,
            fullmove=fullmove,
        )
    except ValueError as exc:
        raise _error(
            "PGN start position is not valid",
            PgnDocumentErrorCode.INVALID_POSITION,
        ) from exc


def _passive_new_game_tags(tags: Mapping[str, str] | None) -> dict[str, str]:
    """Detach plain metadata without executing caller-defined mapping/text hooks."""

    if tags is None:
        return {}
    if type(tags) is not dict:
        raise _error(
            "PGN new-game tags must be a built-in dictionary of text",
            PgnDocumentErrorCode.INVALID_TAG,
        )

    supplied: dict[str, str] = {}
    for name, value in tags.items():
        if type(name) is not str or not name:
            raise _error(
                "PGN tag name must be non-empty text",
                PgnDocumentErrorCode.INVALID_TAG,
            )
        if type(value) is not str:
            raise _error(
                "PGN tag value must be text",
                PgnDocumentErrorCode.INVALID_TAG,
            )
        supplied[name] = value
    return supplied


def _new_game(tags: Mapping[str, str] | None = None) -> PgnGame:
    values = dict(_STANDARD_TAGS)
    supplied_tags = _passive_new_game_tags(tags)
    if _POSITION_TAGS.intersection(supplied_tags):
        raise _error(
            "PGN start position must be created through the position workflow",
            PgnDocumentErrorCode.INVALID_TAG,
        )
    values.update(supplied_tags)
    result = values.get("Result", "*")
    if result not in RESULTS:
        raise _error("game result is not a valid PGN result", PgnDocumentErrorCode.INVALID_RESULT)
    values["Result"] = result
    # PgnWorkspace performs the canonical strict validation of tag names/values.
    return PgnGame(tags=values, line=VariationLine(result=result))


def _validated_new_game(
    tags: Mapping[str, str] | None = None,
) -> tuple[PgnGame, PgnWorkspace]:
    """Build one metadata-valid new game through the canonical workspace gate."""

    try:
        game = _new_game(tags)
        workspace = PgnWorkspace((game,))
    except PgnDocumentError:
        raise
    except (PgnWorkspaceError, TypeError, ValueError) as exc:
        raise _error(
            "PGN new-game metadata is not valid",
            PgnDocumentErrorCode.INVALID_TAG,
        ) from exc
    return game, workspace


def _recover_malformed_result_placeholder(game: PgnGame) -> str | None:
    """Canonicalize one unambiguous malformed result placeholder for recovery.

    The structural parser deliberately preserves unknown movetext as SAN-like
    data so inspection is loss-aware.  A damaged source can therefore encode an
    invalid Result tag value twice: once in the header and once as the entire
    movetext.  When the parser has already proved both an invalid header result
    and a missing termination marker, and the duplicated token is the *only*
    movetext content, it is safe to recover that token as a malformed result
    placeholder rather than a chess move.

    This is a recovery-only grammar/provenance rule.  It does not accept the
    token in strict PGN, does not validate chess legality, and callers still
    preserve the original source by requiring Save As.
    """

    header_result = game.tags.get("Result")
    if header_result is None or header_result in RESULTS:
        return None

    invalid_header_warning = f"invalid header Result {header_result}"
    if invalid_header_warning not in game.warnings:
        return None
    if not any(
        warning.startswith("missing movetext game termination marker;")
        for warning in game.warnings
    ):
        return None

    line = game.line
    if line.leading_comments or line.trailing_comments or len(line.moves) != 1:
        return None
    node = line.moves[0]
    if (
        node.san != header_result
        or node.move_number is not None
        or node.nags
        or node.comments_before
        or node.comments_after
        or node.variations
    ):
        return None

    line.moves.clear()
    line.result = "*"
    game.tags["Result"] = "*"
    return f"recovered malformed result token {header_result} as *"


def _passive_source_snapshot(source: object) -> SourceFingerprint | None:
    """Detach one live source fingerprint without executing active scalar hooks."""

    if source is None:
        return None
    if type(source) is not SourceFingerprint:
        raise TypeError("PGN source fingerprint is invalid")
    path = source.path
    size = source.size
    sha256 = source.sha256
    suffix = source.suffix
    if (
        type(path) is not str
        or not path
        or type(size) is not int
        or size < 0
        or type(sha256) is not str
        or len(sha256) != 64
        or any(character not in "0123456789abcdef" for character in sha256)
        or type(suffix) is not str
        or suffix != suffix.lower()
        or suffix != Path(path).suffix.lower()
    ):
        raise TypeError("PGN source fingerprint fields are invalid")
    return SourceFingerprint(
        path=path,
        size=size,
        sha256=sha256,
        suffix=suffix,
    )


class PgnDocumentSession:
    """One user-facing PGN document session over the canonical workspace."""

    def __init__(
        self,
        workspace: PgnWorkspace,
        *,
        source: SourceFingerprint | None = None,
        global_warnings: tuple[str, ...] = (),
        source_overwrite_safe: bool = True,
        saved_digest: str | None = None,
    ) -> None:
        if type(workspace) is not PgnWorkspace:
            raise TypeError("workspace must be the canonical PgnWorkspace")
        if source is not None:
            if type(source) is not SourceFingerprint:
                raise TypeError("source must be SourceFingerprint or None")
            # Snapshot caller-owned fields once. Frozen dataclasses can still be
            # mutated through low-level object APIs; validation and detachment
            # must therefore consume the same passive values rather than
            # re-reading a possibly changed object after validation.
            source_path = source.path
            source_size = source.size
            source_sha256 = source.sha256
            source_suffix = source.suffix
            if (
                type(source_path) is not str
                or type(source_size) is not int
                or type(source_sha256) is not str
                or type(source_suffix) is not str
            ):
                raise TypeError("source fingerprint fields must be passive built-in scalars")
            if not source_path:
                raise ValueError("source fingerprint path must not be empty")
            if source_size < 0:
                raise ValueError("source fingerprint size must not be negative")
            if (
                len(source_sha256) != 64
                or any(character not in "0123456789abcdef" for character in source_sha256)
            ):
                raise ValueError("source fingerprint digest must be lowercase SHA-256 hex")
            canonical_suffix = Path(source_path).suffix.lower()
            if source_suffix != source_suffix.lower() or source_suffix != canonical_suffix:
                raise ValueError("source fingerprint suffix must match its source path")
            source = SourceFingerprint(
                path=source_path,
                size=source_size,
                sha256=source_sha256,
                suffix=source_suffix,
            )
        if type(global_warnings) is not tuple or any(
            type(item) is not str for item in global_warnings
        ):
            raise TypeError("global_warnings must be a built-in tuple of plain text")
        if type(source_overwrite_safe) is not bool:
            raise TypeError("source_overwrite_safe must be a boolean")
        if saved_digest is not None:
            if type(saved_digest) is not str:
                raise TypeError("saved_digest must be plain text or None")
            if (
                len(saved_digest) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in saved_digest
                )
            ):
                raise ValueError("saved_digest must be lowercase SHA-256 hex")
        self._workspace = workspace
        self._source = source
        self._global_warnings = global_warnings
        self._source_overwrite_safe = source_overwrite_safe
        self._saved_digest = saved_digest
        self._document_revision = 0

    @classmethod
    def new_game(cls, tags: Mapping[str, str] | None = None) -> "PgnDocumentSession":
        _game, workspace = _validated_new_game(tags)
        # No backing file exists, so a new document is intentionally dirty.
        return cls(workspace, saved_digest=None)

    @classmethod
    def new_game_from_position(
        cls,
        position: PositionState,
        tags: Mapping[str, str] | None = None,
    ) -> "PgnDocumentSession":
        """Create a PGN document from the canonical Position workflow state.

        Generic callers cannot inject SetUp/FEN through metadata.  This explicit
        seam converts the already-materialized PositionState to FEN and then
        revalidates that FEN through chesscore.Board, which remains the canonical
        chess/FEN authority.  Standard-start positions stay ordinary PGN games;
        non-standard starts publish SetUp/FEN atomically as one pair.
        """

        # This is an authority boundary, not a structural/protocol check:
        # subclasses may override methods such as to_fen() and therefore are not
        # canonical PositionState values. Reject the position before touching
        # caller-supplied metadata so invalid-position classification remains
        # deterministic and no unrelated mapping code executes first.
        position = _passive_position_state(position)
        game, _metadata_workspace = _validated_new_game(tags)

        try:
            canonical_fen = Board(position.to_fen()).fen()
        except ValueError as exc:
            raise _error(
                "PGN start position is not valid",
                PgnDocumentErrorCode.INVALID_POSITION,
            ) from exc

        if canonical_fen != Board.START:
            game.tags["SetUp"] = "1"
            game.tags["FEN"] = canonical_fen

        try:
            workspace = PgnWorkspace((game,))
        except (PgnWorkspaceError, TypeError, ValueError) as exc:
            raise _error(
                "PGN start position is not representable",
                PgnDocumentErrorCode.INVALID_POSITION,
            ) from exc
        return cls(workspace, saved_digest=None)

    @classmethod
    def from_text(cls, text: object) -> "PgnDocumentSession":
        workspace = PgnWorkspace.from_text(text)
        # Pasted/imported text has no backing file until Save As.
        return cls(workspace, saved_digest=None)

    @classmethod
    def open(cls, path: str | Path) -> "PgnDocumentSession":
        opened: PgnOpenResult = open_pgn(path)
        warnings = list(opened.global_warnings)
        recovered_games = deepcopy(opened.games)
        for index, game in enumerate(recovered_games, start=1):
            recovery_warning = _recover_malformed_result_placeholder(game)
            if recovery_warning is not None:
                game.warnings.append(recovery_warning)
            warnings.extend(f"Game {index}: {warning}" for warning in game.warnings)
            # Parser warnings are provenance about the damaged source, not
            # serializable GameTree content.  Keep them on the document view
            # while constructing a strict canonical recovery snapshot that
            # can only be published through Save As.
            game.warnings.clear()
        workspace = PgnWorkspace(recovered_games)
        overwrite_safe = not warnings
        return cls(
            workspace,
            source=opened.source,
            global_warnings=tuple(warnings),
            source_overwrite_safe=overwrite_safe,
            saved_digest=workspace.content_digest if overwrite_safe else None,
        )

    @property
    def workspace(self) -> PgnWorkspace:
        return self._workspace

    @property
    def source(self) -> SourceFingerprint | None:
        # Never expose the internal provenance object itself. Frozen dataclass
        # protection prevents ordinary assignment but not low-level mutation
        # through a caller-retained reference. Revalidate exact passive scalar
        # shape on every outward read so a corrupted source cannot execute hooks
        # or leak malformed provenance into the UI.
        return _passive_source_snapshot(self._source)

    @property
    def dirty(self) -> bool:
        saved_digest = self._saved_digest
        content_digest = self._workspace.content_digest
        if saved_digest is not None and (
            type(saved_digest) is not str
            or len(saved_digest) != 64
            or any(character not in "0123456789abcdef" for character in saved_digest)
        ):
            raise TypeError("PGN saved digest is invalid")
        if (
            type(content_digest) is not str
            or len(content_digest) != 64
            or any(character not in "0123456789abcdef" for character in content_digest)
        ):
            raise TypeError("PGN workspace digest is invalid")
        return saved_digest is None or content_digest != saved_digest

    @property
    def document_revision(self) -> int:
        revision = self._document_revision
        if type(revision) is not int or revision < 0:
            raise TypeError("PGN document revision is invalid")
        return revision

    def view(self) -> PgnDocumentView:
        source = _passive_source_snapshot(self._source)
        source_overwrite_safe = self._source_overwrite_safe
        global_warnings = self._global_warnings
        revision = self.document_revision
        if type(source_overwrite_safe) is not bool:
            raise TypeError("PGN source overwrite safety flag is invalid")
        if type(global_warnings) is not tuple or any(
            type(item) is not str for item in global_warnings
        ):
            raise TypeError("PGN global warnings are invalid")
        workspace_view = self._workspace.view()
        return PgnDocumentView(
            source_path=None if source is None else source.path,
            source_sha256=None if source is None else source.sha256,
            game_count=workspace_view.game_count,
            selected_game_index=workspace_view.selected_game_index,
            cursor=_passive_context_cursor(workspace_view.cursor),
            dirty=self.dirty,
            document_revision=revision,
            source_overwrite_safe=source_overwrite_safe,
            global_warnings=global_warnings,
        )

    def bookmark(self) -> PgnDocumentContext:
        view = self._workspace.view()
        content_digest = view.content_digest
        selected_game_index = view.selected_game_index
        if (
            type(content_digest) is not str
            or len(content_digest) != 64
            or any(character not in "0123456789abcdef" for character in content_digest)
            or type(selected_game_index) is not int
            or selected_game_index < 0
        ):
            raise TypeError("PGN workspace bookmark state is invalid")
        return PgnDocumentContext(
            content_digest=content_digest,
            selected_game_index=selected_game_index,
            cursor=_passive_context_cursor(view.cursor),
        )

    def restore_context(self, context: PgnDocumentContext) -> PgnWorkspaceView:
        if type(context) is not PgnDocumentContext:
            raise TypeError("context must be the canonical PgnDocumentContext")
        # Snapshot the exact dataclass once; all later validation/mutation uses
        # these passive locals so low-level caller mutation cannot change the
        # restore target between validation and canonical navigation.
        content_digest = context.content_digest
        selected_game_index = context.selected_game_index
        context_cursor = context.cursor
        if (
            type(content_digest) is not str
            or type(selected_game_index) is not int
            or selected_game_index < 0
        ):
            raise _error(
                "saved PGN context is not canonical",
                PgnDocumentErrorCode.CONTEXT_STALE,
            )
        cursor = _passive_context_cursor(context_cursor)
        live_content_digest = self._workspace.content_digest
        if (
            type(live_content_digest) is not str
            or len(live_content_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in live_content_digest
            )
        ):
            raise _error(
                "PGN live content identity is not canonical",
                PgnDocumentErrorCode.CONTEXT_STALE,
            )
        if live_content_digest != content_digest:
            raise _error(
                "PGN content changed; exact saved context is stale",
                PgnDocumentErrorCode.CONTEXT_STALE,
            )

        # Validate the complete return point against a detached canonical
        # workspace before mutating the live session. Calling select_game()
        # first would otherwise switch games/reset the cursor even when the
        # subsequent cursor validation rejects a forged or damaged context.
        # Use the passively detached cursor so nested subclasses/tampering never
        # cross into canonical GameTree navigation.
        probe = PgnWorkspace(self._workspace.games())
        try:
            probe.select_game(selected_game_index)
            probe.set_cursor(cursor)
        except (TypeError, ValueError) as exc:
            raise _error(
                "saved PGN context is not valid for the current document",
                PgnDocumentErrorCode.CONTEXT_STALE,
            ) from exc

        self._workspace.select_game(selected_game_index)
        return self._workspace.set_cursor(cursor)

    def copy_pgn(self) -> str:
        return self._workspace.to_text()

    def _replace_document(
        self,
        games: tuple[PgnGame, ...],
        *,
        selected_game_index: int,
        cursor: GameTreeCursor,
    ) -> PgnWorkspaceView:
        revision = self.document_revision
        replacement = PgnWorkspace(games)
        replacement.select_game(selected_game_index)
        replacement.set_cursor(cursor)
        # Materialize the complete candidate presentation before publishing the
        # replacement workspace. A projection abort must not leave document
        # content advanced while the caller receives a failure.
        replacement_view = replacement.view()
        self._workspace = replacement
        self._document_revision = revision + 1
        return replacement_view

    def append_text(self, text: object) -> int:
        """Append all games from pasted/imported PGN without flattening trees."""

        imported = PgnWorkspace.from_text(text)
        old = self._workspace.view()
        existing = self._workspace.games()
        incoming = list(imported.games())
        # ``source_index`` identifies a game inside the current canonical PGN
        # document.  A pasted document starts again at zero, so appending it
        # verbatim would create duplicate identities and then fail canonical
        # write/reparse equality.  The snapshots are detached copies, making
        # this renumbering atomic and leaving both source workspaces untouched.
        start_index = len(existing)
        for offset, game in enumerate(incoming):
            game.source_index = start_index + offset
        combined = existing + tuple(incoming)
        self._replace_document(
            combined,
            selected_game_index=old.selected_game_index,
            cursor=old.cursor,
        )
        return len(incoming)

    def edit_tag(self, name: object, value: object) -> PgnWorkspaceView:
        if type(name) is not str or not name:
            raise _error("PGN tag name must be non-empty text", PgnDocumentErrorCode.INVALID_TAG)
        if type(value) is not str:
            raise _error("PGN tag value must be text", PgnDocumentErrorCode.INVALID_TAG)
        if name in _POSITION_TAGS:
            raise _error(
                "PGN start position must be changed through the position workflow",
                PgnDocumentErrorCode.INVALID_TAG,
            )
        if name == "Result":
            return self.set_result(value)

        old = self._workspace.view()
        games = list(self._workspace.games())
        games[old.selected_game_index].tags[name] = value
        try:
            return self._replace_document(
                tuple(games),
                selected_game_index=old.selected_game_index,
                cursor=old.cursor,
            )
        except (TypeError, ValueError) as exc:
            raise _error("PGN tag is not representable", PgnDocumentErrorCode.INVALID_TAG) from exc

    def delete_tag(self, name: object) -> PgnWorkspaceView:
        if type(name) is not str or not name or name == "Result":
            raise _error("PGN tag cannot be removed", PgnDocumentErrorCode.INVALID_TAG)
        if name in _POSITION_TAGS:
            raise _error(
                "PGN start position must be changed through the position workflow",
                PgnDocumentErrorCode.INVALID_TAG,
            )
        old = self._workspace.view()
        games = list(self._workspace.games())
        games[old.selected_game_index].tags.pop(name, None)
        return self._replace_document(
            tuple(games),
            selected_game_index=old.selected_game_index,
            cursor=old.cursor,
        )

    def set_result(self, result: object) -> PgnWorkspaceView:
        if type(result) is not str or result not in RESULTS:
            raise _error("game result is not a valid PGN result", PgnDocumentErrorCode.INVALID_RESULT)
        old = self._workspace.view()
        games = list(self._workspace.games())
        game = games[old.selected_game_index]
        game.tags["Result"] = result
        game.line.result = result
        return self._replace_document(
            tuple(games),
            selected_game_index=old.selected_game_index,
            cursor=old.cursor,
        )

    def _commit_saved_file(
        self,
        saved: SourceFingerprint,
        *,
        save_as: bool,
    ) -> None:
        """Finalize verified durable bytes without a partially updated session."""

        if type(saved) is not SourceFingerprint:
            raise _error(
                "PGN file was written but returned provenance is not canonical",
                PgnDocumentErrorCode.SAVE_COMMIT_FAILED,
            )
        path = saved.path
        size = saved.size
        sha256 = saved.sha256
        suffix = saved.suffix
        if (
            type(path) is not str
            or not path
            or type(size) is not int
            or size < 0
            or type(sha256) is not str
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
            or type(suffix) is not str
            or suffix != suffix.lower()
            or suffix != Path(path).suffix.lower()
        ):
            raise _error(
                "PGN file was written but returned provenance is invalid",
                PgnDocumentErrorCode.SAVE_COMMIT_FAILED,
            )
        content_digest = self._workspace.content_digest
        document_revision = self._document_revision
        if (
            type(content_digest) is not str
            or len(content_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in content_digest
            )
            or type(document_revision) is not int
            or document_revision < 0
        ):
            raise _error(
                "PGN file was written but live document state is invalid",
                PgnDocumentErrorCode.SAVE_COMMIT_FAILED,
            )
        next_source = SourceFingerprint(
            path=path,
            size=size,
            sha256=sha256,
            suffix=suffix,
        )
        try:
            self._workspace.mark_saved()
        except BaseException as exc:
            raise _error(
                "PGN file was written but the document checkpoint could not be finalized",
                PgnDocumentErrorCode.SAVE_COMMIT_FAILED,
            ) from exc

        self._source = next_source
        if save_as:
            self._source_overwrite_safe = True
            self._global_warnings = ()
        self._saved_digest = content_digest
        self._document_revision = document_revision + 1

    def save(self) -> SourceFingerprint:
        if type(self._source_overwrite_safe) is not bool:
            raise TypeError("PGN source overwrite safety flag is invalid")
        source = _passive_source_snapshot(self._source)
        if source is None:
            raise _error("document has no source; use Save As", PgnDocumentErrorCode.NO_SOURCE)
        if not self._source_overwrite_safe:
            raise _error(
                "source required recovery; use Save As to preserve the original",
                PgnDocumentErrorCode.SOURCE_REQUIRES_SAVE_AS,
            )
        saved = save_pgn_atomic(
            source.path,
            self._workspace.games(),
            overwrite=True,
            expected_sha256=source.sha256,
        )
        self._commit_saved_file(saved, save_as=False)
        return saved

    @staticmethod
    def _destination_expectation(
        destination: Path,
        *,
        overwrite: bool,
        expected_sha256: str | None,
    ) -> str | None:
        # Overwrite is an authorization request, not a hint inferred from a
        # potentially stale existence check. Requiring the exact destination
        # generation for every replacement closes the check/use race where a
        # previously absent target could appear before atomic publication and be
        # silently clobbered. New targets must use overwrite=False so the
        # canonical writer owns the no-clobber create race.
        if type(overwrite) is not bool:
            raise TypeError("overwrite must be a boolean")
        if overwrite and expected_sha256 is None:
            raise _error(
                "destination overwrite requires its expected fingerprint",
                PgnDocumentErrorCode.DESTINATION_VERSION_REQUIRED,
            )
        return _validated_expected_sha256(expected_sha256)

    def save_as(
        self,
        path: str | Path,
        *,
        overwrite: bool = False,
        expected_sha256: str | None = None,
    ) -> SourceFingerprint:
        if type(self._source_overwrite_safe) is not bool:
            raise TypeError("PGN source overwrite safety flag is invalid")
        source = _passive_source_snapshot(self._source)
        destination = Path(path)
        expected = self._destination_expectation(
            destination,
            overwrite=overwrite,
            expected_sha256=expected_sha256,
        )
        if (
            source is not None
            and not self._source_overwrite_safe
            and _same_direct_path(destination, source.path)
        ):
            raise _error(
                "recovery source must be preserved; choose a different Save As destination",
                PgnDocumentErrorCode.RECOVERY_SOURCE_REQUIRES_DIFFERENT_DESTINATION,
            )
        # Save As may explicitly select this document's current source. Keep
        # that overwrite bound to the source generation captured by the session;
        # a fresh hash obtained after an external edit is not overwrite authority.
        if (
            overwrite
            and source is not None
            and _same_direct_path(destination, source.path)
        ):
            expected = source.sha256
        saved = save_pgn_atomic(
            destination,
            self._workspace.games(),
            overwrite=overwrite,
            expected_sha256=expected,
        )
        self._commit_saved_file(saved, save_as=True)
        return saved

    def export_selected(
        self,
        path: str | Path,
        *,
        overwrite: bool = False,
        expected_sha256: str | None = None,
    ) -> SourceFingerprint:
        destination = Path(path)
        expected = self._destination_expectation(
            destination,
            overwrite=overwrite,
            expected_sha256=expected_sha256,
        )
        return export_game_atomic(
            destination,
            self._workspace.current_game(),
            overwrite=overwrite,
            expected_sha256=expected,
        )

    def expected_destination_sha256(self, path: str | Path) -> str | None:
        """Fingerprint an existing Save-As/export target before explicit replace."""

        destination = Path(path)
        if not destination.exists():
            return None
        return fingerprint(destination).sha256


__all__ = [
    "PgnConcurrentWriteError",
    "PgnDocumentContext",
    "PgnDocumentError",
    "PgnDocumentErrorCode",
    "PgnDocumentSession",
    "PgnDocumentView",
]
