"""Accessible training WebView projection over canonical TrainingPresenter state.

Passive browser snapshots contain progress and concise presentation text only.
Exercise FEN, accepted moves, source identifiers and persistence metadata stay on
the Python/domain side. Accepted moves cross the boundary only after the user
explicitly requests solution reveal.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .full_product_presenters import TrainingPresenter, TrainingView
from .full_product_ui_shell import UILanguage, concise_user_error
from .presentation_privacy import redact_local_paths
from .training import ExerciseStatus

_MAX_ANSWER = 128
_MAX_SOLUTION_MOVES = 64
_MAX_SAFE_INTEGER = (1 << 53) - 1

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
        "continue": "Наступна вправа",
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
        "continue": "Next exercise",
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


def _utf16_units(value: str) -> int:
    """Count browser-visible UTF-16 code units after an O(1) scalar preflight."""

    return sum(2 if ord(character) > 0xFFFF else 1 for character in value)


def _bounded_text_units(value: str, *, limit: int, label: str) -> None:
    # Python len() is O(1). Reject any value that cannot possibly fit before
    # NUL/path/whitespace scans, then finish the browser-equivalent UTF-16 check
    # while the remaining scan is deterministically bounded by the field limit.
    if len(value) > limit:
        raise ValueError(f"{label} is too long")
    if _utf16_units(value) > limit:
        raise ValueError(f"{label} is too long")


def _safe_text(value: object, *, language: UILanguage, limit: int) -> str:
    if value is None:
        return ""
    if type(value) is not str:
        raise TypeError("training presentation text must be text")
    _bounded_text_units(value, limit=limit, label="training presentation text")
    if "\x00" in value:
        raise ValueError("training presentation text contains NUL")
    text = value.strip()
    text = redact_local_paths(text, _LABELS[language]["hidden_path"])
    _bounded_text_units(text, limit=limit, label="training presentation text")
    return text


def _safe_solution(value: object, *, language: UILanguage) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError("training solution must be a tuple")
    if len(value) > _MAX_SOLUTION_MOVES:
        raise ValueError("training solution exceeds the move limit")
    rendered: list[str] = []
    for move in value:
        if type(move) is not str:
            raise TypeError("training solution moves must be text")
        _bounded_text_units(
            move,
            limit=_MAX_ANSWER,
            label="training solution move",
        )
        if "\x00" in move:
            raise ValueError("training solution move contains NUL")
        token = move.strip()
        if not token:
            raise ValueError("training solution move must not be empty")
        token = redact_local_paths(token, _LABELS[language]["hidden_path"])
        _bounded_text_units(
            token,
            limit=_MAX_ANSWER,
            label="training solution move",
        )
        rendered.append(token)
    return tuple(rendered)


def _answer(value: object) -> str:
    if type(value) is not str:
        raise TypeError("training answer must be text")
    _bounded_text_units(value, limit=_MAX_ANSWER, label="training answer")
    if "\x00" in value:
        raise ValueError("training answer contains NUL")
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
        can_continue: Callable[[], bool] | None = None,
    ) -> None:
        # The WebView projection is the accessible publication boundary.
        # Reject presenter subclasses before set_language/view/state hooks.
        if type(presenter) is not TrainingPresenter:
            raise TypeError("presenter must be TrainingPresenter")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        if can_continue is not None and not callable(can_continue):
            raise TypeError("can_continue must be callable or None")
        self._presenter = presenter
        self._language = language
        self._can_continue = can_continue
        self._presenter.set_language(language)

    @property
    def language(self) -> UILanguage:
        return self._language

    @property
    def presenter_message(self) -> str:
        """Exact transient presenter feedback for local transactional rollback."""
        return self._presenter.message

    @property
    def presenter_message_key(self) -> str | None:
        """Internal presentation-message provenance for transactional rollback."""
        return self._presenter.message_key

    def _transactional_event(
        self,
        operation: Callable[[], TrainingWebViewEvent],
    ) -> TrainingWebViewEvent:
        before_snapshot = self._presenter.snapshot()
        before_message = self._presenter.message
        before_message_key = self._presenter.message_key
        try:
            return operation()
        except BaseException:
            self._presenter.restore_state(
                before_snapshot,
                message=before_message,
                message_key=before_message_key,
            )
            raise

    def restore_state(
        self,
        snapshot: Mapping[str, object],
        *,
        language: UILanguage,
        message: str,
        message_key: str | None,
    ) -> None:
        """Restore trusted host rollback state without replacing presenter/session identity."""
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        # Presenter restoration validates message provenance and replays the
        # canonical session on a detached candidate before mutating live state.
        self._presenter.restore_state(
            snapshot,
            message=message,
            message_key=message_key,
        )
        self._language = language
        self._presenter.set_language(language)

    def set_language(self, language: UILanguage | str) -> TrainingWebViewEvent:
        if type(language) is str:
            if len(language) > 8:
                raise ValueError("unsupported UI language")
            try:
                language = UILanguage(language.strip().lower())
            except ValueError:
                raise ValueError("unsupported UI language") from None
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        previous_language = self._language
        try:
            self._language = language
            self._presenter.set_language(language)
            snapshot = self.snapshot()
        except BaseException:
            self._language = previous_language
            self._presenter.set_language(previous_language)
            raise
        return TrainingWebViewEvent("render", {"snapshot": snapshot, "focus_target": ""})

    def _continuation_available(self, completed: bool) -> bool:
        if not completed or self._can_continue is None:
            return False
        try:
            available = self._can_continue()
        except BaseException:
            return False
        return available if type(available) is bool else False

    def _snapshot_from_view(self, view: TrainingView) -> dict[str, object]:
        if type(view) is not TrainingView:
            raise TypeError("TrainingPresenter must return TrainingView")
        if not isinstance(view.status, ExerciseStatus):
            raise ValueError("training status is invalid")
        exact_ints = (view.step_number, view.total_steps, view.attempts, view.mistakes, view.hints_used)
        if any(
            type(value) is not int or not 0 <= value <= _MAX_SAFE_INTEGER
            for value in exact_ints
        ):
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
                {
                    "command": "training.continue",
                    "label": labels["continue"],
                    "enabled": self._continuation_available(view.completed),
                },
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
        if focus_target == "training-answer" and snapshot["answer"]["disabled"]:
            enabled_actions = {
                item["command"]: item["enabled"]
                for item in snapshot["actions"]
            }
            focus_target = (
                "training-action-continue"
                if enabled_actions.get("training.continue", False)
                else "training-action-reset"
            )
        if type(clear_answer) is not bool:
            raise TypeError("training clear-answer flag must be boolean")
        if type(focus_target) is not str:
            raise TypeError("training focus target must be text")
        safe_solution = _safe_solution(solution, language=self._language)
        allowed_focus = {""}
        if not snapshot["answer"]["disabled"]:
            allowed_focus.add("training-answer")
        if safe_solution:
            allowed_focus.add("training-solution")
        for action in snapshot["actions"]:
            if action["enabled"]:
                allowed_focus.add(
                    {
                        "training.hint": "training-action-hint",
                        "training.reveal": "training-action-reveal",
                        "training.retry": "training-action-retry",
                        "training.continue": "training-action-continue",
                        "training.reset.request": "training-action-reset",
                    }[action["command"]]
                )
        if focus_target not in allowed_focus:
            raise ValueError("training focus target is inconsistent with the snapshot")
        return TrainingWebViewEvent(
            "render",
            {
                "snapshot": snapshot,
                "focus_target": focus_target,
                "announcement": _safe_text(announcement, language=self._language, limit=1200),
                "clear_answer": clear_answer,
                "solution": safe_solution,
            },
        )

    def submit(self, value: object) -> TrainingWebViewEvent:
        answer = _answer(value)

        def operation() -> TrainingWebViewEvent:
            result, view = self._presenter.submit(answer)
            return self._render(
                view,
                announcement=view.message,
                clear_answer=result.accepted,
            )

        return self._transactional_event(operation)

    def hint(self) -> TrainingWebViewEvent:
        def operation() -> TrainingWebViewEvent:
            _hint, view = self._presenter.request_hint()
            return self._render(view, announcement=view.message)

        return self._transactional_event(operation)

    def reveal(self) -> TrainingWebViewEvent:
        def operation() -> TrainingWebViewEvent:
            solution = self._presenter.reveal_solution()
            view = self._presenter.view()
            return self._render(
                view,
                focus_target="training-solution",
                announcement=view.message,
                solution=solution,
            )

        return self._transactional_event(operation)

    def retry(self) -> TrainingWebViewEvent:
        def operation() -> TrainingWebViewEvent:
            view = self._presenter.retry()
            return self._render(view)

        return self._transactional_event(operation)

    def reset(self, *, confirmed: object) -> TrainingWebViewEvent:
        if type(confirmed) is not bool or not confirmed:
            raise ValueError("training reset requires explicit confirmation")

        def operation() -> TrainingWebViewEvent:
            view = self._presenter.reset()
            return self._render(view, clear_answer=True)

        return self._transactional_event(operation)

    def generic_error(self) -> TrainingWebViewEvent:
        return TrainingWebViewEvent(
            "error",
            {"message": concise_user_error("", language=self._language)},
        )
