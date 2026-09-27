from __future__ import annotations

"""Semantic teacher/student projection for child-coaching templates.

This module is intentionally independent of the active Teacher WebView owner.
It produces bounded JSON-ready presentation data and can be composed by that
owner without changing canonical lesson/session state.
"""

from dataclasses import dataclass
from typing import Mapping

from .child_coaching import LessonTemplate
from .child_coaching_application import (
    ChildCoachingApplication,
    ChildCoachingApplicationError,
    TemplateSummary,
)
from .full_product_ui_shell import UILanguage

_TEXT = {
    UILanguage.UA: {
        "heading": "Шаблони занять для дітей",
        "description": "Вікові шаблони, які тренер може копіювати й змінювати.",
        "preset": "вбудований",
        "custom": "власний",
        "minutes": "хвилин",
        "blocks": "блоків",
        "no_notation": "без обов'язкового введення нотації",
        "notation": "з використанням нотації",
        "teacher_note": "Нотатка тренера",
    },
    UILanguage.EN: {
        "heading": "Child lesson templates",
        "description": "Age-adaptive templates the coach can copy and edit.",
        "preset": "preset",
        "custom": "custom",
        "minutes": "minutes",
        "blocks": "blocks",
        "no_notation": "no notation entry required",
        "notation": "notation used",
        "teacher_note": "Teacher note",
    },
}

_AGE = {
    UILanguage.UA: {
        "preschool_4_6": "4–6 років",
        "young_beginner_7_8": "7–8 років",
        "school_age_9_10": "9–10 років",
        "strong_child": "сильніший учень",
    },
    UILanguage.EN: {
        "preschool_4_6": "ages 4–6",
        "young_beginner_7_8": "ages 7–8",
        "school_age_9_10": "ages 9–10",
        "strong_child": "stronger child",
    },
}

_LEVEL = {
    UILanguage.UA: {
        "beginner": "початківець",
        "developing": "розвиток",
        "advanced": "просунутий",
    },
    UILanguage.EN: {
        "beginner": "beginner",
        "developing": "developing",
        "advanced": "advanced",
    },
}


@dataclass(frozen=True, slots=True)
class ChildCoachingProjectionEvent:
    kind: str
    payload: Mapping[str, object]


class ChildCoachingProjection:
    """Read-only semantic projection over the revision-aware application service."""

    def __init__(
        self,
        application: ChildCoachingApplication,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if type(application) is not ChildCoachingApplication:
            raise TypeError("application must be ChildCoachingApplication")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._application = application
        self._language = language

    @property
    def language(self) -> UILanguage:
        return self._language

    def snapshot(self) -> dict[str, object]:
        catalog = self._application.open_catalog()
        return {
            "document": {
                "lang": self._language.value,
                "heading": _TEXT[self._language]["heading"],
                "description": _TEXT[self._language]["description"],
            },
            "revision": catalog.revision,
            "recovered_from_backup": catalog.recovered_from_backup,
            "templates": tuple(self._summary(item) for item in catalog.templates),
        }

    def open_teacher_template(self, template_id: str) -> ChildCoachingProjectionEvent:
        template, revision = self._application.get_template(template_id)
        return ChildCoachingProjectionEvent(
            "template",
            {
                "revision": revision,
                "template": self._template_payload(template, include_teacher_notes=True),
                "announcement": self._announcement(template),
            },
        )

    def student_preview(self, template_id: str) -> ChildCoachingProjectionEvent:
        template, revision = self._application.get_template(template_id)
        return ChildCoachingProjectionEvent(
            "student-preview",
            {
                "revision": revision,
                "template": self._template_payload(template, include_teacher_notes=False),
                "announcement": self._announcement(template),
            },
        )

    def safe_open_teacher_template(self, template_id: str) -> ChildCoachingProjectionEvent:
        try:
            return self.open_teacher_template(template_id)
        except (ChildCoachingApplicationError, ValueError, TypeError):
            return ChildCoachingProjectionEvent(
                "error",
                {
                    "message": (
                        "Не вдалося відкрити шаблон заняття."
                        if self._language is UILanguage.UA
                        else "The lesson template could not be opened."
                    )
                },
            )

    def _summary(self, item: TemplateSummary) -> dict[str, object]:
        labels = _TEXT[self._language]
        notation = labels["no_notation"] if item.no_notation_required else labels["notation"]
        kind = labels["custom"] if item.custom else labels["preset"]
        age = _AGE[self._language][item.age_band.value]
        level = _LEVEL[self._language][item.level.value]
        return {
            "template_id": item.template_id,
            "title": item.title,
            "age": age,
            "level": level,
            "minutes": item.total_minutes,
            "block_count": item.block_count,
            "no_notation_required": item.no_notation_required,
            "custom": item.custom,
            "accessible_label": (
                f"{item.title}, {age}, {level}, {item.total_minutes} {labels['minutes']}, "
                f"{item.block_count} {labels['blocks']}, {notation}, {kind}"
            ),
        }

    def _template_payload(
        self,
        template: LessonTemplate,
        *,
        include_teacher_notes: bool,
    ) -> dict[str, object]:
        labels = _TEXT[self._language]
        return {
            "template_id": template.template_id,
            "title": template.title,
            "age": _AGE[self._language][template.age_band.value],
            "level": _LEVEL[self._language][template.level.value],
            "total_minutes": template.total_minutes,
            "no_notation_required": template.no_notation_required,
            "custom": template.custom,
            "blocks": tuple(
                self._block_payload(
                    block,
                    include_teacher_notes=include_teacher_notes,
                    teacher_note_label=labels["teacher_note"],
                )
                for block in template.blocks
            ),
        }

    @staticmethod
    def _block_payload(
        block,
        *,
        include_teacher_notes: bool,
        teacher_note_label: str,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "block_id": block.block_id,
            "kind": block.kind.value,
            "title": block.title,
            "minutes": block.minutes,
            "activity": block.activity.value,
            "prompt": block.prompt,
            "notation_required": block.notation_required,
            "student_engine_visible": block.student_engine_visible,
        }
        if include_teacher_notes:
            payload["target_square"] = block.target_square
            payload["target_piece"] = block.target_piece
            payload["solution_text"] = block.solution_text
            payload["teacher_note"] = block.teacher_note
            payload["teacher_note_label"] = teacher_note_label
        return payload

    def _announcement(self, template: LessonTemplate) -> str:
        labels = _TEXT[self._language]
        age = _AGE[self._language][template.age_band.value]
        notation = (
            labels["no_notation"]
            if template.no_notation_required
            else labels["notation"]
        )
        return (
            f"{template.title}. {age}. {template.total_minutes} {labels['minutes']}. "
            f"{len(template.blocks)} {labels['blocks']}. {notation}."
        )
