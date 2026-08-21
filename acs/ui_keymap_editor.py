from __future__ import annotations

"""Accessible presentation model for editing app-owned keyboard commands.

This module deliberately contains no WebView2 DOM code.  It adapts the central
:mod:`acs.keybindings` registry into stable, localizable rows that any
presentation can render with native form controls.  The registry remains the
single source of truth for normalization, conflicts, reset and persistence.
"""

from dataclasses import dataclass
from typing import Iterable

from .keybindings import ActionRegistry, BindingContext, Conflict
from .ui_keymap_adapter import build_web_keymap


_CONTEXT_LABELS_UK = {
    BindingContext.GLOBAL.value: "Глобальні",
    BindingContext.DOCUMENT.value: "Документ",
    BindingContext.HISTORY.value: "Історія",
    BindingContext.ANALYSIS.value: "Аналіз",
    BindingContext.BOARD.value: "Дошка",
    BindingContext.MOVE_ENTRY.value: "Введення ходу",
    BindingContext.POSITION_EDITOR.value: "Редактор позиції",
    BindingContext.ENGINE_GAME.value: "Гра з рушієм",
    BindingContext.DATABASE.value: "База даних",
    BindingContext.BOOK_READER.value: "Читання книги",
}

_CONTEXT_LABELS_EN = {
    BindingContext.GLOBAL.value: "Global",
    BindingContext.DOCUMENT.value: "Document",
    BindingContext.HISTORY.value: "History",
    BindingContext.ANALYSIS.value: "Analysis",
    BindingContext.BOARD.value: "Board",
    BindingContext.MOVE_ENTRY.value: "Move entry",
    BindingContext.POSITION_EDITOR.value: "Position editor",
    BindingContext.ENGINE_GAME.value: "Engine game",
    BindingContext.DATABASE.value: "Database",
    BindingContext.BOOK_READER.value: "Book reader",
}


@dataclass(frozen=True)
class EditorRow:
    action_id: str
    label: str
    context: str
    context_label: str
    value: str
    default_value: str
    value_kind: str
    changed: bool
    status: str = "ok"
    status_text: str = ""


@dataclass(frozen=True)
class EditorResult:
    ok: bool
    message: str
    conflicts: tuple[Conflict, ...] = ()


@dataclass(frozen=True)
class EditorPreview:
    """Live, non-mutating validation result for a value being captured in UI."""

    action_id: str
    value: str
    value_kind: str
    can_save: bool
    requires_confirmation: bool
    status: str
    message: str
    conflicts: tuple[Conflict, ...] = ()


