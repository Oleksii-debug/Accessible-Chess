from __future__ import annotations

from typing import Any, Mapping

from .keybindings import ActionRegistry, BindingContext
from .teaching_actions import build_teaching_action_registry
from .teaching_ui import TeachingUiState


_UI_ACTION_IDS = (
    "teaching.pointer_input",
    "teaching.annotation.square",
    "teaching.annotation.arrow",
)


class TeachingActionPresentation:
    """Accessible presentation adapter over the central ActionRegistry.

    This adapter owns no chess, pointer, or annotation state. It resolves and
    remaps app-owned teaching actions through the existing ActionRegistry and
    delegates execution to TeachingUiState. Keyboard/UI surfaces therefore do
    not acquire a second shortcut authority.
    """

    def __init__(
        self,
        state: TeachingUiState,
        *,
        registry: ActionRegistry | None = None,
    ) -> None:
        self.state = state
        self.registry = registry or build_teaching_action_registry()

    def snapshot(self) -> dict[str, Any]:
        actions: list[dict[str, object]] = []
        for action_id in _UI_ACTION_IDS:
            definition = self.registry.definition(action_id)
            actions.append(
                {
                    "actionId": action_id,
                    "title": definition.title,
                    "binding": self.registry.get_binding(action_id),
                    "defaultBinding": definition.default_binding,
                }
            )
        return {"ok": True, "actions": actions}

    def set_binding(self, action_id: str, binding: str | None) -> dict[str, Any]:
        if action_id not in _UI_ACTION_IDS:
            return self._error("Невідома команда навчального інтерфейсу.")
        try:
            conflicts = self.registry.set_binding(action_id, binding)
        except (KeyError, ValueError):
            return self._error("Не вдалося зберегти цю комбінацію клавіш.")
        warnings = [item.message for item in conflicts if item.severity != "error"]
        return {
            "ok": True,
            "actionId": action_id,
            "binding": self.registry.get_binding(action_id),
            "warnings": warnings,
            "accessibleText": "Комбінацію клавіш збережено." if not warnings else "Комбінацію збережено з попередженням.",
        }

    def dispatch_binding(self, binding: str, payload: Mapping[str, object] | None = None) -> dict[str, Any]:
        try:
            resolution = self.registry.resolve_binding(BindingContext.DOCUMENT, binding)
        except ValueError:
            return self._error("Некоректна комбінація клавіш.")
        if resolution is None or resolution.action_id not in _UI_ACTION_IDS:
            return self._error("Для цієї комбінації немає навчальної команди.")
        return self.dispatch(resolution.action_id, payload)

    def dispatch(self, action_id: str, payload: Mapping[str, object] | None = None) -> dict[str, Any]:
        if action_id not in _UI_ACTION_IDS:
            return self._error("Невідома команда навчального інтерфейсу.")
        data = dict(payload or {})
        try:
            if action_id == "teaching.pointer_input":
                value = str(data.get("value", ""))
                return self.state.commit_pointer(value)
            if action_id == "teaching.annotation.square":
                return self.state.add_square_annotation(
                    str(data.get("annotationId", "")),
                    str(data.get("square", "")),
                    str(data.get("styleId", "primary")),
                )
            if action_id == "teaching.annotation.arrow":
                return self.state.add_arrow_annotation(
                    str(data.get("annotationId", "")),
                    str(data.get("source", "")),
                    str(data.get("target", "")),
                    str(data.get("styleId", "primary")),
                )
        except (TypeError, ValueError):
            return self._error("Не вдалося виконати команду: перевірте введені поля.")
        return self._error("Невідома команда навчального інтерфейсу.")

    @staticmethod
    def _error(text: str) -> dict[str, Any]:
        return {"ok": False, "accessibleText": text}
