from __future__ import annotations

"""Persistent UI-facing service for the central Accessible Chess action registry.

The WebView must not own shortcut normalization, conflict policy, profile migration,
or persistence. This facade is deliberately JSON-friendly so pywebview can expose
it without leaking filesystem or registry internals into JavaScript.
"""

from pathlib import Path
from typing import Any

from .keybindings import ActionRegistry, BindingContext
from .ui_keymap_adapter import build_web_keymap
from .ui_keymap_editor import KeymapEditorModel


class KeymapService:
    def __init__(self, path: str | Path, *, lang: str = "uk") -> None:
        self.path = Path(path)
        registry, recovery = ActionRegistry.load(self.path)
        self.editor = KeymapEditorModel(registry, lang=lang)
        self.recovery_message = recovery

    def snapshot(self) -> dict[str, Any]:
        data = build_web_keymap(self.editor.registry)
        data["recoveryMessage"] = self.recovery_message
        return data

    def search(self, query: str = "", context: str | None = None) -> list[dict[str, Any]]:
        parsed_context = BindingContext(context) if context else None
        return [row.__dict__.copy() for row in self.editor.rows(query=query, context=parsed_context)]

    def save(self, action_id: str, value: str, *, allow_warnings: bool = False) -> dict[str, Any]:
        result = self.editor.save(action_id, value, allow_warnings=allow_warnings)
        if result.ok:
            self._persist()
        return self._result(result)

    def reset_action(self, action_id: str) -> dict[str, Any]:
        result = self.editor.reset_action(action_id)
        self._persist()
        return self._result(result)

    def reset_context(self, context: str) -> dict[str, Any]:
        result = self.editor.reset_context(BindingContext(context))
        self._persist()
        return self._result(result)

    def reset_all(self) -> dict[str, Any]:
        result = self.editor.reset_all()
        self._persist()
        return self._result(result)

    def export_profile(self) -> str:
        return self.editor.export_profile()

    def import_profile(self, text: str) -> dict[str, Any]:
        result = self.editor.import_profile(text)
        if result.ok:
            self._persist()
        return self._result(result)

    def set_language(self, lang: str) -> dict[str, Any]:
        self.editor.set_language(lang)
        return self.snapshot()

    def _persist(self) -> None:
        self.editor.registry.save(self.path)
        self.recovery_message = None

    @staticmethod
    def _result(result) -> dict[str, Any]:
        return {
            "ok": result.ok,
            "message": result.message,
            "conflicts": [
                {
                    "kind": item.kind,
                    "actionId": item.action_id,
                    "otherActionId": item.other_action_id,
                    "context": item.context.value,
                    "value": item.value,
                    "message": item.message,
                    "severity": item.severity,
                }
                for item in result.conflicts
            ],
        }
