from __future__ import annotations

"""Read-only coach context over canonical classroom identity and progress data.

ClassroomSnapshot remains the authority for the student's pseudonym, consent and
identity lifecycle. StudentProgressLedger remains the append-only review
authority. This module only composes a bounded semantic view for coaching.
"""

from dataclasses import dataclass
from typing import Callable

from .classroom_domain import ClassroomSnapshot, ConsentState, Student
from .full_product_ui_shell import UILanguage
from .student_progress import StudentProgressLedger, StudentProgressSummary


class ChildCoachingStudentContextError(ValueError):
    """Stable read-only student-context failure."""


_TEXT = {
    UILanguage.UA: {
        "deleted_student": "Видалений учень",
        "no_reviews": "Записів прогресу для цього заняття ще немає.",
        "reviews": "записів",
        "training": "тренувань",
        "games": "розборів партій",
        "completed": "завершених тренувань",
        "attempts": "спроб",
        "mistakes": "помилок",
        "hints": "підказок",
        "accuracy": "точність",
        "accuracy_unknown": "точність ще не визначена",
        "consent_not_collected": "згоду на персональні дані не отримано",
        "consent_granted": "згоду на персональні дані надано",
        "consent_withdrawn": "згоду на персональні дані відкликано",
    },
    UILanguage.EN: {
        "deleted_student": "Deleted student",
        "no_reviews": "No progress records for this lesson yet.",
        "reviews": "records",
        "training": "training reviews",
        "games": "game reviews",
        "completed": "completed training reviews",
        "attempts": "attempts",
        "mistakes": "mistakes",
        "hints": "hints",
        "accuracy": "accuracy",
        "accuracy_unknown": "accuracy is not available yet",
        "consent_not_collected": "personal-data consent not collected",
        "consent_granted": "personal-data consent granted",
        "consent_withdrawn": "personal-data consent withdrawn",
    },
}

_CONSENT_TEXT = {
    ConsentState.NOT_COLLECTED: "consent_not_collected",
    ConsentState.GRANTED: "consent_granted",
    ConsentState.WITHDRAWN: "consent_withdrawn",
}


@dataclass(frozen=True, slots=True)
class ChildCoachingStudentContext:
    student_id: str
    display_name: str
    consent: ConsentState
    deleted: bool
    session_id: str
    record_count: int
    training_reviews: int
    game_reviews: int
    completed_training_reviews: int
    attempts: int
    mistakes: int
    hints_used: int
    accepted_attempts: int
    accuracy_permille: int | None
    accessible_summary: str

    @property
    def can_collect_personal_data(self) -> bool:
        return not self.deleted and self.consent is ConsentState.GRANTED

    def to_payload(self) -> dict[str, object]:
        """Return only bounded semantic fields already present in canonical data."""

        return {
            "student_id": self.student_id,
            "display_name": self.display_name,
            "consent": self.consent.value,
            "deleted": self.deleted,
            "session_id": self.session_id,
            "progress": {
                "record_count": self.record_count,
                "training_reviews": self.training_reviews,
                "game_reviews": self.game_reviews,
                "completed_training_reviews": self.completed_training_reviews,
                "attempts": self.attempts,
                "mistakes": self.mistakes,
                "hints_used": self.hints_used,
                "accepted_attempts": self.accepted_attempts,
                "accuracy_permille": self.accuracy_permille,
            },
            "can_collect_personal_data": self.can_collect_personal_data,
            "accessible_summary": self.accessible_summary,
        }


