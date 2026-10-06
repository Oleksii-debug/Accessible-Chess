from __future__ import annotations

"""Read-only Agent access to canonical Books/Training presentation state.

No Book/Training parsing, chess semantics, file access, or persistence mutation
lives here. The bridge consumes only the sanitized Version2Application snapshot
already used by the accessible UI.
"""

from collections.abc import Callable, Mapping

from .agent_tools import ToolExecutor, ToolSpec


_MAX_DEPTH = 12
_MAX_ITEMS = 1024
_MAX_TEXT = 12_000


class AgentBooksTrainingToolsError(ValueError):
    pass


def _passive_copy(value: object, *, surface: str, depth: int = 0,
                  budget: list[int] | None = None) -> object:
    if budget is None:
        budget = [_MAX_ITEMS]
    if depth > _MAX_DEPTH:
        raise AgentBooksTrainingToolsError(f"{surface} snapshot is too deeply nested")
    budget[0] -= 1
    if budget[0] < 0:
        raise AgentBooksTrainingToolsError(f"{surface} snapshot is too large")

    if value is None or type(value) in (bool, int):
        return value
    if type(value) is str:
        if len(value) > _MAX_TEXT:
            raise AgentBooksTrainingToolsError(f"{surface} snapshot text is too large")
        return value
    if type(value) is dict:
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise AgentBooksTrainingToolsError(
                    f"{surface} snapshot contains a non-text key"
                )
            result[key] = _passive_copy(
                item, surface=surface, depth=depth + 1, budget=budget
            )
        return result
    if type(value) in (list, tuple):
        return [
            _passive_copy(item, surface=surface, depth=depth + 1, budget=budget)
            for item in value
        ]
    raise AgentBooksTrainingToolsError(
        f"{surface} snapshot contains an active or unsupported value"
    )


class AgentBooksTrainingTools:
    """Expose already-sanitized Books/Training UI truth as read-only tools."""

    def __init__(self, snapshot_provider: Callable[[], Mapping[str, object]]) -> None:
        if not callable(snapshot_provider):
            raise TypeError("snapshot_provider must be callable")
        self._snapshot_provider = snapshot_provider

    def _surface(self, name: str) -> dict[str, object]:
        root = self._snapshot_provider()
        if type(root) is not dict:
            raise AgentBooksTrainingToolsError(
                "application snapshot must be a plain object"
            )
        value = root.get(name)
        if value is None:
            return {"available": False}
        if type(value) is not dict:
            raise AgentBooksTrainingToolsError(
                f"{name} application snapshot must be a plain object"
            )
        return {"available": True, "view": _passive_copy(value, surface=name)}

    def books_current(self) -> dict[str, object]:
        return self._surface("books")

    def training_status(self) -> dict[str, object]:
        return self._surface("training")

    def register(self, executor: ToolExecutor) -> tuple[ToolSpec, ToolSpec]:
        if type(executor) is not ToolExecutor:
            raise TypeError("executor must be ToolExecutor")

        async def books_current(arguments: Mapping[str, object]) -> object:
            if arguments:
                raise AgentBooksTrainingToolsError(
                    "books.current accepts no arguments"
                )
            return self.books_current()

        async def training_status(arguments: Mapping[str, object]) -> object:
            if arguments:
                raise AgentBooksTrainingToolsError(
                    "training.status accepts no arguments"
                )
            return self.training_status()

        books_spec = ToolSpec(
            "books.current",
            "Read the current sanitized Books presentation state.",
        )
        training_spec = ToolSpec(
            "training.status",
            "Read the current sanitized Training presentation state.",
        )
        executor.register(books_spec, books_current)
        executor.register(training_spec, training_status)
        return books_spec, training_spec
