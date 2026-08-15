from __future__ import annotations

"""Persistent UI-facing service for the central Accessible Chess action registry.

The WebView must not own shortcut normalization, conflict policy, profile migration,
or persistence. This facade is deliberately JSON-friendly so pywebview can expose
it without leaking filesystem or registry internals into JavaScript.
"""

from pathlib import Path
from typing import Any

from .keybindings import ActionRegistry, BindingContext, normalize_binding
from .ui_keymap_adapter import build_web_keymap
from .ui_keymap_editor import KeymapEditorModel


_MODIFIER_KEYS = frozenset({"Control", "Ctrl", "Alt", "Shift", "Meta", "Win", "Windows"})
_KEY_ALIASES = {
    " ": "Space",
    "Spacebar": "Space",
    "Esc": "Escape",
    "Return": "Enter",
    "Del": "Delete",
    "ArrowLeft": "Left",
    "ArrowRight": "Right",
    "ArrowUp": "Up",
    "ArrowDown": "Down",
    "PageUp": "PageUp",
    "PageDown": "PageDown",
}


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

    def preview(self, action_id: str, value: str) -> dict[str, Any]:
        """Return live validation for a captured value without mutating state.

        This is the single WebView bridge for pre-save validation. JavaScript may
        render the returned status in an aria-live region, but normalization and
        conflict policy stay in the central registry/editor model.
        """

        preview = self.editor.preview(action_id, value)
        return {
            "actionId": preview.action_id,
            "value": preview.value,
            "valueKind": preview.value_kind,
            "canSave": preview.can_save,
            "requiresConfirmation": preview.requires_confirmation,
            "status": preview.status,
            "message": preview.message,
            "conflicts": [self._conflict(item) for item in preview.conflicts],
        }

    def capture_shortcut(
        self,
        action_id: str,
        key: str,
        *,
        ctrl: bool = False,
        alt: bool = False,
        shift: bool = False,
        win: bool = False,
    ) -> dict[str, Any]:
        """Convert one browser/native key event into a validated shortcut preview.

        The presentation sends only event facts. It does not normalize chords,
        decide conflicts, or persist anything. Tab remains native focus navigation,
        Escape cancels capture, and modifier-only events stay incomplete so a
        keyboard-only user cannot accidentally save an unusable binding.

        Browser KeyboardEvent.key represents the Space key as a literal single
        space in some WebView/Chromium versions. Preserve that exact value before
        trimming other key names, otherwise Space becomes an empty key and cannot
        be assigned by a keyboard-only user.
        """

        event_key = str(key or "")
        raw_key = event_key if event_key == " " else event_key.strip()
        if raw_key == "Tab":
            return self._capture_control("navigation", "Tab")
        if raw_key in {"Escape", "Esc"}:
            return self._capture_control("cancelled", "Escape")
        if not raw_key or raw_key in _MODIFIER_KEYS:
            message = (
                "Press a non-modifier key to complete the shortcut."
                if self.editor.lang == "en"
                else "Натисніть клавішу, що не є модифікатором, щоб завершити комбінацію."
            )
            return {
                "captured": False,
                "reason": "incomplete",
                "binding": "",
                "status": "pending",
                "message": message,
                "canSave": False,
                "requiresConfirmation": False,
                "conflicts": [],
            }

        canonical_key = _KEY_ALIASES.get(raw_key, raw_key)
        parts: list[str] = []
        if ctrl:
            parts.append("Ctrl")
        if alt:
            parts.append("Alt")
        if shift:
            parts.append("Shift")
        if win:
            parts.append("Win")
        parts.append(canonical_key)

        try:
            binding = normalize_binding("+".join(parts)) or ""
        except ValueError as exc:
            return {
                "captured": False,
                "reason": "invalid",
                "binding": "",
                "status": "error",
                "message": str(exc),
                "canSave": False,
                "requiresConfirmation": False,
                "conflicts": [],
            }

        preview = self.preview(action_id, binding)
        return {
            "captured": True,
            "reason": "captured",
            "binding": binding,
            **preview,
        }

    def resolve_binding(self, context: str, binding: str) -> dict[str, Any] | None:
        """Resolve a live keyboard chord to its current action for WebView dispatch.

        The browser must not cache default shortcuts or reproduce context fallback
        rules. Every keydown can ask this bridge for the action that is active in
        the user's current persisted keymap, so remapping takes effect immediately.
        """

        resolution = self.editor.registry.resolve_binding(BindingContext(context), binding)
        return self._resolution(resolution)

    def resolve_alias(self, context: str, alias: str) -> dict[str, Any] | None:
        """Resolve a typed command alias through the current central registry.

        This keeps move-entry commands remappable without conflating command
        aliases with literal chess syntax such as W:/B: in the position editor.
        """

        resolution = self.editor.registry.resolve_alias(BindingContext(context), alias)
        return self._resolution(resolution)

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

    def _capture_control(self, reason: str, key: str) -> dict[str, Any]:
        if reason == "navigation":
            message = "Tab keeps focus navigation." if self.editor.lang == "en" else "Tab залишає навігацію фокусом."
        else:
            message = "Shortcut capture cancelled." if self.editor.lang == "en" else "Захоплення комбінації скасовано."
        return {
            "captured": False,
            "reason": reason,
            "binding": key,
            "status": "cancelled" if reason == "cancelled" else "navigation",
            "message": message,
            "canSave": False,
            "requiresConfirmation": False,
            "conflicts": [],
        }

    @staticmethod
    def _resolution(item) -> dict[str, Any] | None:
        if item is None:
            return None
        return {
            "actionId": item.action_id,
            "context": item.context.value,
            "binding": item.binding,
            "alias": item.alias,
        }

    @staticmethod
    def _conflict(item) -> dict[str, Any]:
        return {
            "kind": item.kind,
            "actionId": item.action_id,
            "otherActionId": item.other_action_id,
            "context": item.context.value,
            "value": item.value,
            "message": item.message,
            "severity": item.severity,
        }

    @classmethod
    def _result(cls, result) -> dict[str, Any]:
        return {
            "ok": result.ok,
            "message": result.message,
            "conflicts": [cls._conflict(item) for item in result.conflicts],
        }