class ChildCoachingStudentContextProjection:
    """Compose one student's coaching context without mutating either authority."""

    def __init__(
        self,
        classroom_provider: Callable[[], ClassroomSnapshot],
        progress_provider: Callable[[], StudentProgressLedger],
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not callable(classroom_provider):
            raise TypeError("classroom_provider must be callable")
        if not callable(progress_provider):
            raise TypeError("progress_provider must be callable")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._classroom_provider = classroom_provider
        self._progress_provider = progress_provider
        self._language = language

    @property
    def language(self) -> UILanguage:
        return self._language

    def context(
        self,
        student_id: str,
        session_id: str,
    ) -> ChildCoachingStudentContext:
        classroom = self._classroom()
        student = self._student(classroom, student_id)
        if student.deleted:
            if type(session_id) is not str or not session_id.strip():
                raise ChildCoachingStudentContextError(
                    "student progress context is invalid"
                )
            # A tombstoned student must not resurrect historical metrics through
            # the coaching projection. The durable progress authority remains
            # untouched; this view is deliberately identity-minimized.
            summary = StudentProgressSummary(
                student_id=student.student_id,
                session_id=session_id,
                record_count=0,
                training_reviews=0,
                game_reviews=0,
                completed_training_reviews=0,
                attempts=0,
                mistakes=0,
                hints_used=0,
                engine_reviews=0,
                stale_engine_reviews=0,
            )
            return self._compose(student, summary)

        progress = self._progress()
        try:
            summary = progress.summary(student.student_id, session_id)
        except (TypeError, ValueError) as exc:
            raise ChildCoachingStudentContextError(
                "student progress context is invalid"
            ) from exc
        return self._compose(student, summary)

    def safe_payload(self, student_id: str, session_id: str) -> dict[str, object]:
        try:
            return {
                "kind": "student-context",
                "context": self.context(student_id, session_id).to_payload(),
            }
        except (ChildCoachingStudentContextError, TypeError, ValueError):
            return {
                "kind": "error",
                "message": (
                    "Не вдалося відкрити контекст учня."
                    if self._language is UILanguage.UA
                    else "The student context could not be opened."
                ),
            }

    def _classroom(self) -> ClassroomSnapshot:
        classroom = self._classroom_provider()
        if type(classroom) is not ClassroomSnapshot:
            raise TypeError(
                "classroom_provider must return canonical ClassroomSnapshot"
            )
        return classroom

    def _progress(self) -> StudentProgressLedger:
        progress = self._progress_provider()
        if type(progress) is not StudentProgressLedger:
            raise TypeError(
                "progress_provider must return canonical StudentProgressLedger"
            )
        return progress

    @staticmethod
    def _student(classroom: ClassroomSnapshot, student_id: str) -> Student:
        if type(student_id) is not str:
            raise TypeError("student_id must be text")
        matches = tuple(
            item
            for item in classroom.students
            if item.student_id == student_id
        )
        if len(matches) != 1:
            raise ChildCoachingStudentContextError(
                "student does not exist in the current classroom"
            )
        return matches[0]

    def _compose(
        self,
        student: Student,
        summary: StudentProgressSummary,
    ) -> ChildCoachingStudentContext:
        labels = _TEXT[self._language]
        display_name = (
            labels["deleted_student"]
            if student.deleted
            else student.pseudonym
        )
        consent_text = labels[_CONSENT_TEXT[student.consent]]
        if summary.record_count == 0:
            progress_text = labels["no_reviews"]
        else:
            accuracy_text = (
                labels["accuracy_unknown"]
                if summary.accuracy_permille is None
                else (
                    f"{labels['accuracy']} "
                    f"{summary.accuracy_permille // 10}."
                    f"{summary.accuracy_permille % 10}%"
                )
            )
            progress_text = (
                f"{summary.record_count} {labels['reviews']}; "
                f"{summary.training_reviews} {labels['training']}; "
                f"{summary.game_reviews} {labels['games']}; "
                f"{summary.completed_training_reviews} {labels['completed']}; "
                f"{summary.attempts} {labels['attempts']}; "
                f"{summary.mistakes} {labels['mistakes']}; "
                f"{summary.hints_used} {labels['hints']}; "
                f"{accuracy_text}."
            )
        return ChildCoachingStudentContext(
            student_id=student.student_id,
            display_name=display_name,
            consent=student.consent,
            deleted=student.deleted,
            session_id=summary.session_id,
            record_count=summary.record_count,
            training_reviews=summary.training_reviews,
            game_reviews=summary.game_reviews,
            completed_training_reviews=summary.completed_training_reviews,
            attempts=summary.attempts,
            mistakes=summary.mistakes,
            hints_used=summary.hints_used,
            accepted_attempts=summary.accepted_attempts,
            accuracy_permille=summary.accuracy_permille,
            accessible_summary=(
                f"{display_name}. {consent_text}. {progress_text}"
            ),
        )
