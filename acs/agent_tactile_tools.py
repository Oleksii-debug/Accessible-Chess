from __future__ import annotations

"""Section 22 Agent gateway for already-completed tactile capabilities."""

from collections.abc import Callable, Mapping

from .agent_tools import ToolExecutor, ToolRisk, ToolSpec


class AgentTactileTools:
    """Expose the canonical tactile.status/tactile.refresh host boundary.

    The model never receives a FEN setter, device handle, geometry setter, or
    routing authority. Refresh has no model-provided payload and delegates to
    the existing Section-10 application action.
    """

    def __init__(
        self,
        *,
        status_provider: Callable[[], Mapping[str, object]],
        refresh_current: Callable[[], Mapping[str, object]],
    ) -> None:
        if not callable(status_provider):
            raise TypeError("status_provider must be callable")
        if not callable(refresh_current):
            raise TypeError("refresh_current must be callable")
        self._status_provider = status_provider
        self._refresh_current = refresh_current

    @staticmethod
    def _snapshot(value: object) -> dict[str, object]:
        if type(value) is not dict:
            raise TypeError("tactile host result must be an exact dictionary")
        if any(type(key) is not str for key in value):
            raise TypeError("tactile host result keys must be text")
        return dict(value)

    def register(self, executor: ToolExecutor) -> tuple[ToolSpec, ...]:
        if type(executor) is not ToolExecutor:
            raise TypeError("executor must be ToolExecutor")

        async def status(arguments: Mapping[str, object]) -> object:
            if arguments:
                raise ValueError("tactile.status accepts no arguments")
            return self._snapshot(self._status_provider())

        async def refresh(arguments: Mapping[str, object]) -> object:
            if arguments:
                raise ValueError("tactile.refresh accepts no arguments")
            return self._snapshot(self._refresh_current())

        specs = (
            ToolSpec(
                "tactile.status",
                "Read the existing tactile synchronization/output status.",
            ),
            ToolSpec(
                "tactile.refresh",
                "Refresh tactile output from the current canonical product state.",
                risk=ToolRisk.LOCAL_WRITE,
            ),
        )
        executor.register(specs[0], status)
        executor.register(specs[1], refresh)
        return specs


__all__ = ["AgentTactileTools"]
