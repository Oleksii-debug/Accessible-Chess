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

from .gametree import PgnGame, RESULTS, VariationLine
from .gametree_navigation import GameTreeCursor
from .import_contract import SourceFingerprint, fingerprint
from .pgn_service import (
    PgnConcurrentWriteError,
    PgnOpenResult,
    export_game_atomic,
    open_pgn,
    save_pgn_atomic,
)
from .pgn_workspace import PgnWorkspace, PgnWorkspaceView


class PgnDocumentErrorCode(str, Enum):
    NO_SOURCE = "no_source"
    SOURCE_REQUIRES_SAVE_AS = "source_requires_save_as"
    DESTINATION_VERSION_REQUIRED = "destination_version_required"
    INVALID_TAG = "invalid_tag"
    INVALID_RESULT = "invalid_result"
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


def _error(message: str, code: PgnDocumentErrorCode) -> PgnDocumentError:
    return PgnDocumentError(message, code=code)


def _new_game(tags: Mapping[str, str] | None = None) -> PgnGame:
    values = dict(_STANDARD_TAGS)
    if tags is not None:
        values.update(dict(tags))
    result = values.get("Result", "*")
    if result not in RESULTS:
        raise _error("game result is not a valid PGN result", PgnDocumentErrorCode.INVALID_RESULT)
    values["Result"] = result
    # PgnWorkspace performs the canonical strict validation of tag names/values.
    return PgnGame(tags=values, line=VariationLine(result=result))


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
        if not isinstance(workspace, PgnWorkspace):
            raise TypeError("workspace must be PgnWorkspace")
        if source is not None and not isinstance(source, SourceFingerprint):
            raise TypeError("source must be SourceFingerprint or None")
        if not isinstance(global_warnings, tuple) or any(
            not isinstance(item, str) for item in global_warnings
        ):
            raise TypeError("global_warnings must be a tuple of text")
        self._workspace = workspace
        self._source = source
        self._global_warnings = global_warnings
        self._source_overwrite_safe = bool(source_overwrite_safe)
        self._saved_digest = saved_digest
        self._document_revision = 0

    @classmethod
    def new_game(cls, tags: Mapping[str, str] | None = None) -> "PgnDocumentSession":
        workspace = PgnWorkspace((_new_game(tags),))
        # No backing file exists, so a new document is intentionally dirty.
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
        return self._source

    @property
    def dirty(self) -> bool:
        return self._saved_digest is None or self._workspace.content_digest != self._saved_digest

    @property
    def document_revision(self) -> int:
        return self._document_revision

    def view(self) -> PgnDocumentView:
        workspace_view = self._workspace.view()
        return PgnDocumentView(
            source_path=None if self._source is None else self._source.path,
            source_sha256=None if self._source is None else self._source.sha256,
            game_count=workspace_view.game_count,
            selected_game_index=workspace_view.selected_game_index,
            cursor=workspace_view.cursor,
            dirty=self.dirty,
            document_revision=self._document_revision,
            source_overwrite_safe=self._source_overwrite_safe,
            global_warnings=self._global_warnings,
        )

    def bookmark(self) -> PgnDocumentContext:
        view = self._workspace.view()
        return PgnDocumentContext(
            content_digest=view.content_digest,
            selected_game_index=view.selected_game_index,
            cursor=view.cursor,
        )

    def restore_context(self, context: PgnDocumentContext) -> PgnWorkspaceView:
        if not isinstance(context, PgnDocumentContext):
            raise TypeError("context must be PgnDocumentContext")
        if self._workspace.content_digest != context.content_digest:
            raise _error(
                "PGN content changed; exact saved context is stale",
                PgnDocumentErrorCode.CONTEXT_STALE,
            )
        self._workspace.select_game(context.selected_game_index)
        return self._workspace.set_cursor(context.cursor)

    def copy_pgn(self) -> str:
        return self._workspace.to_text()

    def _replace_document(
        self,
        games: tuple[PgnGame, ...],
        *,
        selected_game_index: int,
        cursor: GameTreeCursor,
    ) -> PgnWorkspaceView:
        replacement = PgnWorkspace(games)
        replacement.select_game(selected_game_index)
        replacement.set_cursor(cursor)
        self._workspace = replacement
        self._document_revision += 1
        return replacement.view()

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
        if not isinstance(name, str) or not name:
            raise _error("PGN tag name must be non-empty text", PgnDocumentErrorCode.INVALID_TAG)
        if not isinstance(value, str):
            raise _error("PGN tag value must be text", PgnDocumentErrorCode.INVALID_TAG)
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
        if not isinstance(name, str) or not name or name == "Result":
            raise _error("PGN tag cannot be removed", PgnDocumentErrorCode.INVALID_TAG)
        old = self._workspace.view()
        games = list(self._workspace.games())
        games[old.selected_game_index].tags.pop(name, None)
        return self._replace_document(
            tuple(games),
            selected_game_index=old.selected_game_index,
            cursor=old.cursor,
        )

    def set_result(self, result: object) -> PgnWorkspaceView:
        if not isinstance(result, str) or result not in RESULTS:
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

    def save(self) -> SourceFingerprint:
        if self._source is None:
            raise _error("document has no source; use Save As", PgnDocumentErrorCode.NO_SOURCE)
        if not self._source_overwrite_safe:
            raise _error(
                "source required recovery; use Save As to preserve the original",
                PgnDocumentErrorCode.SOURCE_REQUIRES_SAVE_AS,
            )
        saved = save_pgn_atomic(
            self._source.path,
            self._workspace.games(),
            overwrite=True,
            expected_sha256=self._source.sha256,
        )
        self._source = saved
        self._saved_digest = self._workspace.content_digest
        self._workspace.mark_saved()
        self._document_revision += 1
        return saved

    @staticmethod
    def _destination_expectation(
        destination: Path,
        *,
        overwrite: bool,
        expected_sha256: str | None,
    ) -> str | None:
        if destination.exists() and overwrite and expected_sha256 is None:
            raise _error(
                "existing destination requires its expected fingerprint before overwrite",
                PgnDocumentErrorCode.DESTINATION_VERSION_REQUIRED,
            )
        return expected_sha256

    def save_as(
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
        saved = save_pgn_atomic(
            destination,
            self._workspace.games(),
            overwrite=overwrite,
            expected_sha256=expected,
        )
        self._source = saved
        self._source_overwrite_safe = True
        self._global_warnings = ()
        self._saved_digest = self._workspace.content_digest
        self._workspace.mark_saved()
        self._document_revision += 1
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
