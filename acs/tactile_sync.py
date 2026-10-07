from __future__ import annotations

"""Section 10 tactile synchronization over existing canonical chess state.

This module deliberately owns no chess rules, GameTree, Book navigation, Training
correctness, tactile scene construction, or hardware transport.  It consumes the
canonical FEN already published by those owners and forwards it through a narrow
Section-10 sink.  Section 8/9 may adapt their TactileDisplayPort / hardware
implementation to :class:`TactilePositionSink` without creating a second chess
authority.
"""

from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Protocol, runtime_checkable

from .book_board_workflow import BookBoardView, BookBoardWorkflow
from .chesscore import Board
from .input_limits import MAX_FEN_CHARS
from .training import ExerciseSession
from .version2_pgn_commands import Version2PgnCommands


class TactileSyncSource(str, Enum):
    POSITION = "position"
    PGN = "pgn"
    BOOK = "book"
    TRAINING = "training"


class TactileSyncState(str, Enum):
    IDLE = "idle"
    SYNCED = "synced"
    ERROR = "error"


class TactileSyncCommand(str, Enum):
    STATUS = "tactile.status"
    REFRESH_POSITION = "tactile.refresh_position"
    REFRESH_PGN = "tactile.refresh_pgn"
    REFRESH_BOOK = "tactile.refresh_book"
    REFRESH_TRAINING = "tactile.refresh_training"


class TactileSyncError(RuntimeError):
    """Stable presentation-safe synchronization failure."""


@dataclass(frozen=True, slots=True)
class TactileSyncSnapshot:
    state: TactileSyncState
    source: TactileSyncSource | None
    canonical_fen: str | None
    sync_revision: int
    source_revision: int | None
    status_key: str

    def __post_init__(self) -> None:
        if type(self.sync_revision) is not int or self.sync_revision < 0:
            raise ValueError("sync_revision must be a non-negative exact integer")
        if self.source_revision is not None and (
            type(self.source_revision) is not int or self.source_revision < 0
        ):
            raise ValueError("source_revision must be a non-negative exact integer or None")


@runtime_checkable
class TactilePositionSink(Protocol):
    """Narrow Section-10 output seam implemented by the Section-8/9 adapter.

    The sink receives canonical FEN only.  It may render a TactileScene or send
    that scene to hardware, but it must not reinterpret chess legality.
    """

    def present_position(
        self,
        canonical_fen: str,
        *,
        source: TactileSyncSource,
        revision: int,
    ) -> None:
        ...