class KeymapEditorModel:
    """Presentation-only editor facade around :class:`ActionRegistry`.

    A WebView, native dialog, or future UI can render these rows without
    duplicating keybinding business rules.  Saving happens through the registry
    so a UI cannot silently bypass normalization or conflict checks.
    """

    def __init__(self, registry: ActionRegistry | None = None, *, lang: str = "uk") -> None:
        self.registry = registry or ActionRegistry()
        self.lang = "en" if lang == "en" else "uk"

    def set_language(self, lang: str) -> None:
        self.lang = "en" if lang == "en" else "uk"

    def _is_shortcut_action(self, action_id: str) -> bool:
        """Classify an action without confusing an unbound shortcut with an alias.

        An action whose contract has an alias default remains an alias while it
        has no binding.  All other app-owned actions are keyboard actions even
        when their default shortcut is intentionally unassigned.  A persisted
        binding always wins so migrated profiles remain editable.
        """

        definition = self.registry.definition(action_id)
        return (
            self.registry.get_binding(action_id) is not None
            or definition.default_binding is not None
            or definition.default_alias is None
        )

    def rows(self, *, query: str = "", context: BindingContext | None = None) -> tuple[EditorRow, ...]:
        projection = build_web_keymap(self.registry)["actions"]
        term = query.strip().casefold()
        rows: list[EditorRow] = []
        for item in projection:
            registry_context = str(item["registryContext"])
            if context is not None and registry_context != context.value:
                continue
            label = str(item["labelEn"] if self.lang == "en" else item["labelUk"])
            shortcut = self._is_shortcut_action(str(item["id"]))
            current = item["binding"] if shortcut else item["alias"]
            default = item["defaultBinding"] if shortcut else item["defaultAlias"]
            current_text = "" if current is None else str(current)
            default_text = "" if default is None else str(default)
            haystack = " ".join((label, registry_context, current_text, default_text, str(item["id"]))).casefold()
            if term and term not in haystack:
                continue
            context_labels = _CONTEXT_LABELS_EN if self.lang == "en" else _CONTEXT_LABELS_UK
            preview = self.preview(str(item["id"]), current_text)
            rows.append(
                EditorRow(
                    action_id=str(item["id"]),
                    label=label,
                    context=registry_context,
                    context_label=context_labels.get(registry_context, registry_context),
                    value=current_text,
                    default_value=default_text,
                    value_kind="shortcut" if shortcut else "alias",
                    changed=current_text != default_text,
                    status=preview.status,
                    status_text=preview.message,
                )
            )
        return tuple(rows)

    def preview(self, action_id: str, value: str) -> EditorPreview:
        """Validate a captured shortcut/alias without mutating the registry.

        The UI calls this while the user edits a value so an exact collision is
        announced before Save and reserved Windows/WebView2/NVDA combinations
        are exposed as warnings requiring explicit confirmation.  This keeps
        conflict semantics out of JavaScript and prevents silent overwrite.
        """

        self.registry.definition(action_id)
        is_shortcut = self._is_shortcut_action(action_id)
        try:
            conflicts = (
                self.registry.binding_conflicts(action_id, value)
                if is_shortcut
                else self.registry.alias_conflicts(action_id, value)
            )
        except ValueError as exc:
            message = str(exc)
            return EditorPreview(
                action_id=action_id,
                value=value,
                value_kind="shortcut" if is_shortcut else "alias",
                can_save=False,
                requires_confirmation=False,
                status="error",
                message=message,
            )

        errors = tuple(item for item in conflicts if item.severity == "error")
        warnings = tuple(item for item in conflicts if item.severity != "error")
        if errors:
            return EditorPreview(
                action_id=action_id,
                value=value,
                value_kind="shortcut" if is_shortcut else "alias",
                can_save=False,
                requires_confirmation=False,
                status="error",
                message=self._conflict_message(errors),
                conflicts=conflicts,
            )
        if warnings:
            prefix = "Warning: " if self.lang == "en" else "Попередження: "
            return EditorPreview(
                action_id=action_id,
                value=value,
                value_kind="shortcut" if is_shortcut else "alias",
                can_save=True,
                requires_confirmation=True,
                status="warning",
                message=prefix + "; ".join(item.message for item in warnings),
                conflicts=conflicts,
            )
        return EditorPreview(
            action_id=action_id,
            value=value,
            value_kind="shortcut" if is_shortcut else "alias",
            can_save=True,
            requires_confirmation=False,
            status="ok",
            message="No conflicts." if self.lang == "en" else "Конфліктів немає.",
            conflicts=conflicts,
        )

    def save(self, action_id: str, value: str, *, allow_warnings: bool = False) -> EditorResult:
        self.registry.definition(action_id)
        try:
            if self._is_shortcut_action(action_id):
                conflicts = self.registry.binding_conflicts(action_id, value)
                blocking = tuple(c for c in conflicts if c.severity == "error" or not allow_warnings)
                if blocking:
                    return EditorResult(False, self._conflict_message(blocking), conflicts)
                applied = self.registry.set_binding(action_id, value, allow_warnings=allow_warnings)
            else:
                conflicts = self.registry.alias_conflicts(action_id, value)
                blocking = tuple(c for c in conflicts if c.severity == "error")
                if blocking:
                    return EditorResult(False, self._conflict_message(blocking), conflicts)
                applied = self.registry.set_alias(action_id, value)
        except (KeyError, ValueError) as exc:
            return EditorResult(False, str(exc))
        return EditorResult(True, "Saved." if self.lang == "en" else "Збережено.", tuple(applied))

    def reset_action(self, action_id: str) -> EditorResult:
        self.registry.reset_action(action_id)
        return EditorResult(True, "Default restored." if self.lang == "en" else "Відновлено за замовчуванням.")

    def reset_context(self, context: BindingContext) -> EditorResult:
        self.registry.reset_context(context)
        label = (_CONTEXT_LABELS_EN if self.lang == "en" else _CONTEXT_LABELS_UK).get(context.value, context.value)
        return EditorResult(
            True,
            f"Defaults restored for {label}." if self.lang == "en" else f"Стандартні значення відновлено для: {label}.",
        )

    def reset_all(self) -> EditorResult:
        self.registry.reset_all()
        return EditorResult(True, "All defaults restored." if self.lang == "en" else "Усі стандартні значення відновлено.")

    def export_profile(self) -> str:
        return self.registry.export_json()

    def import_profile(self, text: str) -> EditorResult:
        try:
            candidate = ActionRegistry.import_json(text, self.registry.definitions())
            conflicts = candidate.validate()
            blocking = tuple(c for c in conflicts if c.severity == "error")
            if blocking:
                return EditorResult(False, self._conflict_message(blocking), conflicts)
        except (ValueError, TypeError) as exc:
            return EditorResult(False, str(exc))
        self.registry = candidate
        return EditorResult(True, "Profile imported." if self.lang == "en" else "Профіль імпортовано.", conflicts)

    def conflict_summary(self, conflicts: Iterable[Conflict]) -> str:
        items = tuple(conflicts)
        return self._conflict_message(items) if items else ""

    def _conflict_message(self, conflicts: Iterable[Conflict]) -> str:
        items = tuple(conflicts)
        if not items:
            return ""
        prefix = "Conflict: " if self.lang == "en" else "Конфлікт: "
        return prefix + "; ".join(item.message for item in items)