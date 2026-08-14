from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Iterable, Mapping


SCHEMA_VERSION = 1


class BindingContext(str, Enum):
    GLOBAL = "global"
    DOCUMENT = "document"
    MOVE_ENTRY = "move_entry"
    BOARD = "board"
    POSITION_EDITOR = "position_editor"
    HISTORY = "history"
    ANALYSIS = "analysis"
    ENGINE_GAME = "engine_game"
    DATABASE = "database"
    BOOK_READER = "book_reader"


@dataclass(frozen=True)
class ActionDefinition:
    action_id: str
    context: BindingContext
    title: str
    default_binding: str | None = None
    default_alias: str | None = None
    description: str = ""
    external: bool = False


@dataclass(frozen=True)
class Conflict:
    kind: str
    action_id: str
    other_action_id: str | None
    context: BindingContext
    value: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class Resolution:
    action_id: str
    context: BindingContext
    binding: str | None
    alias: str | None


_RESERVED_WINDOWS = {
    "Alt+F4",
    "Ctrl+Alt+Delete",
    "Win+D",
    "Win+E",
    "Win+L",
    "Win+R",
    "Win+Tab",
}
_RESERVED_WEBVIEW = {
    "Ctrl+L",
    "Ctrl+N",
    "Ctrl+Shift+N",
    "Ctrl+T",
    "Ctrl+W",
}
_LIKELY_NVDA = {
    "NVDA+F1",
    "NVDA+F2",
    "NVDA+F7",
    "NVDA+Space",
}