class TactileSyncController:
    """Synchronize canonical PGN/Book/Training positions to tactile output.

    A failed tactile presentation never rolls back or mutates canonical chess,
    Book, or Training state.  The controller records an accessible semantic
    status key and allows a later refresh of the same canonical state.
    """

    def __init__(self, sink: TactilePositionSink) -> None:
        if not isinstance(sink, TactilePositionSink):
            raise TypeError("sink must implement TactilePositionSink")
        self._sink = sink
        self._lock = RLock()
        self._snapshot = TactileSyncSnapshot(
            state=TactileSyncState.IDLE,
            source=None,
            canonical_fen=None,
            sync_revision=0,
            source_revision=None,
            status_key="tactile.status.idle",
        )

    @staticmethod
    def _canonical_fen(value: object) -> str:
        if type(value) is not str:
            raise TactileSyncError("canonical tactile position must be FEN text")
        if not value or len(value) > MAX_FEN_CHARS or "\x00" in value:
            raise TactileSyncError("canonical tactile position is invalid")
        try:
            canonical = Board(value).fen()
        except (TypeError, ValueError) as exc:
            raise TactileSyncError("canonical tactile position is invalid") from exc
        if canonical != value:
            raise TactileSyncError("tactile synchronization requires canonical FEN")
        return canonical

    @staticmethod
    def _source_revision(value: object) -> int | None:
        if value is None:
            return None
        if type(value) is not int or value < 0:
            raise TactileSyncError("tactile source revision is invalid")
        return value

    def snapshot(self) -> TactileSyncSnapshot:
        with self._lock:
            return self._snapshot

    def _publish(
        self,
        fen: object,
        *,
        source: TactileSyncSource,
        source_revision: object = None,
    ) -> TactileSyncSnapshot:
        canonical = self._canonical_fen(fen)
        bounded_source_revision = self._source_revision(source_revision)
        with self._lock:
            next_revision = self._snapshot.sync_revision + 1
            try:
                self._sink.present_position(
                    canonical,
                    source=source,
                    revision=next_revision,
                )
            except Exception as exc:
                self._snapshot = TactileSyncSnapshot(
                    state=TactileSyncState.ERROR,
                    source=source,
                    canonical_fen=canonical,
                    sync_revision=self._snapshot.sync_revision,
                    source_revision=bounded_source_revision,
                    status_key="tactile.status.refresh_failed",
                )
                raise TactileSyncError("tactile position refresh failed") from exc
            self._snapshot = TactileSyncSnapshot(
                state=TactileSyncState.SYNCED,
                source=source,
                canonical_fen=canonical,
                sync_revision=next_revision,
                source_revision=bounded_source_revision,
                status_key="tactile.status.synced",
            )
            return self._snapshot

    def sync_position(
        self,
        fen: object,
        *,
        source_revision: object = None,
    ) -> TactileSyncSnapshot:
        """Synchronize any already-canonical Position/FEN boundary."""

        return self._publish(
            fen,
            source=TactileSyncSource.POSITION,
            source_revision=source_revision,
        )

    def sync_pgn(self, commands: Version2PgnCommands) -> TactileSyncSnapshot:
        """Synchronize the exact canonical position selected by PGN/GameTree."""

        if not isinstance(commands, Version2PgnCommands):
            raise TypeError("commands must be Version2PgnCommands")
        return self._publish(
            commands.current_fen(),
            source=TactileSyncSource.PGN,
        )

    def sync_book_view(self, view: BookBoardView) -> TactileSyncSnapshot:
        """Synchronize an exact Book -> Board view without moving Book progress."""

        if not isinstance(view, BookBoardView):
            raise TypeError("view must be BookBoardView")
        return self._publish(
            view.current_fen,
            source=TactileSyncSource.BOOK,
            source_revision=view.revision,
        )

    def sync_book(self, workflow: BookBoardWorkflow) -> TactileSyncSnapshot:
        if not isinstance(workflow, BookBoardWorkflow):
            raise TypeError("workflow must be BookBoardWorkflow")
        return self.sync_book_view(workflow.view())

    def sync_training(self, session: ExerciseSession) -> TactileSyncSnapshot:
        """Synchronize Training before/after an answer from canonical session state."""

        if not isinstance(session, ExerciseSession):
            raise TypeError("session must be ExerciseSession")
        return self._publish(
            session.current_fen,
            source=TactileSyncSource.TRAINING,
            source_revision=session.attempts,
        )

    def dispatch(
        self,
        command: TactileSyncCommand | str,
        payload: object = None,
    ) -> TactileSyncSnapshot:
        """Strict typed command seam for keyboard/screen-reader presentation.

        The UI can bind these stable command IDs to accessible controls.  No
        command here mutates chess state; refresh only reads an existing owner.
        """

        try:
            selected = (
                command
                if isinstance(command, TactileSyncCommand)
                else TactileSyncCommand(command)
            )
        except (TypeError, ValueError) as exc:
            raise TactileSyncError("unsupported tactile command") from exc

        if selected is TactileSyncCommand.STATUS:
            if payload is not None:
                raise TactileSyncError("tactile.status accepts no payload")
            return self.snapshot()
        if selected is TactileSyncCommand.REFRESH_POSITION:
            if type(payload) is not str:
                raise TactileSyncError("tactile.refresh_position requires canonical FEN")
            return self.sync_position(payload)
        if selected is TactileSyncCommand.REFRESH_PGN:
            if not isinstance(payload, Version2PgnCommands):
                raise TactileSyncError("tactile.refresh_pgn requires PGN commands")
            return self.sync_pgn(payload)
        if selected is TactileSyncCommand.REFRESH_BOOK:
            if not isinstance(payload, BookBoardWorkflow):
                raise TactileSyncError("tactile.refresh_book requires Book workflow")
            return self.sync_book(payload)
        if selected is TactileSyncCommand.REFRESH_TRAINING:
            if not isinstance(payload, ExerciseSession):
                raise TactileSyncError("tactile.refresh_training requires Training session")
            return self.sync_training(payload)
        raise AssertionError("unreachable tactile command")
