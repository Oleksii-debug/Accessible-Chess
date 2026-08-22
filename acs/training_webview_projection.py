"""Accessible Training WebView projection over canonical ExerciseSession state.

DEV1 does not decide chess correctness or mutate board legality. The browser sends
one bounded answer to TrainingPresenter, which delegates correctness to the
canonical ExerciseSession. Accepted moves are hidden until explicit reveal.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import re
from typing import Any

from .full_product_presenters import TrainingPresenter, TrainingView
from .full_product_ui_shell import UILanguage, concise_user_error
from .training import ExerciseStatus

CommandDispatch = Callable[[str, Mapping[str, object]], Any]

_WINDOWS_LOCAL_PATH = re.compile(r"(?i)(?<![\w])([a-z]:[\\/][^\r\n\t]*)")
_POSIX_LOCAL_PATH = re.compile(
    r"(?i)(?<![\w])(/(?:home|users|tmp|mnt|var/tmp|private/tmp)/[^\r\n\t ]*)"
)

_LABELS = {
    UILanguage.UA: {
        "heading": "Тренування",
        "description": "Виконуйте вправу з клавіатури. Перевірку відповіді виконує канонічний модуль тренування.",
        "prompt": "Введіть хід",
        "answer": "Відповідь",
        "submit": "Перевірити",
        "hint": "Підказка",
        "reveal": "Показати розв’язок",
        "retry": "Спробувати ще раз",
        "reset": "Почати вправу спочатку",
        "progress": "Крок {step} з {total}",
        "attempts": "Спроб: {value}",
        "mistakes": "Помилок: {value}",
        "hints": "Підказок використано: {value}",
        "completed": "Вправу завершено.",
        "solution": "Розв’язок",
        "board": "Початкова позиція вправи",
        "source": "Джерело вправи",
        "transport_error": "Не вдалося виконати дію тренування.",
        "local_path": "[локальний шлях приховано]",
    },
    UILanguage.EN: {
        "heading": "Training",
        "description": "Complete the exercise from the keyboard. Answer correctness is owned by the canonical training service.",
        "prompt": "Enter a move",
        "answer": "Answer",
        "submit": "Check answer",
        "hint": "Hint",
        "reveal": "Reveal solution",
        "retry": "Try again",
        "reset": "Restart exercise",
        "progress": "Step {step} of {total}",
        "attempts": "Attempts: {value}",
        "mistakes": "Mistakes: {value}",
        "hints": "Hints used: {value}",
        "completed": "Exercise completed.",
        "solution": "Solution",
        "board": "Exercise starting position",
        "source": "Exercise source",
        "transport_error": "The training action could not be completed.",
        "local_path": "[local path hidden]",
    },
}


def _safe_text(value: object, *, language: UILanguage, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("training presentation text must be text")
    text = value.replace("\x00", "").strip()
    replacement = _LABELS[language]["local_path"]
    text = _WINDOWS_LOCAL_PATH.sub(replacement, text)
    text = _POSIX_LOCAL_PATH.sub(replacement, text)
    return text[:limit]


@dataclass(frozen=True, slots=True)
class TrainingWebViewEvent:
    kind: str
    payload: Mapping[str, object]


class TrainingWebViewProjection:
    def __init__(
        self,
        presenter: TrainingPresenter,
        dispatch: CommandDispatch | None = None,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(presenter, TrainingPresenter):
            raise TypeError("presenter must be TrainingPresenter")
        if dispatch is not None and not callable(dispatch):
            raise TypeError("training dispatcher must be callable")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._presenter = presenter
        self._dispatch = dispatch
        self._language = language
        self._presenter.set_language(language)

    @property
    def language(self) -> UILanguage:
        return self._language

    def _snapshot_from_view(self, view: TrainingView, *, solution: tuple[str, ...] = ()) -> dict[str, object]:
        if not isinstance(view, TrainingView):
            raise TypeError("training presenter returned invalid view")
        labels = _LABELS[self._language]
        if type(view.step_number) is not int or type(view.total_steps) is not int:
            raise ValueError("training progress is invalid")
        if view.total_steps <= 0 or not 1 <= view.step_number <= view.total_steps:
            raise ValueError("training progress is out of bounds")
        for value in (view.attempts, view.mistakes, view.hints_used):
            if type(value) is not int or value < 0 or value > 1_000_000_000:
                raise ValueError("training counters are invalid")
        if view.mistakes > view.attempts:
            raise ValueError("training counters are inconsistent")
        if not isinstance(view.completed, bool):
            raise ValueError("training completion state is invalid")
        if not isinstance(view.status, ExerciseStatus):
            raise ValueError("training status is invalid")

        definition = self._presenter.session.definition
        title = _safe_text(view.title, language=self._language, limit=320) or labels["heading"]
        message = _safe_text(view.message, language=self._language, limit=1200)
        source = _safe_text(definition.source_id, language=self._language, limit=160)
        start_fen = definition.start_fen
        if not isinstance(start_fen, str) or "\x00" in start_fen or not start_fen.strip() or len(start_fen) > 512:
            raise ValueError("training start position is invalid")
        safe_solution = tuple(_safe_text(move, language=self._language, limit=160) for move in solution)
        if any(not move for move in safe_solution):
            raise ValueError("training solution contains an empty move")

        return {
            "document": {"lang": self._language.value, "landmark": "main"},
            "status": view.status.value,
            "heading": labels["heading"],
            "description": labels["description"],
            "title": title,
            "prompt": labels["prompt"],
            "answer_label": labels["answer"],
            "submit_label": labels["submit"],
            "progress_label": labels["progress"].format(step=view.step_number, total=view.total_steps),
            "attempts_label": labels["attempts"].format(value=view.attempts),
            "mistakes_label": labels["mistakes"].format(value=view.mistakes),
            "hints_label": labels["hints"].format(value=view.hints_used),
            "message": message,
            "completed_message": labels["completed"] if view.completed else "",
            "completed": view.completed,
            "board": {
                # Current canonical training domain does not own a progressing board;
                # this is explicitly the exercise start position for composition with
                # the shared Board/GameTree surface, never a DEV1-invented state.
                "label": labels["board"],
                "start_fen": start_fen.strip(),
            },
            "source": {"label": labels["source"], "value": source},
            "solution": {"label": labels["solution"], "moves": safe_solution},
            "transport_error_message": labels["transport_error"],
            "focus_target": "training-answer" if not view.completed else "training-root",
            "actions": (
                {"action": "training.hint", "label": labels["hint"], "enabled": not view.completed},
                {"action": "training.reveal", "label": labels["reveal"], "enabled": not view.completed},
                {"action": "training.retry", "label": labels["retry"], "enabled": not view.completed},
                {"action": "training.reset", "label": labels["reset"], "enabled": True},
            ),
        }

    def snapshot(self) -> dict[str, object]:
        # Passive render intentionally does not call current_step() or reveal any
        # accepted moves. One TrainingView is the sole mutable progress snapshot.
        return self._snapshot_from_view(self._presenter.view())

    def _event(self, view: TrainingView, *, announce: str = "", solution: tuple[str, ...] = ()) -> TrainingWebViewEvent:
        snapshot = self._snapshot_from_view(view, solution=solution)
        return TrainingWebViewEvent(
            "render",
            {
                "snapshot": snapshot,
                "focus_target": snapshot["focus_target"],
                "announcement": _safe_text(announce, language=self._language, limit=1200),
            },
        )

    def submit(self, answer: str) -> TrainingWebViewEvent:
        result, view = self._presenter.submit(answer)
        announcement = view.message
        if result.completed and not announcement:
            announcement = _LABELS[self._language]["completed"]
        return self._event(view, announce=announcement)

    def hint(self) -> TrainingWebViewEvent:
        _hint, view = self._presenter.request_hint()
        return self._event(view, announce=view.message)

    def reveal(self) -> TrainingWebViewEvent:
        solution = self._presenter.reveal_solution()
        view = self._presenter.view()
        return self._event(view, announce=view.message, solution=solution)

    def retry(self) -> TrainingWebViewEvent:
        return self._event(self._presenter.retry(), announce="")

    def reset(self) -> TrainingWebViewEvent:
        return self._event(self._presenter.reset(), announce="")

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
        return self._event(self._presenter.view())

    def safe_call(self, method: Callable[[], TrainingWebViewEvent]) -> TrainingWebViewEvent:
        try:
            return method()
        except Exception as exc:
            return TrainingWebViewEvent(
                "error",
                {"message": concise_user_error(exc, language=self._language)},
            )
