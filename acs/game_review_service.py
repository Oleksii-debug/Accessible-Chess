from __future__ import annotations

"""Presentation-neutral bounded post-game engine review.

The caller supplies stable domain references and explicit canonical FENs. This
service does not reconstruct chess state, mutate GameTree/StudentProgress, or
persist engine PV/score material. It only produces transient derived
per-position evaluation metadata with cooperative cancellation between engine
requests.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import Lock

from .analysis_service import AnalysisService
from .engine_ports import EngineContractError, EngineContractErrorCode


GAME_REVIEW_MAX_POSITIONS = 512
GAME_REVIEW_MAX_ID_LENGTH = 256
GAME_REVIEW_MAX_FEN_LENGTH = 512
GAME_REVIEW_SAFE_ERROR = "engine analysis unavailable"


def _bounded_id(value: object, *, name: str) -> str:
    if type(value) is not str:
        raise EngineContractError(
            f"{name} must be text", code=EngineContractErrorCode.INVALID_REQUEST
        )
    token = value.strip()
    if not token or len(token) > GAME_REVIEW_MAX_ID_LENGTH:
        raise EngineContractError(
            f"{name} must be bounded non-empty text",
            code=EngineContractErrorCode.INVALID_REQUEST,
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in token):
        raise EngineContractError(
            f"{name} must not contain control characters",
            code=EngineContractErrorCode.INVALID_REQUEST,
        )
    return token


def _fen(value: object) -> str:
    if type(value) is not str:
        raise EngineContractError(
            "review FEN must be text", code=EngineContractErrorCode.INVALID_REQUEST
        )
    token = value.strip()
    if not token or len(token) > GAME_REVIEW_MAX_FEN_LENGTH:
        raise EngineContractError(
            "review FEN must be bounded non-empty text",
            code=EngineContractErrorCode.INVALID_REQUEST,
        )
    return token


def _non_negative_int(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise EngineContractError(
            f"{name} must be an integer",
            code=EngineContractErrorCode.INVALID_REQUEST,
        )
    if value < 0:
        raise EngineContractError(
            f"{name} must be non-negative",
            code=EngineContractErrorCode.INVALID_REQUEST,
        )
    return value


class GameReviewStatus(str, Enum):
    ANALYZED = "analyzed"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class GameReviewPosition:
    """One explicit position linked to existing student/session/game identity."""

    student_id: str
    session_id: str
    game_ref: str
    source_revision: str
    position_id: str
    ply: int
    fen: str

    def __post_init__(self) -> None:
        for name in (
            "student_id",
            "session_id",
            "game_ref",
            "source_revision",
            "position_id",
        ):
            object.__setattr__(
                self, name, _bounded_id(getattr(self, name), name=name)
            )
        object.__setattr__(self, "ply", _non_negative_int(self.ply, name="ply"))
        object.__setattr__(self, "fen", _fen(self.fen))


@dataclass(frozen=True, slots=True)
class GameReviewPoint:
    """Transient engine-derived metadata for one reviewed position.

    No PV is carried so this DTO can never be accidentally serialized as a
    solution line by StudentProgress. Score semantics remain engine-derived
    analytics, not canonical chess truth.
    """

    student_id: str
    session_id: str
    game_ref: str
    source_revision: str
    position_id: str
    ply: int
    fen: str
    status: GameReviewStatus
    generation: int
    depth: int | None = None
    score_kind: str | None = None
    score_value: int | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        source = GameReviewPosition(
            self.student_id,
            self.session_id,
            self.game_ref,
            self.source_revision,
            self.position_id,
            self.ply,
            self.fen,
        )
        for name in (
            "student_id",
            "session_id",
            "game_ref",
            "source_revision",
            "position_id",
            "ply",
            "fen",
        ):
            object.__setattr__(self, name, getattr(source, name))
        if not isinstance(self.status, GameReviewStatus):
            raise EngineContractError(
                "review status is invalid", code=EngineContractErrorCode.INVALID_RESULT
            )
        if type(self.generation) is not int or self.generation < 0:
            raise EngineContractError(
                "review generation must be a non-negative integer",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        analyzed = self.status is GameReviewStatus.ANALYZED
        if analyzed:
            if type(self.depth) is not int or self.depth < 0:
                raise EngineContractError(
                    "analyzed review depth is invalid",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
            if self.score_kind not in {"cp", "mate"}:
                raise EngineContractError(
                    "analyzed review score kind is invalid",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
            if type(self.score_value) is not int:
                raise EngineContractError(
                    "analyzed review score value is invalid",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
            if self.error is not None:
                raise EngineContractError(
                    "analyzed review cannot carry an error",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
        else:
            if (
                self.depth is not None
                or self.score_kind is not None
                or self.score_value is not None
            ):
                raise EngineContractError(
                    "non-analyzed review cannot carry evaluation data",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
            if self.status is GameReviewStatus.UNAVAILABLE:
                if self.error != GAME_REVIEW_SAFE_ERROR:
                    raise EngineContractError(
                        "unavailable review must use the safe error",
                        code=EngineContractErrorCode.INVALID_RESULT,
                    )
            elif self.error is not None:
                raise EngineContractError(
                    "stale review cannot carry an error",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )


@dataclass(frozen=True, slots=True)
class GameReviewBatch:
    points: tuple[GameReviewPoint, ...]
    cancelled: bool
    requested_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.points, tuple) or any(
            not isinstance(point, GameReviewPoint) for point in self.points
        ):
            raise EngineContractError(
                "review batch points must be a GameReviewPoint tuple",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if type(self.cancelled) is not bool:
            raise EngineContractError(
                "review batch cancelled flag must be boolean",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if (
            type(self.requested_count) is not int
            or not 0 <= self.requested_count <= GAME_REVIEW_MAX_POSITIONS
        ):
            raise EngineContractError(
                "review batch requested_count is invalid",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if len(self.points) > self.requested_count:
            raise EngineContractError(
                "review batch cannot contain more results than requests",
                code=EngineContractErrorCode.INVALID_RESULT,
            )


class GameReviewService:
    """Run a bounded sequential review through the shared AnalysisService.

    A service admits at most one batch at a time. ``AnalysisService`` generations
    are intentionally global to the shared provider; allowing two review batches
    to interleave would let one batch invalidate another. A non-blocking busy
    failure prevents hidden work queues and makes this ownership explicit.
    """

    def __init__(self, analysis_service: AnalysisService) -> None:
        if not isinstance(analysis_service, AnalysisService):
            raise EngineContractError(
                "analysis_service must be AnalysisService",
                code=EngineContractErrorCode.INVALID_PROVIDER,
            )
        self._analysis = analysis_service
        self._batch_lock = Lock()

    @staticmethod
    def _cancelled(provider: Callable[[], object] | None) -> bool:
        if provider is None:
            return False
        if not callable(provider):
            raise EngineContractError(
                "cancel_provider must be callable or None",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        try:
            value = provider()
        except Exception as exc:
            raise EngineContractError(
                "review cancellation state is unavailable",
                code=EngineContractErrorCode.INVALID_REQUEST,
            ) from exc
        if type(value) is not bool:
            raise EngineContractError(
                "cancel_provider must return boolean",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        return value

    @staticmethod
    def _validate_batch(positions: tuple[GameReviewPosition, ...]) -> None:
        if not positions:
            return
        first = positions[0]
        scope = (
            first.student_id,
            first.session_id,
            first.game_ref,
            first.source_revision,
        )
        position_ids: set[str] = set()
        for position in positions:
            if (
                position.student_id,
                position.session_id,
                position.game_ref,
                position.source_revision,
            ) != scope:
                raise EngineContractError(
                    "review batch positions must share one game scope",
                    code=EngineContractErrorCode.INVALID_REQUEST,
                )
            if position.position_id in position_ids:
                raise EngineContractError(
                    "review batch position_id values must be unique",
                    code=EngineContractErrorCode.INVALID_REQUEST,
                )
            position_ids.add(position.position_id)

    def review(
        self,
        positions: tuple[GameReviewPosition, ...],
        *,
        depth: int = 16,
        cancel_provider: Callable[[], object] | None = None,
    ) -> GameReviewBatch:
        if not isinstance(positions, tuple):
            raise EngineContractError(
                "review positions must be a tuple",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        if len(positions) > GAME_REVIEW_MAX_POSITIONS:
            raise EngineContractError(
                "review batch exceeds maximum position count",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        if any(not isinstance(position, GameReviewPosition) for position in positions):
            raise EngineContractError(
                "review positions must contain GameReviewPosition values",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        self._validate_batch(positions)
        if type(depth) is not int or not 1 <= depth <= 40:
            raise EngineContractError(
                "review depth must be an integer between 1 and 40",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        if cancel_provider is not None and not callable(cancel_provider):
            raise EngineContractError(
                "cancel_provider must be callable or None",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        if not self._batch_lock.acquire(blocking=False):
            raise EngineContractError(
                "game review service is busy",
                code=EngineContractErrorCode.INVALID_SESSION,
            )

        try:
            out: list[GameReviewPoint] = []
            for position in positions:
                if self._cancelled(cancel_provider):
                    self._analysis.invalidate()
                    return GameReviewBatch(tuple(out), True, len(positions))

                result = self._analysis.analyze(position.fen, multipv=1, depth=depth)

                # Cancellation that arrives while the provider is blocked suppresses
                # that just-completed answer and invalidates the shared generation.
                if self._cancelled(cancel_provider):
                    self._analysis.invalidate()
                    return GameReviewBatch(tuple(out), True, len(positions))

                common = dict(
                    student_id=position.student_id,
                    session_id=position.session_id,
                    game_ref=position.game_ref,
                    source_revision=position.source_revision,
                    position_id=position.position_id,
                    ply=position.ply,
                    fen=position.fen,
                    generation=result.generation,
                )
                if result.stale:
                    out.append(GameReviewPoint(**common, status=GameReviewStatus.STALE))
                    continue
                if result.error is not None or not result.lines:
                    out.append(
                        GameReviewPoint(
                            **common,
                            status=GameReviewStatus.UNAVAILABLE,
                            error=GAME_REVIEW_SAFE_ERROR,
                        )
                    )
                    continue
                line = result.lines[0]
                out.append(
                    GameReviewPoint(
                        **common,
                        status=GameReviewStatus.ANALYZED,
                        depth=line.depth,
                        score_kind=line.score_kind,
                        score_value=line.score_value,
                    )
                )

            return GameReviewBatch(tuple(out), False, len(positions))
        finally:
            self._batch_lock.release()
