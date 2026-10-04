from __future__ import annotations

"""Presentation-neutral engine assistance for Books, Training, and Teacher flows.

This module reuses ``AnalysisService``. It does not own chess legality,
canonical board state, lesson presentation state, or a second engine provider.
It only binds existing semantic contexts to engine analysis and projects the
result according to an explicit audience-visibility policy.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from .analysis_service import AnalysisLine, AnalysisResult, AnalysisService
from .bookdocument import Diagram, Exercise as BookExercise, Position, VariationTree
from .engine_ports import EngineContractError, EngineContractErrorCode
from .input_limits import MAX_FEN_CHARS
from .training import ExerciseSession


class EngineVisibility(str, Enum):
    """Who may receive engine-derived answer material."""

    VISIBLE_TO_TEACHER = "visible_to_teacher"
    VISIBLE_TO_STUDENT = "visible_to_student"
    HIDDEN = "hidden"


def _visibility(value: EngineVisibility | str) -> EngineVisibility:
    if isinstance(value, EngineVisibility):
        return value
    if type(value) is not str:
        raise EngineContractError(
            "engine visibility must be text or EngineVisibility",
            code=EngineContractErrorCode.INVALID_REQUEST,
        )
    token = value.strip().lower()
    try:
        return EngineVisibility(token)
    except ValueError as exc:
        raise EngineContractError(
            "unsupported engine visibility",
            code=EngineContractErrorCode.INVALID_REQUEST,
        ) from exc


def _request_fen(value: object) -> str:
    # Reuse the canonical raw FEN representation budget. Exact built-in text is
    # required before len/strip so provider-defined string hooks cannot execute.
    if type(value) is not str or len(value) > MAX_FEN_CHARS:
        raise EngineContractError(
            "assisted analysis FEN must be non-empty text",
            code=EngineContractErrorCode.INVALID_REQUEST,
        )
    normalized = value.strip()
    if not normalized:
        raise EngineContractError(
            "assisted analysis FEN must be non-empty text",
            code=EngineContractErrorCode.INVALID_REQUEST,
        )
    return normalized


def _context_revision(value: object, *, name: str) -> str | int:
    if type(value) is int:
        if value < 0:
            raise EngineContractError(
                f"{name} must be a non-negative integer or non-empty text",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        return value
    if type(value) is str:
        token = value.strip()
        if not token or len(token) > 256:
            raise EngineContractError(
                f"{name} must be bounded non-empty text",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        return token
    raise EngineContractError(
        f"{name} must be a non-negative integer or non-empty text",
        code=EngineContractErrorCode.INVALID_REQUEST,
    )


@dataclass(frozen=True, slots=True)
class AudienceAnalysisResult:
    """Engine result after teacher/student visibility projection.

    Raw provider exception text is intentionally not exposed here. A
    presentation adapter remains responsible for legality-aware SAN and spoken
    language projection.
    """

    fen: str
    generation: int
    visibility: EngineVisibility
    stale: bool
    teacher_lines: tuple[AnalysisLine, ...] = ()
    student_lines: tuple[AnalysisLine, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        if type(self.fen) is not str or len(self.fen) > MAX_FEN_CHARS:
            raise EngineContractError(
                "audience analysis FEN must be non-empty text",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        normalized_fen = self.fen.strip()
        if not normalized_fen:
            raise EngineContractError(
                "audience analysis FEN must be non-empty text",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if type(self.generation) is not int or self.generation < 0:
            raise EngineContractError(
                "audience analysis generation must be a non-negative integer",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if not isinstance(self.visibility, EngineVisibility):
            raise EngineContractError(
                "audience analysis visibility is invalid",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if type(self.stale) is not bool:
            raise EngineContractError(
                "audience analysis stale flag must be boolean",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        for name, lines in (
            ("teacher_lines", self.teacher_lines),
            ("student_lines", self.student_lines),
        ):
            if not isinstance(lines, tuple) or any(
                not isinstance(line, AnalysisLine) for line in lines
            ):
                raise EngineContractError(
                    f"audience analysis {name} must be an AnalysisLine tuple",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
        if self.error is not None and (
            not isinstance(self.error, str) or not self.error.strip()
        ):
            raise EngineContractError(
                "audience analysis error must be non-empty text or None",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if self.stale and (self.teacher_lines or self.student_lines or self.error):
            raise EngineContractError(
                "stale audience analysis cannot expose lines or errors",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if self.error is not None and (self.teacher_lines or self.student_lines):
            raise EngineContractError(
                "failed audience analysis cannot expose lines",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if self.visibility is EngineVisibility.HIDDEN and (
            self.teacher_lines or self.student_lines
        ):
            raise EngineContractError(
                "hidden engine analysis cannot expose answer lines",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if (
            self.visibility is EngineVisibility.VISIBLE_TO_TEACHER
            and self.student_lines
        ):
            raise EngineContractError(
                "teacher-only engine analysis cannot expose student lines",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        object.__setattr__(self, "fen", normalized_fen)

    @property
    def available_to_teacher(self) -> bool:
        return bool(self.teacher_lines)

    @property
    def available_to_student(self) -> bool:
        return bool(self.student_lines)


class EngineAssistedWorkflowService:
    """Bind existing Book/Training/Teacher contexts to ``AnalysisService``.

    The service never submits training moves, edits BookDocument blocks, or
    owns teacher presentation state. Context revisions are sampled before and
    after analysis; a changed context suppresses the completed answer as stale.
    """

    SAFE_ERROR = "engine analysis unavailable"

    def __init__(self, analysis_service: AnalysisService) -> None:
        # AnalysisService is the single canonical analysis coordinator. Engine
        # providers are injected through its factory; subclasses here would create
        # a second overridable analysis authority above that provider seam.
        if type(analysis_service) is not AnalysisService:
            raise EngineContractError(
                "analysis_service must be AnalysisService",
                code=EngineContractErrorCode.INVALID_PROVIDER,
            )
        self._analysis = analysis_service

    @staticmethod
    def _project(
        result: AnalysisResult,
        visibility: EngineVisibility | str,
        *,
        force_stale: bool = False,
    ) -> AudienceAnalysisResult:
        policy = _visibility(visibility)
        if force_stale or result.stale:
            return AudienceAnalysisResult(result.fen, result.generation, policy, True)
        if result.error is not None:
            return AudienceAnalysisResult(
                result.fen,
                result.generation,
                policy,
                False,
                error=EngineAssistedWorkflowService.SAFE_ERROR,
            )
        if policy is EngineVisibility.HIDDEN:
            return AudienceAnalysisResult(result.fen, result.generation, policy, False)
        if policy is EngineVisibility.VISIBLE_TO_TEACHER:
            return AudienceAnalysisResult(
                result.fen,
                result.generation,
                policy,
                False,
                teacher_lines=result.lines,
            )
        return AudienceAnalysisResult(
            result.fen,
            result.generation,
            policy,
            False,
            teacher_lines=result.lines,
            student_lines=result.lines,
        )

    def invalidate(self) -> int:
        """Invalidate an in-flight assisted request after context replacement."""

        return self._analysis.invalidate()

    def analyze_training(
        self,
        session: ExerciseSession,
        fen: str,
        *,
        visibility: EngineVisibility | str = EngineVisibility.VISIBLE_TO_TEACHER,
        multipv: int = 1,
        depth: int = 12,
    ) -> AudienceAnalysisResult:
        """Analyze the canonical current FEN without mutating training progress."""

        # ExerciseSession owns mutable Training progress. Reject subclasses
        # before snapshot() can resolve provider-defined state hooks.
        if type(session) is not ExerciseSession:
            raise EngineContractError(
                "training session must be ExerciseSession",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        # Reject malformed/oversized FEN before sampling mutable Training state.
        # A rejected request must not execute session/provider work.
        normalized_fen = _request_fen(fen)
        policy = _visibility(visibility)
        before = session.snapshot()
        result = self._analysis.analyze(
            normalized_fen, multipv=multipv, depth=depth
        )
        after = session.snapshot()
        return self._project(result, policy, force_stale=after != before)

    @staticmethod
    def book_block_fen(block: object) -> str:
        """Return only an explicit semantic FEN; never derive chess state."""

        # Keep analysis input on the closed canonical Book semantic roots. Reject
        # subclasses before attribute access so provider-defined Book DTO hooks
        # cannot become an alternate FEN authority above BookDocument/BookReader.
        if type(block) in (Position, Diagram):
            return _request_fen(block.fen)
        if type(block) is VariationTree:
            return _request_fen(block.root_fen)
        if type(block) is BookExercise:
            return _request_fen(block.fen)
        raise EngineContractError(
            "book block does not carry an explicit analyzable FEN",
            code=EngineContractErrorCode.INVALID_REQUEST,
        )

    def analyze_book_block(
        self,
        block: object,
        *,
        visibility: EngineVisibility | str = EngineVisibility.VISIBLE_TO_TEACHER,
        multipv: int = 5,
        depth: int = 16,
    ) -> AudienceAnalysisResult:
        """Analyze Position/Diagram/VariationTree/Exercise without editing it."""

        policy = _visibility(visibility)
        before_fen = self.book_block_fen(block)
        result = self._analysis.analyze(before_fen, multipv=multipv, depth=depth)
        try:
            after_fen = self.book_block_fen(block)
        except EngineContractError:
            after_fen = None
        return self._project(result, policy, force_stale=after_fen != before_fen)

    def analyze_teacher(
        self,
        fen: str,
        *,
        visibility: EngineVisibility | str,
        context_revision: str | int,
        revision_provider: Callable[[], object],
        multipv: int = 5,
        depth: int = 16,
    ) -> AudienceAnalysisResult:
        """Analyze a lesson position while rejecting stale lesson-state answers.

        ``revision_provider`` belongs to the canonical lesson/session owner.
        DEV3 reads it but never stores or mutates teacher presentation state.
        """

        normalized_fen = _request_fen(fen)
        if not callable(revision_provider):
            raise EngineContractError(
                "teacher revision_provider must be callable",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        policy = _visibility(visibility)
        expected = _context_revision(
            context_revision, name="teacher context revision"
        )
        try:
            before = _context_revision(
                revision_provider(), name="teacher current revision"
            )
        except EngineContractError:
            raise
        except Exception as exc:
            raise EngineContractError(
                "teacher current revision is unavailable",
                code=EngineContractErrorCode.INVALID_REQUEST,
            ) from exc

        if before != expected:
            return AudienceAnalysisResult(normalized_fen, 0, policy, True)

        result = self._analysis.analyze(
            normalized_fen, multipv=multipv, depth=depth
        )
        try:
            after = _context_revision(
                revision_provider(), name="teacher current revision"
            )
        except Exception:
            return self._project(result, policy, force_stale=True)
        return self._project(result, policy, force_stale=after != expected)
