from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

from .board_service import BoardCommandService, MoveView, SquareView
from .squares import square_name


class AgentToolError(RuntimeError):
    """Base error for Universal Chess Agent tool execution."""


class UnknownAgentToolError(AgentToolError):
    pass


class DuplicateAgentToolError(AgentToolError):
    pass


class InvalidAgentToolArguments(AgentToolError):
    pass


class MissingAgentCapabilityError(AgentToolError):
    pass


class AgentToolConfirmationRequired(AgentToolError):
    pass


class AgentToolRisk(str, Enum):
    READ_ONLY = "read_only"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class AgentToolArgument:
    name: str
    expected_types: tuple[type, ...]
    required: bool = True
    allow_none: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name.strip() or self.name != self.name.strip():
            raise ValueError("argument name must be non-empty trimmed text")
        if type(self.expected_types) is not tuple or not self.expected_types:
            raise TypeError("expected_types must be a non-empty tuple of types")
        if any(type(item) is not type for item in self.expected_types):
            raise TypeError("expected_types entries must be types")
        if type(self.required) is not bool or type(self.allow_none) is not bool:
            raise TypeError("required and allow_none must be boolean")
        if type(self.description) is not str:
            raise TypeError("description must be text")

    def validate(self, value: Any) -> Any:
        if value is None:
            if self.allow_none:
                return None
            raise InvalidAgentToolArguments(f"{self.name} may not be null")
        if not any(type(value) is expected for expected in self.expected_types):
            names = ", ".join(expected.__name__ for expected in self.expected_types)
            raise InvalidAgentToolArguments(f"{self.name} must be exactly one of: {names}")
        return value


@dataclass(frozen=True)
class AgentToolResult:
    """Accessible text plus detached structured data returned by a tool."""

    text: str
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.text) is not str or not self.text.strip():
            raise ValueError("tool result text must be non-empty")
        if type(self.data) is not dict:
            raise TypeError("tool result data must be a built-in dict")
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


@dataclass(frozen=True)
class AgentToolSpec:
    """One explicit action exposed to the Universal Chess Agent.

    The handler is the only executable authority. Agent code must not bypass this
    registry to mutate board, tree, engine, library, online or media state.
    """

    name: str
    description: str
    handler: Callable[..., AgentToolResult] = field(repr=False, compare=False)
    arguments: tuple[AgentToolArgument, ...] = ()
    risk: AgentToolRisk = AgentToolRisk.READ_ONLY
    required_capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name.strip() or self.name != self.name.strip():
            raise ValueError("tool name must be non-empty trimmed text")
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789._-"
        if self.name[0] not in "abcdefghijklmnopqrstuvwxyz" or any(ch not in allowed for ch in self.name):
            raise ValueError("tool name must be a lowercase stable identifier")
        if type(self.description) is not str or not self.description.strip():
            raise ValueError("tool description must be non-empty text")
        if not callable(self.handler):
            raise TypeError("tool handler must be callable")
        if type(self.arguments) is not tuple or any(type(arg) is not AgentToolArgument for arg in self.arguments):
            raise TypeError("arguments must be a tuple of AgentToolArgument")
        names = [arg.name for arg in self.arguments]
        if len(names) != len(set(names)):
            raise ValueError("tool argument names must be unique")
        if type(self.risk) is not AgentToolRisk:
            raise TypeError("risk must be AgentToolRisk")
        if type(self.required_capabilities) is not frozenset or any(
            type(item) is not str or not item.strip() for item in self.required_capabilities
        ):
            raise TypeError("required_capabilities must be a frozenset of non-empty strings")

    def public_schema(self) -> Mapping[str, Any]:
        arguments = tuple(
            MappingProxyType(
                {
                    "name": arg.name,
                    "types": tuple(item.__name__ for item in arg.expected_types),
                    "required": arg.required,
                    "allow_none": arg.allow_none,
                    "description": arg.description,
                }
            )
            for arg in self.arguments
        )
        return MappingProxyType(
            {
                "name": self.name,
                "description": self.description,
                "risk": self.risk.value,
                "required_capabilities": tuple(sorted(self.required_capabilities)),
                "arguments": arguments,
            }
        )


