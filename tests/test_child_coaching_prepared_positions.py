from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from acs import classroom_domain as cd
from acs import education_workspace as ew
from acs.child_coaching_application import (
    ChildCoachingApplication,
    ChildCoachingApplicationError,
)
from acs.child_coaching_prepared_positions import (
    ChildCoachingPreparedPositionError,
    PreparedPositionNavigator,
)
from acs.child_coaching_store import ChildCoachingTemplateStore
from acs.teaching_session import PositionSourceKind, TeachingPositionSource


class ChildCoachingPreparedPositionTests(unittest.TestCase):
    def make_context(self, temp: str):
        workspace = ew.EducationWorkspace.empty(cd.ClassroomSnapshot())
        workspace = ew.save_prepared_position(
            workspace,
            position_id="prep-start",
            source=TeachingPositionSource(PositionSourceKind.START),
            expected_position_revision=0,
        )
        workspace = ew.save_prepared_position(
            workspace,
            position_id="prep-fen",
            source=TeachingPositionSource(
                PositionSourceKind.FEN,
                fen="8/8/8/8/8/8/4K3/6k1 w - - 0 1",
            ),
            expected_position_revision=0,
        )
        workspace = ew.save_prepared_position(
            workspace,
            position_id="prep-pgn",
            source=TeachingPositionSource(
                PositionSourceKind.PGN,
                source_ref="game-17",
                source_index=3,
            ),
            expected_position_revision=0,
        )
        holder = {"workspace": workspace}
        app = ChildCoachingApplication(
            ChildCoachingTemplateStore(Path(temp) / "child-coaching.json")
        )
        navigator = PreparedPositionNavigator(
            app,
            lambda: holder["workspace"],
        )
        return holder, app, navigator

    def test_snapshot_selects_first_and_next_previous_preserve_workspace_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, _, navigator = self.make_context(temp)
            first = navigator.snapshot()
            self.assertEqual(first.count, 3)
            self.assertEqual(first.selected_position_id, "prep-start")
            self.assertEqual(first.selected_index, 0)
            self.assertTrue(first.positions[0].selected)
            self.assertIn("start", first.positions[0].accessible_text)

            second = navigator.next()
            self.assertEqual(second.selected_position_id, "prep-fen")
            self.assertEqual(second.selected_index, 1)
            third = navigator.next()
            self.assertEqual(third.selected_position_id, "prep-pgn")
            back = navigator.previous()
            self.assertEqual(back.selected_position_id, "prep-fen")

    def test_navigation_boundaries_fail_without_wraparound(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, _, navigator = self.make_context(temp)
            navigator.snapshot()
            with self.assertRaisesRegex(
                ChildCoachingPreparedPositionError,
                "boundary reached",
            ):
                navigator.previous()
            navigator.select("prep-pgn")
            with self.assertRaisesRegex(
                ChildCoachingPreparedPositionError,
                "boundary reached",
            ):
                navigator.next()

    def test_selection_survives_workspace_refresh_by_stable_position_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            holder, _, navigator = self.make_context(temp)
            navigator.select("prep-fen")
            source = TeachingPositionSource(
                PositionSourceKind.DATABASE,
                source_ref="acsdb-99",
            )
            holder["workspace"] = ew.save_prepared_position(
                holder["workspace"],
                position_id="prep-fen",
                source=source,
                expected_position_revision=0,
            )
            snap = navigator.snapshot()
            self.assertEqual(snap.selected_position_id, "prep-fen")
            self.assertEqual(navigator.current().revision, 1)
            self.assertEqual(navigator.current_source(), source)

    def test_removed_explicit_selection_does_not_silently_fall_back_to_another_position(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            holder, _, navigator = self.make_context(temp)
            navigator.select("prep-fen")
            holder["workspace"] = replace(
                holder["workspace"],
                prepared_positions=tuple(
                    item
                    for item in holder["workspace"].prepared_positions
                    if item.position_id != "prep-fen"
                ),
            )

            snapshot = navigator.snapshot()
            self.assertIsNone(snapshot.selected_position_id)
            self.assertTrue(all(not item.selected for item in snapshot.positions))
            with self.assertRaisesRegex(
                ChildCoachingPreparedPositionError,
                "select again",
            ):
                navigator.current()
            with self.assertRaisesRegex(
                ChildCoachingPreparedPositionError,
                "select again",
            ):
                navigator.next()

            recovered = navigator.select("prep-pgn")
            self.assertEqual(recovered.selected_position_id, "prep-pgn")

    def test_empty_workspace_has_no_selection_and_launch_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = ew.EducationWorkspace.empty(cd.ClassroomSnapshot())
            app = ChildCoachingApplication(
                ChildCoachingTemplateStore(Path(temp) / "child-coaching.json")
            )
            navigator = PreparedPositionNavigator(app, lambda: workspace)
            snap = navigator.snapshot()
            self.assertEqual(snap.count, 0)
            self.assertIsNone(snap.selected_position_id)
            with self.assertRaisesRegex(
                ChildCoachingPreparedPositionError,
                "no prepared positions",
            ):
                navigator.current_source()

    def test_launch_current_reuses_exact_canonical_source_and_template_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, app, navigator = self.make_context(temp)
            catalog = app.open_catalog()
            navigator.select("prep-fen")
            selected = navigator.current()
            session = navigator.launch_current(
                "preset-preschool-4-6",
                session_id="prepared-session",
                lesson_id="lesson-1",
                student_ids=("student-1",),
                require_no_notation=True,
                expected_template_revision=catalog.revision,
            )
            self.assertEqual(session.source, selected.source)
            self.assertEqual(session.source.kind, PositionSourceKind.FEN)
            self.assertEqual(
                session.source.fen,
                selected.source.fen,
            )

    def test_launch_can_reject_stale_reviewed_prepared_position_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            holder, app, navigator = self.make_context(temp)
            catalog = app.open_catalog()
            navigator.select("prep-fen")
            reviewed = navigator.current()
            holder["workspace"] = ew.save_prepared_position(
                holder["workspace"],
                position_id="prep-fen",
                source=TeachingPositionSource(
                    PositionSourceKind.FEN,
                    fen="8/8/8/8/8/8/3K4/6k1 w - - 0 1",
                ),
                expected_position_revision=reviewed.revision,
            )

            with self.assertRaisesRegex(
                ChildCoachingPreparedPositionError,
                "changed; review it before launching",
            ):
                navigator.launch_current(
                    "preset-preschool-4-6",
                    session_id="stale-position-session",
                    lesson_id="lesson-1",
                    expected_template_revision=catalog.revision,
                    expected_position_revision=reviewed.revision,
                )

            current = navigator.current()
            launched = navigator.launch_current(
                "preset-preschool-4-6",
                session_id="current-position-session",
                lesson_id="lesson-1",
                expected_template_revision=catalog.revision,
                expected_position_revision=current.revision,
            )
            self.assertEqual(launched.source, current.source)

    def test_launch_rejects_stale_reviewed_template_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, app, navigator = self.make_context(temp)
            reviewed = app.open_catalog()
            app.copy_template(
                "preset-preschool-4-6",
                template_id="concurrent-change",
                title="Concurrent change",
                expected_revision=reviewed.revision,
            )
            with self.assertRaisesRegex(
                ChildCoachingApplicationError,
                "changed; reopen",
            ):
                navigator.launch_current(
                    "preset-preschool-4-6",
                    session_id="stale-prepared-session",
                    lesson_id="lesson-1",
                    expected_template_revision=reviewed.revision,
                )

    def test_adapter_never_persists_a_second_prepared_position_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            holder, _, navigator = self.make_context(temp)
            before = holder["workspace"].to_json()
            navigator.select("prep-fen")
            navigator.next()
            navigator.previous()
            navigator.current_source()
            self.assertEqual(holder["workspace"].to_json(), before)


if __name__ == "__main__":
    unittest.main()
