"""Accessible training WebView projection over canonical TrainingPresenter state.

Passive browser snapshots contain progress and concise presentation text only.
Exercise FEN, accepted moves, source identifiers and persistence metadata stay on
the Python/domain side. Accepted moves cross the boundary only after the user
explicitly requests solution reveal.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re

from .full_product_presenters import TrainingPresenter, TrainingView
from .full_product_ui_shell import UILanguage, concise_user_error
from .training import ExerciseStatus

_MAX_ANSWER = 128
_WINDOWS_PATH = re.compile(r"(?i)(?<![\w])([a-z]:[\\/][^\r\n\t]*)")
_POSIX_PATH = re.compile(r"(?i)(?<![\w])(/(?:home|users|tmp|mnt|var/tmp|private/tmp)/[^\r\n\t ]*)")

_LABELS = {
    UILanguage.UA: {
        "heading": "Тренування",
        "step": "Крок",
        "of": "з",
        "attempts": "Спроби",
        "mistakes": "Помилки",
        "hints": "Підказки",
        "answer": "Ваш хід",
        "submit": "Перевірити хід",
        "hint": "Підказка",
        "reveal": "Показати розв’язок",
        "retry": "Спробувати ще раз",
        "reset": "Почати вправу спочатку",
        "reset_title": "Скинути прогрес вправи?",
        "reset_text": "Поточний прогрес цієї вправи буде скинуто.",
        "confirm_reset": "Скинути",
        "cancel": "Скасувати",
        "solution": "Розв’язок",
        "completed": "Вправу завершено.",
        "hidden_path": "[локальний шлях приховано]",
    },
    UILanguage.EN: {
        "heading": "Training",
        "step": "Step",
        "of": "of",
        "attempts": "Attempts",
        "mistakes": "Mistakes",
        "hints": "Hints",
        "answer": "Your move",
        "submit": "Check move",
        "hint": "Hint",
        "reveal": "Reveal solution",
        "retry": "Try again",
        "reset": "Restart exercise",
        "reset_title": "Reset exercise progress?",
        "reset_text": "The current progress for this exercise will be reset.",
        "confirm_reset": "Reset",
        "cancel": "Cancel",
        "solution": "Solution",
        "completed": "Exercise completed.",
        "hidden_path": "[local path hidden]",
    },
}


def _safe_text(value: object, *, language: UILanguage, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("training presentation text must be text")
    text = value.replace("\x00", "").strip()
    replacement = _LABELS[language]["hidden_path"]
    text = _WINDOWS_PATH.sub(replacement, text)
    text = _POSIX_PATH.sub(replacement, text)
    return text[:limit]


def _answer(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("training answer must be text")
    if "\x00" in value:
        raise ValueError("training answer contains NUL")
    if len(value) > _MAX_ANSWER:
        raise ValueError("training answer is too long")
    token = " ".join(value.split())
    if not token:
        raise ValueError("training answer must not be empty")
    return token


@dataclass(frozen=True, slots=True)
class TrainingWebViewEvent:
    kind: str
    payload: Mapping[str, object]


class TrainingWebViewProjection:
    def __init__(
        self,
        presenter: TrainingPresenter,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(presenter, TrainingPresenter):
            raise TypeError("presenter must be TrainingPresenter")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._presenter = presenter
        self._language = language
        self._presenter.set_language(language)

    @property
    def language(self) -> UILanguage:
        return self._language

    def set_language(self, language: UILanguage | str) -> TrainingWebViewEvent:
        if isinstance(language, str):
            try:
                language = UILanguage(language.strip().lower())
            except ValueError:
                raise ValueError("unsupported UI language") from None
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._language = language
        self._presenter.set_language(language)
        return TrainingWebViewEvent("render", {"snapshot": self.snapshot(), "focus_target": ""})

    def _snapshot_from_view(self, view: TrainingView) -> dict[str, object]:
        if not isinstance(view, TrainingView):
            raise TypeError("TrainingPresenter must return TrainingView")
        if not isinstance(view.status, ExerciseStatus):
            raise ValueError("training status is invalid")
        exact_ints = (view.step_number, view.total_steps, view.attempts, view.mistakes, view.hints_used)
        if any(type(value) is not int or value < 0 for value in exact_ints):
            raise ValueError("training counters are invalid")
        if view.total_steps < 1 or not 1 <= view.step_number <= view.total_steps:
            raise ValueError("training step counters are inconsistent")
        if view.mistakes > view.attempts:
            raise ValueError("training mistakes exceed attempts")
        if type(view.completed) is not bool:
            raise ValueError("training completion flag must be boolean")
        if view.completed != (view.status is ExerciseStatus.COMPLETED):
            raise ValueError("training completion/status mismatch")

        labels = _LABELS[self._language]
        title = _safe_text(view.title, language=self._language, limit=360) or labels["heading"]
        message = _safe_text(view.message, language=self._language, limit=1200)
        if view.completed and not message:
            message = labels["completed"]
        return {
            "document": {"lang": self._language.value, "landmark": "main"},
            "heading": labels["heading"],
            "title": title,
            "status": view.status.value,
            "progress": {
                "step_label": labels["step"],
                "step": view.step_number,
                "of_label": labels["of"],
                "total": view.total_steps,
                "attempts_label": labels["attempts"],
                "attempts": view.attempts,
                "mistakes_label": labels["mistakes"],
                "mistakes": view.mistakes,
                "hints_label": labels["hints"],
                "hints_used": view.hints_used,
                "completed": view.completed,
            },
            "message": message,
            "answer": {
                "label": labels["answer"],
                "max_length": _MAX_ANSWER,
                "submit_label": labels["submit"],
                "disabled": view.completed,
            },
            "actions": (
                {"command": "training.hint", "label": labels["hint"], "enabled": not view.completed},
                {"command": "training.reveal", "label": labels["reveal"], "enabled": not view.completed},
                {"command": "training.retry", "label": labels["retry"], "enabled": not view.completed},
                {"command": "training.reset.request", "label": labels["reset"], "enabled": True},
            ),
            "reset_dialog": {
                "title": labels["reset_title"],
                "text": labels["reset_text"],
                "confirm_label": labels["confirm_reset"],
                "cancel_label": labels["cancel"],
            },
            "solution_label": labels["solution"],
            # Passive snapshot intentionally excludes definition.start_fen,
            # accepted_moves, source_id, metadata and persistence snapshot data.
        }

    def snapshot(self) -> dict[str, object]:
        return self._snapshot_from_view(self._presenter.view())

    def _render(
        self,
        view: TrainingView,
        *,
        focus_target: str = "training-answer",
        announcement: str = "",
        clear_answer: bool = False,
        solution: tuple[str, ...] = (),
    ) -> TrainingWebViewEvent:
        snapshot = self._snapshot_from_view(view)
        safe_solution = tuple(
            _safe_text(move, language=self._language, limit=_MAX_ANSWER)
            for move in solution
        )
        return TrainingWebViewEvent(
            "render",
            {
                "snapshot": snapshot,
                "focus_target": focus_target,
                "announcement": _safe_text(announcement, language=self._language, limit=1200),
                "clear_answer": bool(clear_answer),
                "solution": safe_solution,
            },
        )

    def submit(self, value: object) -> TrainingWebViewEvent:
        answer = _answer(value)
        result, view = self._presenter.submit(answer)
        return self._render(
            view,
            announcement=view.message,
            clear_answer=result.accepted,
        )

    def hint(self) -> TrainingWebViewEvent:
        _hint, view = self._presenter.request_hint()
        return self._render(view, announcement=view.message)

    def reveal(self) -> TrainingWebViewEvent:
        solution = self._presenter.reveal_solution()
        view = self._presenter.view()
        return self._render(
            view,
            announcement=view.message,
            solution=solution,
        )

    def retry(self) -> TrainingWebViewEvent:
        view = self._presenter.retry()
        return self._render(view)

    def reset(self, *, confirmed: object) -> TrainingWebViewEvent:
        if type(confirmed) is not bool or not confirmed:
            raise ValueError("training reset requires explicit confirmation")
        view = self._presenter.reset()
        return self._render(view, clear_answer=True)

    def generic_error(self) -> TrainingWebViewEvent:
        return TrainingWebViewEvent(
            "error",
            {"message": concise_user_error("", language=self._language)},
        )
