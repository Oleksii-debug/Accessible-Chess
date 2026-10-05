from __future__ import annotations

import unittest

from acs.bookdocument import BookDocument
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.full_product_presenters import TrainingPresenter, TrainingView
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStatus, ExerciseStep
from acs.training_webview_bridge import TrainingWebViewBridge
from acs.training_webview_projection import TrainingWebViewProjection
from acs.version2_training_workspace import Version2BookTrainingWorkspace


class TrainingPresentationPassiveAuthorityTests(unittest.TestCase):
    @staticmethod
    def _session() -> ExerciseSession:
        definition = ExerciseDefinition(
            "presentation-passive",
            Board.START,
            (ExerciseStep(frozenset({"e4"}), hint="Play in the centre."),),
            title="Passive training",
        )
        return ExerciseSession(definition)

    def test_presenter_rejects_session_subclass_before_state_hook(self) -> None:
        class HostileSession(ExerciseSession):
            touched = False

            def snapshot(self):
                type(self).touched = True
                raise AssertionError("session subclass snapshot hook must not execute")

        hostile = HostileSession.__new__(HostileSession)

        with self.assertRaisesRegex(
            TypeError,
            "^training presenter session must be ExerciseSession$",
        ):
            TrainingPresenter(hostile)

        self.assertFalse(HostileSession.touched)

    def test_projection_rejects_presenter_subclass_before_language_hook(self) -> None:
        class HostilePresenter(TrainingPresenter):
            touched = False

            def set_language(self, language):
                type(self).touched = True
                raise AssertionError("presenter subclass language hook must not execute")

        hostile = HostilePresenter.__new__(HostilePresenter)

        with self.assertRaisesRegex(
            TypeError,
            "^presenter must be TrainingPresenter$",
        ):
            TrainingWebViewProjection(hostile)

        self.assertFalse(HostilePresenter.touched)

    def test_bridge_rejects_projection_subclass_before_projection_hook(self) -> None:
        class HostileProjection(TrainingWebViewProjection):
            touched = False

            def snapshot(self):
                type(self).touched = True
                raise AssertionError("projection subclass hook must not execute")

        hostile = HostileProjection.__new__(HostileProjection)

        with self.assertRaisesRegex(
            TypeError,
            "^projection must be TrainingWebViewProjection$",
        ):
            TrainingWebViewBridge(hostile)

        self.assertFalse(HostileProjection.touched)

    def test_projection_rejects_training_view_subclass_before_field_hook(self) -> None:
        presenter = TrainingPresenter(self._session())
        projection = TrainingWebViewProjection(presenter)

        class HostileTrainingView(TrainingView):
            touched = False

            def __getattribute__(self, name):
                if name not in {"touched", "__class__"}:
                    type(self).touched = True
                    raise AssertionError(
                        f"TrainingView subclass field hook must not execute: {name}"
                    )
                return super().__getattribute__(name)

        hostile = HostileTrainingView.__new__(HostileTrainingView)

        with self.assertRaisesRegex(
            TypeError,
            "^TrainingPresenter must return TrainingView$",
        ):
            projection._snapshot_from_view(hostile)

        self.assertFalse(HostileTrainingView.touched)

    def test_workspace_rejects_reader_subclass_before_navigation_hook(self) -> None:
        class HostileReader(BookReader):
            touched = False

            def location(self):
                type(self).touched = True
                raise AssertionError("BookReader subclass navigation hook must not execute")

        hostile = HostileReader.__new__(HostileReader)

        with self.assertRaisesRegex(TypeError, "^reader must be BookReader$"):
            Version2BookTrainingWorkspace(hostile, progress_root=".")

        self.assertFalse(HostileReader.touched)

    def test_exact_training_presentation_chain_remains_usable(self) -> None:
        session = self._session()
        presenter = TrainingPresenter(session)
        projection = TrainingWebViewProjection(presenter)
        bridge = TrainingWebViewBridge(projection)

        snapshot = projection.snapshot()

        self.assertEqual(snapshot["status"], ExerciseStatus.READY.value)
        self.assertEqual(snapshot["title"], "Passive training")
        self.assertIs(bridge.projection, projection)
        self.assertIs(presenter.session, session)

        reader = BookReader(BookDocument("Workspace", blocks=[]))
        workspace = Version2BookTrainingWorkspace(reader, progress_root=".")
        self.assertIs(workspace.reader, reader)


if __name__ == "__main__":
    unittest.main()
