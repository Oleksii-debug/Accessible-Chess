from __future__ import annotations

import unittest
from pathlib import Path

from acs.child_coaching_ui import ChildCoachingPresentationState
from acs.keybindings import BindingContext
from acs.lesson_plan import LessonItem, LessonItemKind, LessonPlan, LessonPosition
from acs.teaching_actions import TEACHING_ACTIONS, build_teaching_action_registry
from acs.teaching_webapp import TeachingAccessibleChessAPI


START = "8/8/8/8/8/8/8/K6k w - - 0 1"
SECOND = "8/8/8/8/8/8/1K6/7k b - - 0 1"
THIRD = "8/8/8/8/8/2K5/8/7k w - - 0 1"


def lesson() -> LessonPlan:
    positions = (
        LessonPosition("p1", "Перша", START, "Покажи короля", "Не підказувати"),
        LessonPosition("p2", "Друга", SECOND, "Знайди поле"),
        LessonPosition("p3", "Третя", THIRD, "Постав вказівник"),
    )
    items = (
        LessonItem("warm", LessonItemKind.WARM_UP, "Розминка", 5),
        LessonItem("pos", LessonItemKind.POSITION, "Позиції", 10, "p1"),
    )
    return LessonPlan("lesson-one", "Перший урок", "7-8", "beginner", items, positions)


class ChildCoachingUiTests(unittest.TestCase):
    def test_teaching_actions_use_existing_central_registry_and_are_remappable(self) -> None:
        registry = build_teaching_action_registry()
        ids = {item.action_id for item in TEACHING_ACTIONS}
        self.assertIn("teaching.lesson.next_position", ids)
        self.assertIn("teaching.pointer_input", ids)
        self.assertTrue(all(item.context is BindingContext.DOCUMENT for item in TEACHING_ACTIONS))
        self.assertTrue(all(registry.get_binding(action_id) is None for action_id in ids))
        registry.set_binding("teaching.lesson.next_position", "Ctrl+Alt+N")
        resolved = registry.resolve_binding(BindingContext.DOCUMENT, "Ctrl+Alt+N")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.action_id, "teaching.lesson.next_position")

    def test_age_presets_are_editable_and_preschool_stays_short(self) -> None:
        state = ChildCoachingPresentationState()
        snap = state.snapshot()
        presets = {item["templateId"]: item for item in snap["templates"]}
        self.assertEqual(set(presets), {"preschool", "young-beginner", "school-age"})
        self.assertGreaterEqual(presets["preschool"]["plannedMinutes"], 25)
        self.assertLessEqual(presets["preschool"]["plannedMinutes"], 35)
        original = presets["preschool"]["plannedMinutes"]
        updated = state.edit_template_block("movement", duration_minutes=8)
        self.assertEqual(updated["plannedMinutes"], original + 2)
        fresh = ChildCoachingPresentationState().snapshot()["template"]
        self.assertEqual(fresh["plannedMinutes"], original)

    def test_beginner_pointer_answer_does_not_require_san_or_mutate_board(self) -> None:
        state = ChildCoachingPresentationState()
        result = state.pointer_only_answer("Марко", "f3")
        self.assertTrue(result["ok"])
        self.assertFalse(result["boardMutation"])
        self.assertFalse(result["notationRequired"])
        self.assertEqual(result["accessibleText"], "Марко: f 3.")
        tasks = state.snapshot()["noNotationTasks"]
        self.assertTrue(tasks)
        self.assertTrue(all(not task["notationRequired"] for task in tasks))
        self.assertTrue(any(task["responseMode"] == "pointer" for task in tasks))

    def test_prepared_positions_navigate_without_mutating_lesson_and_deploy_targets(self) -> None:
        source = lesson()
        state = ChildCoachingPresentationState(lesson=source)
        self.assertEqual(state.snapshot()["prepared"]["position"]["fen"], START)
        state.next_position()
        self.assertEqual(state.snapshot()["prepared"]["position"]["fen"], SECOND)
        group = state.deploy_selected("group", group_id="blue")
        self.assertTrue(group["ok"])
        self.assertEqual(group["fen"], SECOND)
        self.assertEqual(group["groupId"], "blue")
        self.assertFalse(group["mutatesGameHere"])
        selected = state.deploy_selected("participants", participant_ids=("s1", "s2"))
        self.assertEqual(selected["participantIds"], ["s1", "s2"])
        state.previous_position()
        self.assertEqual(state.snapshot()["prepared"]["position"]["fen"], START)
        self.assertEqual(source.positions[1].fen, SECOND)

    def test_remapped_action_dispatches_prepared_position_navigation(self) -> None:
        registry = build_teaching_action_registry()
        registry.set_binding("teaching.lesson.next_position", "Ctrl+Alt+N")
        state = ChildCoachingPresentationState(action_registry=registry, lesson=lesson())
        result = state.dispatch_binding("Ctrl+Alt+N")
        self.assertTrue(result["available"])
        self.assertEqual(result["position"]["fen"], SECOND)

    def test_rotation_supervision_is_keyboard_action_addressable(self) -> None:
        state = ChildCoachingPresentationState()
        first = state.start_rotation(("a", "b", "c", "d"), base_seconds=300, increment_seconds=3)
        self.assertEqual(len(first["pairings"]), 2)
        self.assertIn("a — білі", first["accessibleText"])
        second_board = state.dispatch("teaching.rotation.next_board")
        self.assertEqual(second_board["currentBoardIndex"], 1)
        next_round = state.dispatch("teaching.rotation.next_round")
        self.assertEqual(next_round["round"], 2)
        self.assertNotEqual(first["pairings"][0]["white"], next_round["pairings"][0]["white"])
        demo = state.dispatch("teaching.rotation.return_demo")
        self.assertTrue(demo["demonstrationMode"])
        self.assertEqual(demo["accessibleText"], "Демонстраційний режим.")

    def test_web_api_exposes_coaching_without_release_webapp_dependency(self) -> None:
        api = TeachingAccessibleChessAPI(coaching=ChildCoachingPresentationState(lesson=lesson()))
        self.assertEqual(api.coaching_snapshot()["prepared"]["count"], 3)
        self.assertEqual(api.coaching_next_position()["position"]["positionId"], "p2")
        source = Path("acs/teaching_webapp.py").read_text(encoding="utf-8")
        self.assertIn("ChildCoachingPresentationState", source)
        self.assertIn("child_coaching.html", source)
        self.assertNotIn("from .webapp import", source)

    def test_child_coaching_document_is_semantic_and_has_one_live_region(self) -> None:
        source = Path("web/child_coaching.html").read_text(encoding="utf-8")
        self.assertIn("План уроку й робота з групою", source)
        self.assertIn("Завдання без нотації", source)
        self.assertIn("Підготовлені позиції", source)
        self.assertIn("Пари й ротації", source)
        self.assertIn("центральному Action Registry", source)
        self.assertIn("SAN вводити не потрібно", source)
        self.assertEqual(source.count('aria-live="polite"'), 1)
        self.assertNotIn("document.addEventListener('keydown'", source)
        self.assertNotIn('document.addEventListener("keydown"', source)


if __name__ == "__main__":
    unittest.main()
