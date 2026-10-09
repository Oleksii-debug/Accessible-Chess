from __future__ import annotations

"""Read-only child-coaching context over canonical Classroom + progress authorities."""

from dataclasses import dataclass

from .classroom_domain import ClassroomSnapshot
from .full_product_ui_shell import UILanguage
from .student_progress import StudentProgressLedger, StudentProgressSummary


class ChildCoachingContextError(ValueError):
    """Raised when a coach context cannot be projected safely."""


@dataclass(frozen=True, slots=True)
class ChildCoachingContext:
    student_id: str
    student_label: str
    consent_state: str
    summary: StudentProgressSummary
    accessible_text: str


def build_child_coaching_context(
    classroom: ClassroomSnapshot,
    ledger: StudentProgressLedger,
    *,
    student_id: str,
    session_id: str,
    language: UILanguage = UILanguage.UA,
) -> ChildCoachingContext:
    """Project factual local review context without inventing proficiency state."""

    if type(classroom) is not ClassroomSnapshot:
        raise ChildCoachingContextError("classroom context is unavailable")
    if not isinstance(ledger, StudentProgressLedger):
        raise ChildCoachingContextError("student progress authority is unavailable")
    if type(student_id) is not str or not student_id:
        raise ChildCoachingContextError("student identity is invalid")
    if type(session_id) is not str or not session_id:
        raise ChildCoachingContextError("session identity is invalid")
    if not isinstance(language, UILanguage):
        raise ChildCoachingContextError("UI language is invalid")

    matches = tuple(item for item in classroom.students if item.student_id == student_id)
    if len(matches) != 1:
        raise ChildCoachingContextError("student is unavailable")
    student = matches[0]
    if student.deleted:
        raise ChildCoachingContextError("student is unavailable")
    if not student.can_collect_personal_data:
        raise ChildCoachingContextError(
            "student progress is unavailable without granted consent"
        )

    try:
        summary = ledger.summary(student.student_id, session_id)
    except (TypeError, ValueError) as exc:
        raise ChildCoachingContextError("student progress summary is unavailable") from exc

    return ChildCoachingContext(
        student_id=student.student_id,
        student_label=student.pseudonym,
        consent_state=student.consent.value,
        summary=summary,
        accessible_text=_accessible_summary(student.pseudonym, summary, language),
    )


def child_coaching_context_to_teacher_payload(
    context: ChildCoachingContext,
) -> dict[str, object]:
    """Serialize only coach-facing aggregate facts; omit stable internal ids."""

    if type(context) is not ChildCoachingContext:
        raise ChildCoachingContextError("child coaching context is invalid")
    summary = context.summary
    accuracy = summary.accuracy_permille
    return {
        "student_label": context.student_label,
        "consent": context.consent_state,
        "record_count": summary.record_count,
        "training_reviews": summary.training_reviews,
        "game_reviews": summary.game_reviews,
        "completed_training_reviews": summary.completed_training_reviews,
        "attempts": summary.attempts,
        "mistakes": summary.mistakes,
        "hints_used": summary.hints_used,
        "accuracy_percent": (
            None if accuracy is None else _percent_text(accuracy)
        ),
        "engine_reviews": summary.engine_reviews,
        "stale_engine_reviews": summary.stale_engine_reviews,
        "accessible_text": context.accessible_text,
    }


def _percent_text(permille: int) -> str:
    whole, tenth = divmod(permille, 10)
    return f"{whole}.{tenth}%"


def _accessible_summary(
    label: str,
    summary: StudentProgressSummary,
    language: UILanguage,
) -> str:
    if summary.record_count == 0:
        if language is UILanguage.UA:
            return f"{label}. Історії тренувань і партій для цього заняття ще немає."
        return f"{label}. No training or game review history for this lesson yet."

    if language is UILanguage.UA:
        parts = [
            label,
            f"оглядів: {summary.record_count}",
            f"тренувань: {summary.training_reviews}",
            f"партій: {summary.game_reviews}",
        ]
        if summary.attempts:
            parts.extend(
                (
                    f"спроб: {summary.attempts}",
                    f"помилок: {summary.mistakes}",
                    f"підказок: {summary.hints_used}",
                    f"точність: {_percent_text(summary.accuracy_permille or 0)}",
                )
            )
        return ". ".join(parts) + "."

    parts = [
        label,
        f"reviews: {summary.record_count}",
        f"training: {summary.training_reviews}",
        f"games: {summary.game_reviews}",
    ]
    if summary.attempts:
        parts.extend(
            (
                f"attempts: {summary.attempts}",
                f"mistakes: {summary.mistakes}",
                f"hints: {summary.hints_used}",
                f"accuracy: {_percent_text(summary.accuracy_permille or 0)}",
            )
        )
    return ". ".join(parts) + "."


__all__ = [
    "ChildCoachingContext",
    "ChildCoachingContextError",
    "build_child_coaching_context",
    "child_coaching_context_to_teacher_payload",
]
