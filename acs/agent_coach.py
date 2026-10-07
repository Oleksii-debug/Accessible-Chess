from __future__ import annotations

"""Evidence-first AI Coach workflows over canonical Accessible Chess tools.

This module owns no chess rules, engine, Library, GameTree or Media truth.  It
collects bounded evidence through registered application tools and asks the one
Universal Chess Agent to explain only that evidence.  Optional Media navigation
remains an explicit, per-run capability.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .agent_books_training_tools import AgentBooksTrainingTools
from .agent_gametree_tools import register_gametree_tools
from .agent_tools import ToolCall, ToolExecutor, ToolRisk
from .universal_chess_agent import AgentRunResult, UniversalChessAgentRuntime


class AgentCoachError(RuntimeError):
    pass


class CoachMode(StrEnum):
    POSITION = "position"
    GAME_REVIEW = "game_review"
    TRAINING = "training"
    MEDIA = "media"


@dataclass(frozen=True, slots=True)
class CoachRequest:
    request_id: str
    mode: CoachMode
    question: str
    allow_media_navigation: bool = False
    library_limit: int = 8

    def __post_init__(self) -> None:
        if (
            type(self.request_id) is not str
            or not self.request_id
            or self.request_id != self.request_id.strip()
            or len(self.request_id) > 180
        ):
            raise ValueError("request_id must be bounded canonical text")
        if type(self.mode) is not CoachMode:
            raise TypeError("mode must be CoachMode")
        if (
            type(self.question) is not str
            or not self.question.strip()
            or len(self.question) > 8000
            or "\x00" in self.question
        ):
            raise ValueError("question must be bounded non-empty text")
        if type(self.allow_media_navigation) is not bool:
            raise TypeError("allow_media_navigation must be boolean")
        if type(self.library_limit) is not int or not 1 <= self.library_limit <= 25:
            raise ValueError("library_limit must be between 1 and 25")


@dataclass(frozen=True, slots=True)
class CoachEvidence:
    tool_id: str
    output: object


@dataclass(frozen=True, slots=True)
class CoachResult:
    mode: CoachMode
    text: str
    evidence: tuple[CoachEvidence, ...]
    model_calls: int
    model_tool_calls: int


def register_coach_read_tools(
    executor: ToolExecutor,
    *,
    workspace_provider=None,
    application_snapshot_provider=None,
) -> tuple[str, ...]:
    """Compose Section-23 read surfaces before constructing the Agent runtime.

    Existing board/engine/library/media tools stay owned by ChessAgentToolRegistry.
    This helper adds only the already-qualified GameTree and Books/Training read
    adapters required by Coach workflows.
    """
    if type(executor) is not ToolExecutor:
        raise TypeError("executor must be ToolExecutor")
    before = {spec.tool_id for spec in executor.specs()}
    if workspace_provider is not None:
        register_gametree_tools(executor, workspace_provider)
    if application_snapshot_provider is not None:
        AgentBooksTrainingTools(application_snapshot_provider).register(executor)
    after = {spec.tool_id for spec in executor.specs()}
    return tuple(sorted(after - before))


class AgentCoachWorkflow:
    """Compose grounded coaching from existing typed application services."""

    def __init__(
        self,
        *,
        runtime: UniversalChessAgentRuntime,
        tools: ToolExecutor,
    ) -> None:
        if type(runtime) is not UniversalChessAgentRuntime:
            raise TypeError("runtime must be UniversalChessAgentRuntime")
        if type(tools) is not ToolExecutor:
            raise TypeError("tools must be ToolExecutor")
        if runtime.tools is not tools:
            raise ValueError("runtime and coach must share one ToolExecutor authority")
        self.runtime = runtime
        self.tools = tools

    def _spec(self, tool_id: str):
        for spec in self.tools.specs():
            if spec.tool_id == tool_id:
                return spec
        raise AgentCoachError(f"required tool is unavailable: {tool_id}")

    async def _read(
        self,
        *,
        request_id: str,
        ordinal: int,
        tool_id: str,
        arguments: Mapping[str, object] | None = None,
    ) -> CoachEvidence:
        spec = self._spec(tool_id)
        if spec.risk is not ToolRisk.READ_ONLY:
            raise AgentCoachError(f"grounding tool is not read-only: {tool_id}")
        result = await self.tools.execute(
            ToolCall(
                call_id=f"{request_id}:evidence:{ordinal}",
                tool_id=tool_id,
                arguments={} if arguments is None else arguments,
                task_id=request_id,
            )
        )
        if not result.ok:
            raise AgentCoachError(f"required evidence failed: {tool_id}")
        return CoachEvidence(tool_id=tool_id, output=result.output)

    @staticmethod
    def _library_query_from_game(evidence: CoachEvidence, *, limit: int) -> dict[str, object]:
        query: dict[str, object] = {"limit": limit}
        if type(evidence.output) is not dict:
            return query
        game = evidence.output.get("game")
        if type(game) is not dict:
            return query
        white = game.get("white")
        black = game.get("black")
        event = game.get("event")
        if type(white) is str and white.strip():
            query["player"] = white.strip()
        elif type(black) is str and black.strip():
            query["player"] = black.strip()
        if type(event) is str and event.strip():
            query["event"] = event.strip()
        return query

    async def _collect(self, request: CoachRequest) -> tuple[CoachEvidence, ...]:
        evidence: list[CoachEvidence] = []
        if request.mode is CoachMode.POSITION:
            evidence.append(
                await self._read(
                    request_id=request.request_id,
                    ordinal=1,
                    tool_id="board.current",
                )
            )
            evidence.append(
                await self._read(
                    request_id=request.request_id,
                    ordinal=2,
                    tool_id="engine.analyze",
                    arguments={"multipv": 3, "depth": 16},
                )
            )
        elif request.mode is CoachMode.GAME_REVIEW:
            game = await self._read(
                request_id=request.request_id,
                ordinal=1,
                tool_id="gametree.current",
            )
            evidence.append(game)
            evidence.append(
                await self._read(
                    request_id=request.request_id,
                    ordinal=2,
                    tool_id="engine.analyze",
                    arguments={"multipv": 5, "depth": 18},
                )
            )
            evidence.append(
                await self._read(
                    request_id=request.request_id,
                    ordinal=3,
                    tool_id="library.search",
                    arguments=self._library_query_from_game(
                        game, limit=request.library_limit
                    ),
                )
            )
        elif request.mode is CoachMode.TRAINING:
            evidence.append(
                await self._read(
                    request_id=request.request_id,
                    ordinal=1,
                    tool_id="board.current",
                )
            )
            evidence.append(
                await self._read(
                    request_id=request.request_id,
                    ordinal=2,
                    tool_id="engine.analyze",
                    arguments={"multipv": 3, "depth": 16},
                )
            )
            evidence.append(
                await self._read(
                    request_id=request.request_id,
                    ordinal=3,
                    tool_id="training.status",
                )
            )
        elif request.mode is CoachMode.MEDIA:
            evidence.append(
                await self._read(
                    request_id=request.request_id,
                    ordinal=1,
                    tool_id="media.status",
                )
            )
            evidence.append(
                await self._read(
                    request_id=request.request_id,
                    ordinal=2,
                    tool_id="board.current",
                )
            )
            evidence.append(
                await self._read(
                    request_id=request.request_id,
                    ordinal=3,
                    tool_id="engine.analyze",
                    arguments={"multipv": 3, "depth": 16},
                )
            )
        else:  # pragma: no cover - closed enum
            raise AgentCoachError("unsupported coach mode")
        return tuple(evidence)

    @staticmethod
    def _instruction(request: CoachRequest, evidence: tuple[CoachEvidence, ...]) -> str:
        payload = [
            {"tool_id": item.tool_id, "output": item.output}
            for item in evidence
        ]
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        mode_rules = {
            CoachMode.POSITION: (
                "Explain the current move/position only from the supplied canonical "
                "board and Stockfish evidence. Distinguish engine evidence from coaching interpretation."
            ),
            CoachMode.GAME_REVIEW: (
                "Review the loaded game context, identify mistakes only when supported "
                "by the supplied engine evidence, and use Library results only as related examples. "
                "Do not claim an opening/endgame fact that is absent from evidence."
            ),
            CoachMode.TRAINING: (
                "Create one bounded exercise or Guess-the-Move/adaptive-training prompt "
                "from the supplied canonical position, engine lines and current training status. "
                "Include the expected answer and a short explanation, but do not persist anything."
            ),
            CoachMode.MEDIA: (
                "Answer what is currently shown by Media evidence and compare only the supplied "
                "canonical board with Stockfish. Never infer an unseen timestamp or board."
            ),
        }[request.mode]
        navigation = (
            " You may request media.seek or media.restore_position only if needed and only "
            "because the owner explicitly enabled local Media navigation for this run."
            if request.mode is CoachMode.MEDIA and request.allow_media_navigation
            else " Do not request any tool; answer only from the evidence below."
        )
        return (
            f"COACH_MODE={request.mode.value}\n"
            f"{mode_rules}{navigation}\n"
            f"USER_QUESTION={request.question.strip()}\n"
            f"CANONICAL_EVIDENCE_JSON={encoded}"
        )

    async def run(self, request: CoachRequest) -> CoachResult:
        if type(request) is not CoachRequest:
            raise TypeError("request must be CoachRequest")
        evidence = await self._collect(request)
        allowed: frozenset[str]
        if request.mode is CoachMode.MEDIA and request.allow_media_navigation:
            allowed = frozenset({"media.seek", "media.restore_position"})
            for tool_id in allowed:
                self._spec(tool_id)
        else:
            allowed = frozenset()
        result: AgentRunResult = await self.runtime.run(
            run_id=request.request_id,
            user_text=self._instruction(request, evidence),
            allowed_tool_ids=allowed,
        )
        return CoachResult(
            mode=request.mode,
            text=result.text,
            evidence=evidence,
            model_calls=result.model_calls,
            model_tool_calls=result.tool_calls,
        )

    async def cancel(self, request_id: str) -> bool:
        return await self.runtime.cancel(request_id)


__all__ = [
    "AgentCoachError",
    "AgentCoachWorkflow",
    "CoachEvidence",
    "CoachMode",
    "CoachRequest",
    "CoachResult",
    "register_coach_read_tools",
]