def _normalize_alias(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value.casefold() if value else None


def normalize_binding(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None

    tokens = [token.strip() for token in raw.replace("-", "+").split("+") if token.strip()]
    if not tokens:
        return None

    aliases = {
        "control": "Ctrl",
        "ctrl": "Ctrl",
        "shift": "Shift",
        "alt": "Alt",
        "win": "Win",
        "windows": "Win",
        "meta": "Win",
        "escape": "Escape",
        "esc": "Escape",
        "spacebar": "Space",
        "space": "Space",
        "return": "Enter",
        "enter": "Enter",
        "delete": "Delete",
        "del": "Delete",
        "backspace": "Backspace",
        "home": "Home",
        "end": "End",
        "pageup": "PageUp",
        "pagedown": "PageDown",
        "left": "Left",
        "right": "Right",
        "up": "Up",
        "down": "Down",
    }
    modifiers: list[str] = []
    key = None
    for token in tokens:
        canonical = aliases.get(token.casefold())
        if canonical in {"Ctrl", "Shift", "Alt", "Win"}:
            if canonical not in modifiers:
                modifiers.append(canonical)
            continue
        if key is not None:
            raise ValueError(f"binding has more than one non-modifier key: {value!r}")
        if canonical:
            key = canonical
        elif len(token) == 1:
            key = token.upper()
        elif token.upper().startswith("F") and token[1:].isdigit():
            key = token.upper()
        else:
            key = token[0].upper() + token[1:]

    if key is None:
        raise ValueError(f"binding must contain a non-modifier key: {value!r}")

    order = ["Ctrl", "Alt", "Shift", "Win"]
    modifiers.sort(key=order.index)
    return "+".join([*modifiers, key])


DEFAULT_ACTIONS: tuple[ActionDefinition, ...] = (
    ActionDefinition("history.previous", BindingContext.HISTORY, "Previous historical position", "Shift+A"),
    ActionDefinition("history.next", BindingContext.HISTORY, "Next historical position", "Shift+D"),
    ActionDefinition("history.go_to_move", BindingContext.HISTORY, "Go to move", "Ctrl+G"),
    ActionDefinition("edit.undo", BindingContext.GLOBAL, "Undo", "Ctrl+Z"),
    ActionDefinition("edit.redo", BindingContext.GLOBAL, "Redo", "Ctrl+Shift+Z"),
    ActionDefinition("analysis.pv1", BindingContext.ANALYSIS, "Read principal variation 1", "Alt+1"),
    ActionDefinition("analysis.pv2", BindingContext.ANALYSIS, "Read principal variation 2", "Alt+2"),
    ActionDefinition("analysis.pv3", BindingContext.ANALYSIS, "Read principal variation 3", "Alt+3"),
    ActionDefinition("analysis.pv4", BindingContext.ANALYSIS, "Read principal variation 4", "Alt+4"),
    ActionDefinition("analysis.pv5", BindingContext.ANALYSIS, "Read principal variation 5", "Alt+5"),
    ActionDefinition("board.current", BindingContext.BOARD, "Current square", "O"),
    ActionDefinition("board.last_captured", BindingContext.BOARD, "Last captured piece", "C"),
    ActionDefinition("board.last_move", BindingContext.BOARD, "Last move", "L"),
    ActionDefinition("board.my_clock", BindingContext.BOARD, "My clock", "T"),
    ActionDefinition("board.opponent_clock", BindingContext.BOARD, "Opponent clock", "Shift+T"),
    ActionDefinition("board.legal_moves", BindingContext.BOARD, "Legal moves", "M"),
    ActionDefinition("board.captures", BindingContext.BOARD, "Captures", "Shift+M"),
    ActionDefinition("board.surroundings", BindingContext.BOARD, "Surroundings", "X"),
    ActionDefinition("board.attackers", BindingContext.BOARD, "Attackers", "A"),
    ActionDefinition("board.defenders", BindingContext.BOARD, "Defenders", "D"),
    ActionDefinition("board.evaluation", BindingContext.BOARD, "Evaluation", "V"),
    ActionDefinition("board.best_move", BindingContext.BOARD, "Best move", "G"),
    ActionDefinition("board.play_best", BindingContext.BOARD, "Play best move in analysis", "Shift+G"),
    ActionDefinition("board.next_king", BindingContext.BOARD, "Next king", "K"),
    ActionDefinition("board.next_queen", BindingContext.BOARD, "Next queen", "Q"),
    ActionDefinition("board.next_rook", BindingContext.BOARD, "Next rook", "R"),
    ActionDefinition("board.next_bishop", BindingContext.BOARD, "Next bishop", "B"),
    ActionDefinition("board.next_knight", BindingContext.BOARD, "Next knight", "N"),
    ActionDefinition("board.next_pawn", BindingContext.BOARD, "Next pawn", "P"),
    ActionDefinition("board.previous_king", BindingContext.BOARD, "Previous king", "Shift+K"),
    ActionDefinition("board.previous_queen", BindingContext.BOARD, "Previous queen", "Shift+Q"),
    ActionDefinition("board.previous_rook", BindingContext.BOARD, "Previous rook", "Shift+R"),
    ActionDefinition("board.previous_bishop", BindingContext.BOARD, "Previous bishop", "Shift+B"),
    ActionDefinition("board.previous_knight", BindingContext.BOARD, "Previous knight", "Shift+N"),
    ActionDefinition("board.previous_pawn", BindingContext.BOARD, "Previous pawn", "Shift+P"),
    ActionDefinition("board.input", BindingContext.BOARD, "Move input", "I"),
    ActionDefinition("move.undo", BindingContext.MOVE_ENTRY, "Undo move command", default_alias="u"),
    ActionDefinition("move.redo", BindingContext.MOVE_ENTRY, "Redo move command", default_alias="y"),
    ActionDefinition("move.last", BindingContext.MOVE_ENTRY, "Last move command", default_alias="l"),
    ActionDefinition("move.white_to_move", BindingContext.MOVE_ENTRY, "White to move command", default_alias="w"),
    ActionDefinition("move.black_to_move", BindingContext.MOVE_ENTRY, "Black to move command", default_alias="b"),
    ActionDefinition("move.clear", BindingContext.MOVE_ENTRY, "Clear board command", default_alias="c"),
    ActionDefinition("move.standard", BindingContext.MOVE_ENTRY, "Standard position command", default_alias="s"),
    ActionDefinition("move.empty", BindingContext.MOVE_ENTRY, "Empty position command", default_alias="e"),
)


class ActionRegistry:
    """Presentation-neutral command registry and user keymap state."""

    def __init__(
        self,
        definitions: Iterable[ActionDefinition] = DEFAULT_ACTIONS,
        *,
        bindings: Mapping[str, str | None] | None = None,
        aliases: Mapping[str, str | None] | None = None,
    ):
        self._definitions = {item.action_id: item for item in definitions}
        if not self._definitions:
            raise ValueError("registry requires at least one action")
        self._bindings: dict[str, str | None] = {}
        self._aliases: dict[str, str | None] = {}

        for action_id, definition in self._definitions.items():
            self._bindings[action_id] = normalize_binding(definition.default_binding)
            self._aliases[action_id] = _normalize_alias(definition.default_alias)

        for action_id, value in (bindings or {}).items():
            if action_id in self._definitions:
                self._bindings[action_id] = normalize_binding(value)
        for action_id, value in (aliases or {}).items():
            if action_id in self._definitions:
                self._aliases[action_id] = _normalize_alias(value)

    def definitions(self) -> tuple[ActionDefinition, ...]:
        return tuple(self._definitions.values())

    def definition(self, action_id: str) -> ActionDefinition:
        try:
            return self._definitions[action_id]
        except KeyError as exc:
            raise KeyError(f"unknown action id: {action_id}") from exc

    def get_binding(self, action_id: str) -> str | None:
        self.definition(action_id)
        return self._bindings[action_id]

    def get_alias(self, action_id: str) -> str | None:
        self.definition(action_id)
        return self._aliases[action_id]

    def set_binding(self, action_id: str, binding: str | None, *, allow_warnings: bool = True) -> tuple[Conflict, ...]:
        definition = self.definition(action_id)
        if definition.external:
            raise ValueError(f"external action cannot be remapped: {action_id}")
        normalized = normalize_binding(binding)
        conflicts = self.binding_conflicts(action_id, normalized)
        errors = [c for c in conflicts if c.severity == "error"]
        warnings = [c for c in conflicts if c.severity != "error"]
        if errors or (warnings and not allow_warnings):
            raise ValueError("; ".join(c.message for c in (errors or warnings)))
        self._bindings[action_id] = normalized
        return conflicts

    def set_alias(self, action_id: str, alias: str | None) -> tuple[Conflict, ...]:
        definition = self.definition(action_id)
        if definition.external:
            raise ValueError(f"external action cannot be remapped: {action_id}")
        normalized = _normalize_alias(alias)
        conflicts = self.alias_conflicts(action_id, normalized)
        errors = [c for c in conflicts if c.severity == "error"]
        if errors:
            raise ValueError("; ".join(c.message for c in errors))
        self._aliases[action_id] = normalized
        return conflicts

    def resolve_binding(self, context: BindingContext, binding: str) -> Resolution | None:
        normalized = normalize_binding(binding)
        for ctx in (context, BindingContext.GLOBAL):
            for action_id, definition in self._definitions.items():
                if definition.external or definition.context != ctx:
                    continue
                if self._bindings[action_id] == normalized:
                    return Resolution(action_id, definition.context, normalized, self._aliases[action_id])
        return None

    def resolve_alias(self, context: BindingContext, alias: str) -> Resolution | None:
        normalized = _normalize_alias(alias)
        if normalized is None:
            return None
        for ctx in (context, BindingContext.GLOBAL):
            for action_id, definition in self._definitions.items():
                if definition.external or definition.context != ctx:
                    continue
                if self._aliases[action_id] == normalized:
                    return Resolution(action_id, definition.context, self._bindings[action_id], normalized)
        return None

    def binding_conflicts(self, action_id: str, binding: str | None) -> tuple[Conflict, ...]:
        definition = self.definition(action_id)
        normalized = normalize_binding(binding)
        if normalized is None:
            return ()
        result: list[Conflict] = []
        for other_id, other_def in self._definitions.items():
            if other_id == action_id or other_def.external:
                continue
            if other_def.context == definition.context and self._bindings[other_id] == normalized:
                result.append(Conflict(
                    "duplicate",
                    action_id,
                    other_id,
                    definition.context,
                    normalized,
                    f"{normalized} is already assigned to {other_id} in {definition.context.value}",
                ))
        if normalized in _RESERVED_WINDOWS:
            result.append(Conflict(
                "windows_reserved", action_id, None, definition.context, normalized,
                f"{normalized} is reserved or strongly owned by Windows", "warning"
            ))
        if normalized in _RESERVED_WEBVIEW:
            result.append(Conflict(
                "webview_reserved", action_id, None, definition.context, normalized,
                f"{normalized} is commonly reserved by WebView/browser behavior", "warning"
            ))
        if normalized in _LIKELY_NVDA or normalized.startswith("NVDA+"):
            result.append(Conflict(
                "nvda_likely", action_id, None, definition.context, normalized,
                f"{normalized} is likely to conflict with NVDA", "warning"
            ))
        return tuple(result)

    def alias_conflicts(self, action_id: str, alias: str | None) -> tuple[Conflict, ...]:
        definition = self.definition(action_id)
        normalized = _normalize_alias(alias)
        if normalized is None:
            return ()
        result: list[Conflict] = []
        for other_id, other_def in self._definitions.items():
            if other_id == action_id or other_def.external:
                continue
            if other_def.context == definition.context and self._aliases[other_id] == normalized:
                result.append(Conflict(
                    "alias_duplicate",
                    action_id,
                    other_id,
                    definition.context,
                    normalized,
                    f"alias {normalized!r} is already assigned to {other_id} in {definition.context.value}",
                ))
        return tuple(result)

    def reset_action(self, action_id: str) -> None:
        definition = self.definition(action_id)
        self._bindings[action_id] = normalize_binding(definition.default_binding)
        self._aliases[action_id] = _normalize_alias(definition.default_alias)

    def reset_context(self, context: BindingContext) -> None:
        for action_id, definition in self._definitions.items():
            if definition.context == context and not definition.external:
                self.reset_action(action_id)

    def reset_all(self) -> None:
        for action_id, definition in self._definitions.items():
            if not definition.external:
                self.reset_action(action_id)

    def help_items(self, *, context: BindingContext | None = None) -> tuple[dict[str, object], ...]:
        rows = []
        for action_id, definition in self._definitions.items():
            if definition.external or (context is not None and definition.context != context):
                continue
            rows.append({
                "action_id": action_id,
                "context": definition.context.value,
                "title": definition.title,
                "description": definition.description,
                "binding": self._bindings[action_id],
                "alias": self._aliases[action_id],
                "default_binding": normalize_binding(definition.default_binding),
                "default_alias": _normalize_alias(definition.default_alias),
            })
        return tuple(rows)

    def to_profile(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "bindings": dict(self._bindings),
            "aliases": dict(self._aliases),
        }

    def export_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_profile(), ensure_ascii=False, indent=indent, sort_keys=True)

    @classmethod
    def from_profile(
        cls,
        profile: Mapping[str, object],
        definitions: Iterable[ActionDefinition] = DEFAULT_ACTIONS,
    ) -> "ActionRegistry":
        migrated = _migrate_profile(profile)
        bindings = migrated.get("bindings", {})
        aliases = migrated.get("aliases", {})
        if not isinstance(bindings, Mapping) or not isinstance(aliases, Mapping):
            raise ValueError("invalid keymap profile")
        registry = cls(definitions, bindings=bindings, aliases=aliases)
        registry.validate()
        return registry

    @classmethod
    def import_json(
        cls,
        text: str,
        definitions: Iterable[ActionDefinition] = DEFAULT_ACTIONS,
    ) -> "ActionRegistry":
        value = json.loads(text)
        if not isinstance(value, Mapping):
            raise ValueError("keymap profile must be a JSON object")
        return cls.from_profile(value, definitions)

    def validate(self) -> tuple[Conflict, ...]:
        conflicts: list[Conflict] = []
        for action_id in self._definitions:
            conflicts.extend(self.binding_conflicts(action_id, self._bindings[action_id]))
            conflicts.extend(self.alias_conflicts(action_id, self._aliases[action_id]))
        unique: dict[tuple[str, str, str | None, str], Conflict] = {}
        for item in conflicts:
            left, right = item.action_id, item.other_action_id
            if right is not None and item.kind in {"duplicate", "alias_duplicate"}:
                a, b = sorted((left, right))
                key = (item.kind, a, b, item.value)
            else:
                key = (item.kind, left, right, item.value)
            unique[key] = item
        return tuple(unique.values())

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(self.export_json() + "\n", encoding="utf-8")
        tmp.replace(target)

    @classmethod
    def load(
        cls,
        path: str | Path,
        definitions: Iterable[ActionDefinition] = DEFAULT_ACTIONS,
    ) -> tuple["ActionRegistry", str | None]:
        target = Path(path)
        if not target.exists():
            return cls(definitions), None
        try:
            return cls.import_json(target.read_text(encoding="utf-8"), definitions), None
        except Exception as exc:
            return cls(definitions), f"keymap recovery: {exc}"


def _migrate_profile(profile: Mapping[str, object]) -> dict[str, object]:
    raw_version = profile.get("schema_version", 0)
    try:
        version = int(raw_version)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid schema_version") from exc

    if version > SCHEMA_VERSION:
        raise ValueError(
            f"keymap schema {version} is newer than supported schema {SCHEMA_VERSION}"
        )

    data = dict(profile)
    if version == 0:
        data = {
            "schema_version": 1,
            "bindings": dict(data.get("bindings") or data.get("keys") or {}),
            "aliases": dict(data.get("aliases") or data.get("commands") or {}),
        }
        version = 1

    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported keymap schema {version}")
    return data
