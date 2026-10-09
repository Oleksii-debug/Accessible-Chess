import unittest

from acs import classroom_domain as cd
from acs.education_webview_projection import (
    EDUCATION_COLLECTION_ORDER,
    EducationCollection,
    EducationWebViewProjection,
)
from acs.education_workspace import EducationWorkspace
from acs.full_product_ui_shell import UILanguage


STAMP = "2026-08-25T08:00:00Z"


def classroom(*, class_count: int = 1) -> cd.ClassroomSnapshot:
    classes = tuple(
        cd.ClassroomClass(
            f"private-class-{index}",
            f"Class {index}",
            ("private-group-1",) if index == 1 else (),
        )
        for index in range(1, class_count + 1)
    )
    return cd.ClassroomSnapshot(
        students=(cd.Student("private-student-1", "Knight 17", cd.ConsentState.GRANTED),),
        classes=classes,
        groups=(cd.Group("private-group-1", "private-class-1", "Group A"),),
        courses=(cd.Course("private-course-1", "Tactics", ("private-lesson-1",)),),
        cohorts=(
            cd.Cohort(
                "private-cohort-1",
                "private-course-1",
                ("private-student-1",),
            ),
        ),
        materials=(
            cd.LessonMaterial(
                "private-exercise-1",
                "exercise",
                "Fork exercise",
                "private-source-ref",
            ),
        ),
        lessons=(
            cd.Lesson(
                "private-lesson-1",
                "private-course-1",
                "Forks",
                ("private-exercise-1",),
                STAMP,
            ),
        ),
        assignments=(
            cd.Assignment(
                "private-assignment-1",
                "private-lesson-1",
                "private-cohort-1",
                "Fork homework",
                STAMP,
                "2026-09-01T08:00:00Z",
            ),
        ),
        homework=(
            cd.Homework(
                "private-homework-1",
                "private-assignment-1",
                "private-student-1",
                cd.HomeworkStatus.SUBMITTED,
                "private-response-ref",
            ),
        ),
        student_games=(
            cd.StudentGame(
                "private-student-game-1",
                "private-student-1",
                "private-canonical-game-1",
                "private-assignment-1",
            ),
        ),
        results=(
            cd.Result(
                "private-result-1",
                "private-student-1",
                "private-assignment-1",
                "passed",
                8750,
            ),
        ),
        progress=(
            cd.Progress(
                "private-progress-1",
                "private-student-1",
                "private-course-1",
                ("private-lesson-1",),
            ),
        ),
    )


class EducationWebViewProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = EducationWorkspace.empty(classroom())
        self.calls: list[tuple[str, dict[str, object]]] = []

        def dispatch(action: str, payload: dict[str, object]):
            self.calls.append((action, dict(payload)))
            return {"private_backend_result": "must-not-cross"}

        self.projection = EducationWebViewProjection(
            lambda: self.workspace,
            dispatch,
            language=UILanguage.EN,
            page_size=2,
        )

    @staticmethod
    def section(snapshot: dict[str, object], kind: str) -> dict[str, object]:
        return next(item for item in snapshot["sections"] if item["kind"] == kind)

    def test_all_requested_collections_are_projected_without_private_authority_fields(self) -> None:
        snapshot = self.projection.snapshot()
        self.assertEqual(
            [kind.value for kind in EDUCATION_COLLECTION_ORDER],
            [item["kind"] for item in snapshot["sections"]],
        )
        rendered = repr(snapshot)
        for forbidden in (
            "private-student-1",
            "private-source-ref",
            "private-response-ref",
            "private-canonical-game-1",
            "private-assignment-1",
            "classroom_digest",
            "revision",
            "operation_receipts",
        ):
            self.assertNotIn(forbidden, rendered)
        for section in snapshot["sections"]:
            self.assertTrue(section["items"], section["kind"])
            for item in section["items"]:
                self.assertRegex(item["item_key"], r"^[0-9a-f]{64}$")
                self.assertNotIn("record_id", item)
        self.assertEqual(
            "Fork exercise",
            self.section(snapshot, "exercise")["items"][0]["label"],
        )
        self.assertEqual(
            "87.5%",
            self.section(snapshot, "result")["items"][0]["status"].split(", ")[1],
        )

    def test_only_existing_registered_open_actions_and_new_class_are_delegated(self) -> None:
        snapshot = self.projection.snapshot()
        opened = self.projection.open_selected(EducationCollection.CLASS)
        self.assertEqual("delegated", opened.kind)
        self.assertEqual(
            ("classes.open", {"record_id": "private-class-1"}),
            self.calls[-1],
        )
        self.assertNotIn("private_backend_result", repr(opened))

        assignment = self.section(snapshot, "assignment")
        selected = self.projection.select("assignment", assignment["items"][0]["item_key"])
        self.assertEqual("selection", selected.kind)
        self.assertEqual("delegated", self.projection.open_selected("assignment").kind)
        self.assertEqual("classes.assignment_open", self.calls[-1][0])

        unsupported = self.projection.open_selected(EducationCollection.COURSE)
        self.assertEqual("error", unsupported.kind)
        self.assertNotIn("course", unsupported.payload["message"].lower())
        self.assertEqual("delegated", self.projection.new_class().kind)
        self.assertEqual(("classes.new", {}), self.calls[-1])

    def test_selection_crosses_page_boundary_without_unbounded_snapshot(self) -> None:
        workspace = EducationWorkspace.empty(classroom(class_count=3))
        projection = EducationWebViewProjection(
            lambda: workspace,
            lambda _action, _payload: None,
            language=UILanguage.EN,
            page_size=2,
        )
        first = self.section(projection.snapshot(), "class")
        self.assertEqual(2, len(first["items"]))
        self.assertEqual((1, 2), (first["page"], first["page_count"]))
        self.assertFalse(first["can_previous"])
        self.assertTrue(first["can_next"])

        self.assertEqual("selection", projection.move_selection("class", 1).kind)
        crossed = projection.move_selection("class", 1)
        self.assertEqual("selection", crossed.kind)
        self.assertEqual(2, crossed.payload["snapshot"]["page"])
        self.assertEqual(1, len(crossed.payload["snapshot"]["items"]))
        self.assertTrue(crossed.payload["focus_target"])
        previous = projection.change_page("class", -1)
        self.assertEqual(1, previous.payload["snapshot"]["page"])

    def test_browser_projection_operations_never_mutate_workspace(self) -> None:
        before = self.workspace.to_json()
        snapshot = self.projection.snapshot()
        student = self.section(snapshot, "student")
        self.projection.select("student", student["items"][0]["item_key"])
        self.projection.move_selection("class", 1)
        self.projection.change_page("class", 1)
        self.assertEqual(before, self.workspace.to_json())


if __name__ == "__main__":
    unittest.main()
