from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol

from .child_coaching_ui import LessonTemplate, LessonTemplateBlock
from .lesson_template_storage import LessonTemplatePreset, TemplateRevision


class LessonTemplateApplicationPort(Protocol):
    """Narrow presentation-facing subset of LessonApplicationService."""

    def ensure_default_templates(self) -> tuple[TemplateRevision, ...]: ...

    def save_new_template(
        self, template: LessonTemplate, *, level: str, is_preset: bool = False
    ) -> TemplateRevision: ...

    def update_template(
        self,
        template: LessonTemplate,
        *,
        level: str,
        expected_revision: int,
        is_preset: bool = False,
    ) -> TemplateRevision: ...

    def load_template(self, template_id: str) -> tuple[LessonTemplatePreset, TemplateRevision]: ...


@dataclass(frozen=True)
class EditableTemplateState:
    template: LessonTemplate
    level: str
    revision: int | None
    persisted: bool
    is_preset: bool


class LessonTemplatePresentation:
    """Accessible editable-template projection over the existing application service.

    Persistence, migrations and optimistic concurrency remain owned by the
    existing LessonApplicationService/stores. This class owns only editable UI
    state and concise user-facing results; storage exceptions are never exposed
    verbatim to the document.
    """

    def __init__(self, application: LessonTemplateApplicationPort) -> None:
        self._application = application
        self._current: EditableTemplateState | None = None

    def ensure_presets(self) -> dict[str, Any]:
        try:
            revisions = self._application.ensure_default_templates()
        except Exception:
            return self._error("Не вдалося підготувати стандартні шаблони уроків.")
        return {
            "ok": True,
            "count": len(revisions),
            "accessibleText": "Стандартні шаблони уроків готові.",
        }

    def open_template(self, template_id: str) -> dict[str, Any]:
        try:
            preset, revision = self._application.load_template(str(template_id).strip())
        except Exception:
            return self._error("Не вдалося відкрити шаблон уроку.")
        self._current = EditableTemplateState(
            preset.template,
            preset.level,
            revision.revision,
            True,
            preset.is_preset,
        )
        return self.snapshot(accessible_text=f"Відкрито шаблон «{preset.template.title}».")

    def begin_copy(
        self,
        source: LessonTemplate,
        *,
        template_id: str,
        title: str,
        level: str = "beginner",
    ) -> dict[str, Any]:
        new_id = str(template_id).strip()
        new_title = str(title).strip()
        new_level = str(level).strip()
        if not new_id or not new_title or not new_level:
            return self._error("Потрібні назва, ідентифікатор і рівень шаблону.")
        template = replace(source, template_id=new_id, title=new_title)
        self._current = EditableTemplateState(template, new_level, None, False, False)
        return self.snapshot(accessible_text=f"Створено редаговану копію «{new_title}».")

    def edit_block(
        self,
        block_id: str,
        *,
        title: str | None = None,
        duration_minutes: int | None = None,
    ) -> dict[str, Any]:
        current = self._require_current()
        target = str(block_id).strip()
        updated: list[LessonTemplateBlock] = []
        found = False
        try:
            for block in current.template.blocks:
                if block.block_id != target:
                    updated.append(block)
                    continue
                found = True
                next_title = block.title if title is None else str(title).strip()
                next_duration = block.duration_minutes if duration_minutes is None else int(duration_minutes)
                updated.append(
                    replace(
                        block,
                        title=next_title,
                        duration_minutes=next_duration,
                    )
                )
        except (TypeError, ValueError):
            return self._error("Перевірте назву та тривалість блоку.")
        if not found:
            return self._error("Блок шаблону не знайдено.")
        self._current = replace(
            current,
            template=replace(current.template, blocks=tuple(updated)),
        )
        return self.snapshot(accessible_text="Блок шаблону змінено.")

    def save(self) -> dict[str, Any]:
        current = self._require_current()
        try:
            if current.persisted:
                assert current.revision is not None
                revision = self._application.update_template(
                    current.template,
                    level=current.level,
                    expected_revision=current.revision,
                    is_preset=False,
                )
            else:
                revision = self._application.save_new_template(
                    current.template,
                    level=current.level,
                    is_preset=False,
                )
        except Exception:
            return self._error(
                "Не вдалося зберегти шаблон. Оновіть дані й повторіть дію."
            )
        self._current = replace(
            current,
            revision=revision.revision,
            persisted=True,
            is_preset=False,
        )
        return self.snapshot(accessible_text=f"Шаблон «{current.template.title}» збережено.")

    def snapshot(self, *, accessible_text: str = "") -> dict[str, Any]:
        if self._current is None:
            return {
                "ok": True,
                "open": False,
                "template": None,
                "accessibleText": accessible_text,
            }
        current = self._current
        return {
            "ok": True,
            "open": True,
            "template": {
                "templateId": current.template.template_id,
                "title": current.template.title,
                "ageBand": current.template.age_band,
                "level": current.level,
                "plannedMinutes": current.template.planned_minutes,
                "revision": current.revision,
                "persisted": current.persisted,
                "isPreset": current.is_preset,
                "blocks": [
                    {
                        "blockId": block.block_id,
                        "kind": block.kind.value,
                        "title": block.title,
                        "durationMinutes": block.duration_minutes,
                        "notationRequired": block.notation_required,
                    }
                    for block in current.template.blocks
                ],
            },
            "accessibleText": accessible_text,
        }

    def _require_current(self) -> EditableTemplateState:
        if self._current is None:
            raise ValueError("no template is open")
        return self._current

    @staticmethod
    def _error(text: str) -> dict[str, Any]:
        return {"ok": False, "accessibleText": text}