class AgentToolRegistry:
    """Deterministic capability and confirmation gate for agent actions."""

    def __init__(self) -> None:
        self._tools: dict[str, AgentToolSpec] = {}

    def register(self, tool: AgentToolSpec) -> None:
        if type(tool) is not AgentToolSpec:
            raise TypeError("tool must be AgentToolSpec")
        if tool.name in self._tools:
            raise DuplicateAgentToolError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def schemas(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._tools[name].public_schema() for name in sorted(self._tools))

    def invoke(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        capabilities: frozenset[str] = frozenset(),
        confirmed: bool = False,
    ) -> AgentToolResult:
        if type(name) is not str:
            raise UnknownAgentToolError("tool name must be text")
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownAgentToolError(f"unknown tool: {name}")
        if arguments is None:
            supplied: dict[str, Any] = {}
        elif type(arguments) is dict:
            supplied = dict(arguments)
        else:
            raise InvalidAgentToolArguments("tool arguments must be a built-in dict")
        if type(capabilities) is not frozenset or any(type(item) is not str for item in capabilities):
            raise TypeError("capabilities must be a frozenset of strings")
        if type(confirmed) is not bool:
            raise TypeError("confirmed must be boolean")

        definitions = {argument.name: argument for argument in tool.arguments}
        unknown = sorted(set(supplied) - set(definitions))
        if unknown:
            raise InvalidAgentToolArguments(f"unknown arguments: {', '.join(unknown)}")
        missing = [argument.name for argument in tool.arguments if argument.required and argument.name not in supplied]
        if missing:
            raise InvalidAgentToolArguments(f"missing required arguments: {', '.join(missing)}")

        validated = {
            key: definitions[key].validate(value)
            for key, value in supplied.items()
        }
        missing_capabilities = sorted(tool.required_capabilities - capabilities)
        if missing_capabilities:
            raise MissingAgentCapabilityError(
                f"missing capabilities: {', '.join(missing_capabilities)}"
            )
        if tool.risk is not AgentToolRisk.READ_ONLY and not confirmed:
            raise AgentToolConfirmationRequired(
                f"{tool.name} requires explicit human confirmation"
            )

        result = tool.handler(**validated)
        if type(result) is not AgentToolResult:
            raise AgentToolError(f"tool {tool.name} returned an invalid result")
        return result


def _piece_text(piece: str | None) -> str:
    return "empty" if piece is None else piece


def _square_data(view: SquareView) -> dict[str, Any]:
    return {"square": view.square, "piece": view.piece}


def _move_data(move: MoveView) -> dict[str, Any]:
    return {
        "from": square_name(move.frm),
        "to": square_name(move.to),
        "san": move.san,
        "is_capture": move.is_capture,
    }


def register_board_read_tools(
    registry: AgentToolRegistry,
    board: BoardCommandService,
    *,
    capability: str = "board.read",
) -> None:
    """Register read-only tools that delegate to canonical BoardCommandService.

    No move legality, SAN, attack, material or engine calculation is reproduced
    here. The adapter only validates transport arguments, calls the canonical
    service and serializes its already-authoritative result.
    """

    if type(registry) is not AgentToolRegistry:
        raise TypeError("registry must be AgentToolRegistry")
    if type(board) is not BoardCommandService:
        raise TypeError("board must be BoardCommandService")
    if type(capability) is not str or not capability.strip():
        raise ValueError("capability must be non-empty text")
    required = frozenset({capability})
    square_argument = AgentToolArgument(
        "square", (str, int), description="Canonical square name or 0..63 index."
    )

    def current(square: str | int) -> AgentToolResult:
        view = board.current(square)
        return AgentToolResult(
            f"{view.square}: {_piece_text(view.piece)}",
            _square_data(view),
        )

    def legal_moves(square: str | int) -> AgentToolResult:
        moves = board.legal_moves(square)
        labels = tuple(move.san or f"{square_name(move.frm)}-{square_name(move.to)}" for move in moves)
        origin = board.current(square).square
        text = f"Legal moves from {origin}: " + (", ".join(labels) if labels else "none")
        return AgentToolResult(text, {"square": origin, "moves": tuple(_move_data(move) for move in moves)})

    def material() -> AgentToolResult:
        view = board.material()
        return AgentToolResult(
            f"Material: White {view.white_points}, Black {view.black_points}, balance {view.balance:+d}",
            {
                "white": dict(view.white),
                "black": dict(view.black),
                "white_points": view.white_points,
                "black_points": view.black_points,
                "balance": view.balance,
            },
        )

    def evaluation() -> AgentToolResult:
        value = board.evaluation()
        return AgentToolResult(
            "Engine evaluation: unavailable" if value is None else f"Engine evaluation: {value}",
            {"evaluation": value},
        )

    def best_move() -> AgentToolResult:
        value = board.best_move()
        return AgentToolResult(
            "Engine best move: unavailable" if value is None else f"Engine best move: {value}",
            {"best_move": value},
        )

    specs = (
        AgentToolSpec(
            "board.best_move",
            "Read the canonical engine best-move snapshot for the current board.",
            best_move,
            required_capabilities=required,
        ),
        AgentToolSpec(
            "board.current",
            "Read the canonical piece occupying one square.",
            current,
            (square_argument,),
            required_capabilities=required,
        ),
        AgentToolSpec(
            "board.evaluation",
            "Read the canonical engine evaluation snapshot for the current board.",
            evaluation,
            required_capabilities=required,
        ),
        AgentToolSpec(
            "board.legal_moves",
            "Read canonical legal moves from one square without calculating legality in the agent.",
            legal_moves,
            (square_argument,),
            required_capabilities=required,
        ),
        AgentToolSpec(
            "board.material",
            "Read the canonical material summary for the current board.",
            material,
            required_capabilities=required,
        ),
    )
    for spec in specs:
        registry.register(spec)
