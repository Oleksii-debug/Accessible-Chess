from __future__ import annotations

"""Section 22 adapter for the existing bounded speech-context tool."""

from collections.abc import Callable

from .agent_tools import ToolExecutor, ToolSpec
from .media_subtitles import SubtitleContext, register_speech_context_tool


class AgentSpeechContextTools:
    """Register speech_context.* on the canonical Agent executor.

    The actual transcript/subtitle evidence remains owned by the existing media
    context authority. Permission is checked live for every read.
    """

    def __init__(
        self,
        context: SubtitleContext,
        *,
        current_media: Callable[[], tuple[str, str, int]],
        context_allowed: Callable[[], bool],
    ) -> None:
        if type(context) is not SubtitleContext:
            raise TypeError("context must be an exact SubtitleContext")
        if not callable(current_media):
            raise TypeError("current_media must be callable")
        if not callable(context_allowed):
            raise TypeError("context_allowed must be callable")
        self._context = context
        self._current_media = current_media
        self._context_allowed = context_allowed

    def register(self, executor: ToolExecutor) -> tuple[ToolSpec, ...]:
        if type(executor) is not ToolExecutor:
            raise TypeError("executor must be ToolExecutor")
        before = {spec.tool_id for spec in executor.specs()}
        register_speech_context_tool(
            executor,
            context=self._context,
            current_media=self._current_media,
            context_allowed=self._context_allowed,
        )
        return tuple(spec for spec in executor.specs() if spec.tool_id not in before)


__all__ = ["AgentSpeechContextTools"]
