from __future__ import annotations

"""Evidence-only oracle for the complete local Training exercise journey.

This intentionally does not implement or repair Product behavior. It first proves
that the existing canonical Training domain, feedback projection, and durable
single-exercise resume work. It then fails if the current Version 2 application
profile cannot expose Training or provide a completed-exercise continuation.
"""

import json
import tempfile
from pathlib import Path

from acs.full_product_presenters import TrainingPresenter
from acs.full_product_ui_shell import UILanguage
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.training_progress_store import TrainingProgressStore
from acs.training_webview_projection import TrainingWebViewProjection
from acs.version2_profile import VERSION2_ROUTE_IDS, build_version2_action_registry

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def main() -> int:
    checks: dict[str, object] = {}
    failures: list[str] = []

    definition = ExerciseDefinition(
        exercise_id="qa-complete-journey-1",
        start_fen=START_FEN,
        title="QA complete journey",
        steps=(
            ExerciseStep(
                frozenset({"e4"}),
                hint="Пішак короля вперед на два поля.",
                explanation="Правильно.",
            ),
        ),
    )

    # Canonical position + legality/evaluation: illegal answer must not mutate.
    session = ExerciseSession(definition)
    initial_fen = session.current_fen
    rejected = session.submit("e5")
    checks["canonical_wrong_answer_rejected"] = not rejected.accepted
    checks["wrong_answer_position_unchanged"] = session.current_fen == initial_fen
    if rejected.accepted or session.current_fen != initial_fen:
        failures.append("canonical Training session accepted/mutated on an illegal answer")

    # Correct answer + feedback through the existing presenter/projection.
    feedback_session = ExerciseSession(definition)
    presenter = TrainingPresenter(feedback_session, language=UILanguage.UA)
    projection = TrainingWebViewProjection(presenter, language=UILanguage.UA)
    event = projection.submit("e4")
    completed_snapshot = event.payload["snapshot"]
    checks["canonical_correct_answer_completed"] = bool(completed_snapshot["progress"]["completed"])
    checks["feedback_announced"] = event.payload.get("announcement") == "Вправу завершено."
    if not checks["canonical_correct_answer_completed"]:
        failures.append("canonical correct answer did not complete the one-step exercise")
    if not checks["feedback_announced"]:
        failures.append("completed exercise did not produce canonical accessible feedback")

    # Durable progress + restart for the same exercise.
    with tempfile.TemporaryDirectory(prefix="accessible-chess-training-oracle-") as raw:
        store = TrainingProgressStore(Path(raw) / "progress.json")
        revision = store.save(feedback_session, expected_revision=None)
        loaded = store.load(definition)
        checks["durable_progress_saved"] = isinstance(revision, str) and len(revision) == 64
        checks["restart_restores_completed_session"] = bool(
            loaded is not None
            and loaded.session.completed
            and loaded.session.current_fen == feedback_session.current_fen
            and loaded.session.accepted_path == feedback_session.accepted_path
        )
        if not checks["restart_restores_completed_session"]:
            failures.append("durable Training progress did not restore the exact completed session")

    # Complete-journey release reachability. These are intentionally RED on the
    # inspected current runtime if Training is still deferred from Version 2.
    registry_ids = {definition.action_id for definition in build_version2_action_registry().definitions()}
    checks["v2_training_route_exposed"] = "training" in VERSION2_ROUTE_IDS
    checks["v2_training_screen_action_exposed"] = "screen.training" in registry_ids
    checks["v2_training_submit_action_exposed"] = "training.submit" in registry_ids
    if not checks["v2_training_route_exposed"]:
        failures.append("Version 2 application profile exposes no Training route")
    if not checks["v2_training_screen_action_exposed"]:
        failures.append("Version 2 ActionRegistry exposes no screen.training action")
    if not checks["v2_training_submit_action_exposed"]:
        failures.append("Version 2 ActionRegistry exposes no training.submit action")

    # A completed exercise must offer a deterministic continuation owned by an
    # application/training collection layer. Do not invent a rules engine here.
    commands = tuple(action.get("command", "") for action in completed_snapshot["actions"])
    continuation = tuple(
        command for command in commands
        if command.startswith("training.") and ("next" in command or "continue" in command)
    )
    checks["completed_exercise_has_next_exercise_action"] = bool(continuation)
    checks["completed_exercise_actions"] = commands
    if not continuation:
        failures.append("completed Training projection has no next/continue exercise action")

    result = {
        "oracle": "training_complete_journey",
        "product_mutation": "NONE",
        "checks": checks,
        "failures": failures,
        "status": "RED" if failures else "GREEN",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
