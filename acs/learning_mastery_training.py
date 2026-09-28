from __future__ import annotations

"""Composition seam from canonical Training completion to learning mastery.

Chess correctness remains entirely inside :mod:`acs.training`. This adapter
only summarizes a completed ExerciseSession into the chess-neutral
TrainingOutcome consumed by :mod:`acs.learning_mastery`.
"""

import hashlib

from .learning_mastery import MasteryError, TrainingOutcome
from .training import ExerciseSession


def outcome_from_completed_training(
    session: ExerciseSession,
    *,
    sequence: int,
    event_id: str,
    practice_date: str,
    duration_seconds: int = 0,
) -> TrainingOutcome:
    """Return one mastery outcome for an already-completed canonical session.

    ``sequence`` and ``event_id`` belong to the caller's durable operation
    identity. Retries must reuse both values. This adapter never invents a new
    sequence on retry and never calls Board/parse_move itself.
    """

    if not isinstance(session, ExerciseSession):
        raise TypeError("session must be ExerciseSession")
    if not session.completed:
        raise MasteryError("mastery can record only a completed training session")

    total_steps = len(session.definition.steps)
    if session.step_index != total_steps:
        raise MasteryError("completed training session has inconsistent progress")

    activity_id = _activity_id(session.definition.exercise_id)
    return TrainingOutcome(
        sequence=sequence,
        event_id=event_id,
        activity_id=activity_id,
        practice_date=practice_date,
        completed=True,
        correct_steps=total_steps,
        total_steps=total_steps,
        mistakes=session.mistakes,
        hints_used=session.hints_used,
        duration_seconds=duration_seconds,
    )


def _activity_id(exercise_id: str) -> str:
    """Return bounded stable identity without persisting arbitrary authored text."""

    if type(exercise_id) is not str or not exercise_id:
        raise MasteryError("training exercise identity is unavailable")
    digest = hashlib.sha256(exercise_id.encode("utf-8")).hexdigest()
    return f"training:{digest[:32]}"


__all__ = ["outcome_from_completed_training"]
