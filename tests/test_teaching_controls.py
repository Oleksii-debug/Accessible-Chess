from __future__ import annotations

import unittest

from acs.teaching_controls import (
    AnnotationKind,
    CoachPointerService,
    PointerAction,
    StudentPointerEvent,
    TeachingAnnotation,
)


class CoachPointerServiceTests(unittest.TestCase):
    def test_typed_square_commits_and_requests_auto_clear_keep_focus(self) -> None:
        service = CoachPointerService()
        first = service.commit_text(" F3 ")
        second = service.commit_text("c7")
        self.assertEqual(first.square, "f3")
        self.assertTrue(first.clear_input)
        self.assertTrue(first.keep_focus)
        self.assertEqual(second.square, "c7")
        self.assertEqual(service.square, "c7")
        self.assertEqual(service.generation, 2)

    def test_invalid_square_never_changes_pointer(self) -> None:
        service = CoachPointerService()
        service.commit_text("a1")
        with self.assertRaises(ValueError):
            service.commit_text("z9")
        self.assertEqual(service.square, "a1")
        self.assertEqual(service.generation, 1)

    def test_student_pointer_history_is_accessible_and_bounded(self) -> None:
        service = CoachPointerService(history_limit=2)
        service.record_student_pointer(StudentPointerEvent("p1", "Марія", "e4", PointerAction.CLICK))
        service.record_student_pointer(StudentPointerEvent("p2", "Іван", "c6", PointerAction.POINT))
        service.record_student_pointer(StudentPointerEvent("p1", "Марія", "f3", PointerAction.FOCUS))
        self.assertEqual([event.square for event in service.student_history()], ["c6", "f3"])
        self.assertEqual(service.recent_accessible_text(), "Іван: c 6.\nМарія: f 3.")

    def test_pointer_history_does_not_carry_timestamp_requirement(self) -> None:
        event = StudentPointerEvent("p1", "Оля", "d8")
        self.assertNotIn("time", event.__dict__)
        self.assertEqual(event.accessible_text(), "Оля: d 8.")


class TeachingAnnotationTests(unittest.TestCase):
    def test_square_and_arrow_contracts_are_distinct(self) -> None:
        square = TeachingAnnotation("a1", AnnotationKind.SQUARE, "e4")
        arrow = TeachingAnnotation("a2", AnnotationKind.ARROW, "f3", "g5")
        self.assertEqual(square.source, "e4")
        self.assertIsNone(square.target)
        self.assertEqual((arrow.source, arrow.target), ("f3", "g5"))

    def test_arrow_requires_target(self) -> None:
        with self.assertRaises(ValueError):
            TeachingAnnotation("a1", AnnotationKind.ARROW, "e4")


if __name__ == "__main__":
    unittest.main()
