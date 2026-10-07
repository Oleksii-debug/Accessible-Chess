from __future__ import annotations

"""Section 10 synchronization from canonical product state into Section-8 tactile scenes.

This layer owns no chess rules, tactile geometry, device SDK, Book navigation or
Training correctness. It composes the already-existing canonical owners with the
Section-8 TactileGraphicsController. Section 9 remains the physical-device owner
behind TactileDisplayPort.
"""

from dataclasses import dataclass
from enum import Enum
from threading import RLock

from .book_board_workflow import BookBoardView, BookBoardWorkflow
from .pgn_workspace import PgnWorkspace
from .position_editor import PositionState, PositionValidationError
from .tactile_graphics import (
    TactileGraphicsController,
    TactileGraphicsError,
    TactileScene,
)
from .training import ExerciseSession


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
    """Stable application-level tactile synchronization failure."""


@dataclass(frozen=True, slots=True)
class TactileSyncSnapshot:
    state: TactileSyncState
    source: TactileSyncSource | None
    canonical_fen: str | None
    sync_revision: int
    source_revision: int | None
    scene_sequence: int | None
    status_key: str

    def __post_init__(self) -> None:
        if type(self.sync_revision) is not int or self.sync_revision < 0:
            raise ValueError("sync_revision must be a non-negative exact integer")
        if self.source_revision is not None and (
            type(self.source_revision) is not int or self.source_revision < 0
        ):
            raise ValueError("source_revision must be a non-negative exact integer or None")
        if self.scene_sequence is not None and (
            type(self.scene_sequence) is not int or self.scene_sequence < 0
        ):
            raise ValueError("scene_sequence must be a non-negative exact integer or None")


class TactileSyncController:
    """Bind PGN, Books, Training and Position state to the Section-8 controller."""

    def __init__(self, graphics: TactileGraphicsController) -> None:
        if not isinstance(graphics, TactileGraphicsController):
            raise TypeError("graphics must be TactileGraphicsController")
        self._graphics = graphics
        self._lock = RLock()
        self._snapshot = TactileSyncSnapshot(
            state=TactileSyncState.IDLE,
            source=None,
            canonical_fen=None,
            sync_revision=0,
            source_revision=None,
            scene_sequence=None,
            status_key="tactile.status.idle",
        )

    @staticmethod
    def _position_from_fen(value: object) -> PositionState:
        if type(value) is not str:
            raise TactileSyncError("tactile position must be canonical FEN text")
        try:
            position = PositionState.from_fen(value)
        except (PositionValidationError, TypeError, ValueError) as exc:
            raise TactileSyncError("tactile position is invalid") from exc
        if position.to_fen() != value:
            raise TactileSyncError("tactile synchronization requires canonical FEN")
        return position

    @staticmethod
    def _revision(value: object) -> int | None:
        if value is None:
            return None
        if type(value) is not int or value < 0:
            raise TactileSyncError("tactile source revision is invalid")
        return value

    def snapshot(self) -> TactileSyncSnapshot:
        with self._lock:
            return self._snapshot

    def _accept_scene(
        self,
        scene: TactileScene,
        *,
        source: TactileSyncSource,
        source_revision: object = None,
    ) -> TactileSyncSnapshot:
        if type(scene) is not TactileScene:
            raise TactileSyncError("Section-8 tactile controller returned an invalid scene")
        bounded_source_revision = self._revision(source_revision)
        with self._lock:
            self._snapshot = TactileSyncSnapshot(
                state=TactileSyncState.SYNCED,
                source=source,
                canonical_fen=scene.position_fen,
                sync_revision=self._snapshot.sync_revision + 1,
                source_revision=bounded_source_revision,
                scene_sequence=scene.sequence,
                status_key="tactile.status.synced",
            )
            return self._snapshot

    def _fail(
        self,
        source: TactileSyncSource,
        *,
        source_revision: object = None,
    ) -> None:
        bounded_source_revision = self._revision(source_revision)
        with self._lock:
            current_scene = self._graphics.current_scene
            self._snapshot = TactileSyncSnapshot(
                state=TactileSyncState.ERROR,
                source=source,
                canonical_fen=(
                    None if current_scene is None else current_scene.position_fen
                ),
                sync_revision=self._snapshot.sync_revision,
                source_revision=bounded_source_revision,
                scene_sequence=(
                    None if current_scene is None else current_scene.sequence
                ),
                status_key="tactile.status.refresh_failed",
            )

    def _publish_position(
        self,
        fen: object,
        *,
        source: TactileSyncSource,
        source_revision: object = None,
    ) -> TactileSyncSnapshot:
        position = self._position_from_fen(fen)
        try:
            scene = self._graphics.on_position_navigation(position)
        except Exception as exc:
            self._fail(source, source_revision=source_revision)
            raise TactileSyncError("tactile position refresh failed") from exc
        return self._accept_scene(
            scene,
            source=source,
            source_revision=source_revision,
        )

    def sync_position(
        self,
        fen: object,
        *,
        source_revision: object = None,
    ) -> TactileSyncSnapshot:
        return self._publish_position(
            fen,
            source=TactileSyncSource.POSITION,
            source_revision=source_revision,
        )

    def sync_pgn(self, workspace: PgnWorkspace) -> TactileSyncSnapshot:
        """Use Section-8 GameTree projection; never replay PGN inside Section 10."""

        if not isinstance(workspace, PgnWorkspace):
            raise TypeError("workspace must be PgnWorkspace")
        view = workspace.view()
        try:
            scene = self._graphics.on_gametree_navigation(
                workspace.current_game(),
                workspace.cursor,
            )
        except Exception as exc:
            self._fail(
                TactileSyncSource.PGN,
                source_revision=view.content_revision,
            )
            raise TactileSyncError("PGN tactile refresh failed") from exc
        return self._accept_scene(
            scene,
            source=TactileSyncSource.PGN,
            source_revision=view.content_revision,
        )

    def sync_book_view(self, view: BookBoardView) -> TactileSyncSnapshot:
        if not isinstance(view, BookBoardView):
            raise TypeError("view must be BookBoardView")
        return self._publish_position(
            view.current_fen,
            source=TactileSyncSource.BOOK,
            source_revision=view.revision,
        )

    def sync_book(self, workflow: BookBoardWorkflow) -> TactileSyncSnapshot:
        if not isinstance(workflow, BookBoardWorkflow):
            raise TypeError("workflow must be BookBoardWorkflow")
        return self.sync_book_view(workflow.view())

    def sync_training(self, session: ExerciseSession) -> TactileSyncSnapshot:
        if not isinstance(session, ExerciseSession):
            raise TypeError("session must be ExerciseSession")
        return self._publish_position(
            session.current_fen,
            source=TactileSyncSource.TRAINING,
            source_revision=session.attempts,
        )

    def dispatch(
        self,
        command: TactileSyncCommand | str,
        payload: object = None,
    ) -> TactileSyncSnapshot:
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
            if not isinstance(payload, PgnWorkspace):
                raise TactileSyncError("tactile.refresh_pgn requires PgnWorkspace")
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
