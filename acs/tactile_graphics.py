from __future__ import annotations

"""Vendor-neutral refreshable tactile graphics core.

Section 8 stops at the semantic tactile-scene boundary. Physical device
discovery/capabilities belong to Section 9; Books/Training synchronization to
Section 10; tactile input/routing to Section 11.

This module owns no chess rules. Position rendering consumes canonical
PositionState; GameTree navigation is projected through the existing canonical
legality service.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from .gametree import PgnGame
from .gametree_legality import validate_game_legality
from .gametree_navigation import GameTreeCursor, MoveAddress, validate_cursor
from .position_editor import PositionState, PositionValidationError, VALID_PIECES
from .squares import FILES, parse_square, square_name


class TactileGraphicsError(ValueError):
    """Stable Section-8 boundary failure."""


class TactileSceneSource(str, Enum):
    POSITION_NAVIGATION = "position_navigation"
    GAMETREE_NAVIGATION = "gametree_navigation"
    EXPLORATION = "exploration"


def _canonical_square(value: object, *, allow_none: bool = False) -> str | None:
    if allow_none and value is None:
        return None
    if type(value) is not str or value != value.strip():
        raise TactileGraphicsError("tactile square must be canonical text")
    try:
        index = parse_square(value)
    except (TypeError, ValueError) as exc:
        raise TactileGraphicsError("tactile square is invalid") from exc
    canonical = square_name(index)
    if canonical != value:
        raise TactileGraphicsError(
            "tactile square must use canonical lowercase algebraic text"
        )
    return canonical


# White-side semantic display order. Device orientation transforms are later
# adapter/profile work, not part of this vendor-neutral core.
TACTILE_BOARD_ORDER = tuple(
    f"{file_name}{rank}"
    for rank in range(8, 0, -1)
    for file_name in FILES
)


@dataclass(frozen=True, slots=True)
class TactileCell:
    """One semantic tactile chess square; no vendor pin encoding lives here."""

    square: str
    piece: str | None
    focused: bool = False

    def __post_init__(self) -> None:
        _canonical_square(self.square)
        if self.piece is not None and (
            type(self.piece) is not str or self.piece not in VALID_PIECES
        ):
            raise TactileGraphicsError("tactile cell contains an invalid piece")
        if type(self.focused) is not bool:
            raise TactileGraphicsError("tactile focus flag must be boolean")


def _focus_order(focus_square: str) -> tuple[str, ...]:
    index = parse_square(focus_square)
    file_index, rank_index = index % 8, index // 8
    result: list[str] = []
    for rank_no in range(min(7, rank_index + 1), max(-1, rank_index - 2), -1):
        for file_no in range(max(0, file_index - 1), min(7, file_index + 1) + 1):
            result.append(square_name(rank_no * 8 + file_no))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class TactileScene:
    """Immutable vendor-neutral full-board plus local-focus tactile scene."""

    position_fen: str
    full_board: tuple[TactileCell, ...]
    focus_square: str | None
    focus_view: tuple[TactileCell, ...]
    sequence: int
    source: TactileSceneSource

    def __post_init__(self) -> None:
        if type(self.position_fen) is not str:
            raise TactileGraphicsError("tactile scene position must be FEN text")
        try:
            position = PositionState.from_fen(self.position_fen)
            canonical_fen = position.to_fen()
        except (PositionValidationError, TypeError, ValueError) as exc:
            raise TactileGraphicsError(
                "tactile scene position is not a canonical Position"
            ) from exc
        if canonical_fen != self.position_fen:
            raise TactileGraphicsError("tactile scene FEN must already be canonical")

        if type(self.full_board) is not tuple or len(self.full_board) != 64:
            raise TactileGraphicsError(
                "tactile full board must contain exactly 64 cells"
            )
        if any(type(cell) is not TactileCell for cell in self.full_board):
            raise TactileGraphicsError(
                "tactile full board must contain TactileCell values"
            )
        if tuple(cell.square for cell in self.full_board) != TACTILE_BOARD_ORDER:
            raise TactileGraphicsError(
                "tactile full board must use canonical white-side display order"
            )

        focus = _canonical_square(self.focus_square, allow_none=True)
        for cell in self.full_board:
            if cell.piece != position.piece_at(cell.square):
                raise TactileGraphicsError(
                    "tactile full board does not match the canonical Position"
                )
            if cell.focused != (cell.square == focus):
                raise TactileGraphicsError(
                    "tactile full-board focus marker is inconsistent"
                )

        if type(self.focus_view) is not tuple or any(
            type(cell) is not TactileCell for cell in self.focus_view
        ):
            raise TactileGraphicsError(
                "tactile focus view must be a tuple of TactileCell values"
            )
        expected_squares = () if focus is None else _focus_order(focus)
        if tuple(cell.square for cell in self.focus_view) != expected_squares:
            raise TactileGraphicsError(
                "tactile focus view does not match the focused square"
            )
        by_square = {cell.square: cell for cell in self.full_board}
        if self.focus_view != tuple(by_square[square] for square in expected_squares):
            raise TactileGraphicsError(
                "tactile focus view must reuse canonical full-board cells"
            )

        if type(self.sequence) is not int or self.sequence < 0:
            raise TactileGraphicsError(
                "tactile scene sequence must be a non-negative integer"
            )
        try:
            source = TactileSceneSource(self.source)
        except (TypeError, ValueError) as exc:
            raise TactileGraphicsError("unsupported tactile scene source") from exc
        object.__setattr__(self, "source", source)


@runtime_checkable
class TactileDisplayPort(Protocol):
    """Vendor-neutral output port. Physical-device details are Section 9."""

    def present(self, scene: TactileScene) -> None:
        """Present one complete immutable semantic scene."""


class TactileSimulator:
    """In-memory simulator/mock display used without physical hardware."""

    def __init__(self) -> None:
        self._history: list[TactileScene] = []

    @property
    def current_scene(self) -> TactileScene | None:
        return self._history[-1] if self._history else None

    @property
    def history(self) -> tuple[TactileScene, ...]:
        return tuple(self._history)

    def present(self, scene: TactileScene) -> None:
        if type(scene) is not TactileScene:
            raise TactileGraphicsError(
                "tactile display accepts only canonical TactileScene values"
            )
        self._history.append(scene)


def project_tactile_scene(
    position: PositionState,
    *,
    focus_square: str | None = None,
    sequence: int = 0,
    source: TactileSceneSource = TactileSceneSource.POSITION_NAVIGATION,
) -> TactileScene:
    """Project a detached canonical Position without adding chess rules."""

    if type(position) is not PositionState:
        raise TactileGraphicsError(
            "tactile projection requires the canonical PositionState"
        )
    try:
        detached = PositionState.from_fen(position.to_fen())
    except (PositionValidationError, TypeError, ValueError) as exc:
        raise TactileGraphicsError("canonical Position cannot be projected") from exc

    focus = _canonical_square(focus_square, allow_none=True)
    cells = tuple(
        TactileCell(
            square=square,
            piece=detached.piece_at(square),
            focused=(square == focus),
        )
        for square in TACTILE_BOARD_ORDER
    )
    by_square = {cell.square: cell for cell in cells}
    focus_view = (
        ()
        if focus is None
        else tuple(by_square[square] for square in _focus_order(focus))
    )
    return TactileScene(
        position_fen=detached.to_fen(),
        full_board=cells,
        focus_square=focus,
        focus_view=focus_view,
        sequence=sequence,
        source=source,
    )


def position_for_gametree_cursor(
    game: PgnGame,
    cursor: GameTreeCursor,
) -> PositionState:
    """Resolve a cursor through the existing canonical GameTree legality service.

    Section 8 never parses SAN or applies moves itself. If the existing legality
    projection cannot prove the requested cursor position, tactile output fails
    closed rather than guessing.
    """

    if not isinstance(game, PgnGame):
        raise TactileGraphicsError("GameTree tactile refresh requires a PgnGame")
    if not isinstance(cursor, GameTreeCursor):
        raise TactileGraphicsError(
            "GameTree tactile refresh requires a GameTreeCursor"
        )
    try:
        validate_cursor(game, cursor)
        report = validate_game_legality(game)
    except (TypeError, ValueError) as exc:
        raise TactileGraphicsError(
            "GameTree cursor cannot be projected safely"
        ) from exc

    if report.start_fen is None:
        raise TactileGraphicsError(
            "GameTree has no canonical start position for tactile refresh"
        )

    projections = {}
    for projection in report.moves:
        if projection.address in projections:
            raise TactileGraphicsError(
                "GameTree legality projection contains a duplicate address"
            )
        projections[projection.address] = projection

    if cursor.next_move_index == 0:
        if not cursor.line_path:
            fen = report.start_fen
        else:
            owner = cursor.line_path[-1]
            parent_address = MoveAddress(
                cursor.line_path[:-1],
                owner.parent_move_index,
            )
            projection = projections.get(parent_address)
            if projection is None:
                raise TactileGraphicsError(
                    "GameTree branch start position is not provable"
                )
            fen = projection.fen_before
    else:
        previous_address = MoveAddress(
            cursor.line_path,
            cursor.next_move_index - 1,
        )
        projection = projections.get(previous_address)
        if projection is None:
            raise TactileGraphicsError(
                "GameTree cursor position is not provable"
            )
        fen = projection.fen_after

    try:
        return PositionState.from_fen(fen)
    except (PositionValidationError, TypeError, ValueError) as exc:
        raise TactileGraphicsError(
            "GameTree legality projection did not publish a canonical Position"
        ) from exc


class TactileGraphicsController:
    """Refresh coordinator with fail-closed, non-mutating exploration."""

    def __init__(self, display: TactileDisplayPort) -> None:
        presenter = getattr(display, "present", None)
        if not callable(presenter):
            raise TypeError("display must implement TactileDisplayPort.present")
        self._display = display
        self._sequence = 0
        self._scene: TactileScene | None = None

    @property
    def current_scene(self) -> TactileScene | None:
        return self._scene

    def refresh_position(
        self,
        position: PositionState,
        *,
        focus_square: str | None = None,
    ) -> TactileScene:
        return self._publish(
            position,
            focus_square=focus_square,
            source=TactileSceneSource.POSITION_NAVIGATION,
        )

    def on_position_navigation(
        self,
        position: PositionState,
        *,
        focus_square: str | None = None,
    ) -> TactileScene:
        """Event boundary for canonical Position navigation."""

        return self.refresh_position(position, focus_square=focus_square)

    def on_gametree_navigation(
        self,
        game: PgnGame,
        cursor: GameTreeCursor,
        *,
        focus_square: str | None = None,
    ) -> TactileScene:
        """Refresh after every canonical GameTree cursor navigation event."""

        position = position_for_gametree_cursor(game, cursor)
        return self._publish(
            position,
            focus_square=focus_square,
            source=TactileSceneSource.GAMETREE_NAVIGATION,
        )

    def explore(self, focus_square: str) -> TactileScene:
        """Move tactile focus only; never mutate the originating chess Position."""

        if self._scene is None:
            raise TactileGraphicsError(
                "tactile exploration requires an existing scene"
            )
        focus = _canonical_square(focus_square)
        prior_fen = self._scene.position_fen
        try:
            detached = PositionState.from_fen(prior_fen)
        except (PositionValidationError, TypeError, ValueError) as exc:
            raise TactileGraphicsError(
                "current tactile scene no longer has a canonical Position"
            ) from exc

        candidate = project_tactile_scene(
            detached,
            focus_square=focus,
            sequence=self._sequence + 1,
            source=TactileSceneSource.EXPLORATION,
        )
        if candidate.position_fen != prior_fen:
            raise TactileGraphicsError(
                "tactile exploration attempted to mutate the Position"
            )
        self._present_and_commit(candidate)
        return candidate

    def _publish(
        self,
        position: PositionState,
        *,
        focus_square: str | None,
        source: TactileSceneSource,
    ) -> TactileScene:
        candidate = project_tactile_scene(
            position,
            focus_square=focus_square,
            sequence=self._sequence + 1,
            source=source,
        )
        self._present_and_commit(candidate)
        return candidate

    def _present_and_commit(self, candidate: TactileScene) -> None:
        # Advance semantic state only after the output port accepts the scene.
        self._display.present(candidate)
        self._scene = candidate
        self._sequence = candidate.sequence
