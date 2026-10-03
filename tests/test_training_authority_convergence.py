from __future__ import annotations

import tempfile
import unittest
from collections import UserDict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument, Exercise, Heading
from acs.bookreader import BookReader
from acs.book_webview_bridge import BookWebViewBridge
from acs.book_webview_projection import BookWebViewProjection
from acs.chesscore import Board
from acs.full_product_presenters import BookReaderPresenter, TrainingPresenter
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.full_product_ui_shell import UILanguage
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.training_webview_bridge import TrainingWebViewBridge
from acs.training_webview_projection import TrainingWebViewProjection
from acs.version2_application import Version2Application
from acs.version2_training_workspace import Version2BookTrainingWorkspace


class TrainingAuthorityConvergenceTests(unittest.TestCase):
    def definition(self) -> ExerciseDefinition:
        return ExerciseDefinition(
            "authority",
            Board.START,
            (
                ExerciseStep(
                    frozenset({"e4"}),
                    hint="Authored hint",
                    explanation="Authored explanation",
                ),
                ExerciseStep(frozenset({"e5"})),
            ),
            title="Canonical training",
        )

    def test_session_preserves_finite_collection_and_mapping_compatibility(self) -> None:
        definition = ExerciseDefinition(
            "compat",
            Board.START,
            iter((ExerciseStep(frozenset({"e4"})),)),
            tags=iter(("Tactic", "Opening")),
            metadata=UserDict({"origin": "book"}),
        )
        session = ExerciseSession(definition)
        self.assertEqual(("tactic", "opening"), session.canonical_definition.tags)
        self.assertEqual({"origin": "book"}, session.canonical_definition.metadata)
        self.assertTrue(session.submit("e4").completed)

    def test_session_rejects_post_construction_container_substitution_before_hooks(self) -> None:
        class HostileSteps:
            touched = False

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("hostile steps iterator must not execute")

        class HostileMetadata(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("hostile metadata len must not execute")

            def items(self):
                type(self).touched = True
                raise AssertionError("hostile metadata items must not execute")

        definition = self.definition()
        object.__setattr__(definition, "steps", HostileSteps())
        with self.assertRaisesRegex(TypeError, "exact tuple"):
            ExerciseSession(definition)
        self.assertFalse(HostileSteps.touched)

        definition = self.definition()
        object.__setattr__(definition, "metadata", HostileMetadata({"x": "y"}))
        with self.assertRaisesRegex(TypeError, "exact dict"):
            ExerciseSession(definition)
        self.assertFalse(HostileMetadata.touched)

    def test_session_detaches_from_caller_owned_step_mutation(self) -> None:
        step = ExerciseStep(frozenset({"e4"}))
        definition = ExerciseDefinition("detached", Board.START, (step,))
        session = ExerciseSession(definition)

        object.__setattr__(step, "accepted_moves", frozenset({"d4"}))

        self.assertEqual(frozenset({"e4"}), session.current_step().accepted_moves)
        self.assertTrue(session.submit("e4").completed)

    def test_bound_definition_replacement_fails_closed(self) -> None:
        session = ExerciseSession(self.definition())
        session.definition = ExerciseDefinition(
            "replacement",
            Board.START,
            (ExerciseStep(frozenset({"d4"})),),
        )

        with self.assertRaisesRegex(ValueError, "changed during session"):
            session.current_step()
        with self.assertRaisesRegex(ValueError, "changed during session"):
            session.snapshot()

    def test_low_level_bound_mutation_fails_before_semantic_use(self) -> None:
        session = ExerciseSession(self.definition())
        object.__setattr__(session.definition.steps[0], "hint", "changed")

        with self.assertRaisesRegex(ValueError, "changed during session"):
            session.request_hint()

    def test_hostile_internal_container_substitution_does_not_execute_hooks(self) -> None:
        class HostileDict(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("hostile metadata len must not execute")

            def items(self):
                type(self).touched = True
                raise AssertionError("hostile metadata items must not execute")

        session = ExerciseSession(self.definition())
        object.__setattr__(session.definition, "metadata", HostileDict({"x": "y"}))

        with self.assertRaisesRegex(TypeError, "exact dict"):
            session.snapshot()
        self.assertFalse(HostileDict.touched)

    def test_snapshot_non_text_key_fails_deterministically(self) -> None:
        session = ExerciseSession(self.definition())
        snapshot = session.snapshot()
        snapshot[7] = snapshot.pop("status")  # type: ignore[index]

        with self.assertRaisesRegex(TypeError, "field names must be strings"):
            ExerciseSession.restore(self.definition(), snapshot)

    def test_restore_state_is_atomic_and_preserves_session_identity(self) -> None:
        session = ExerciseSession(self.definition())
        retained = session
        session.submit("e4")
        before = session.snapshot()
        invalid = dict(before)
        invalid["status"] = "ready"

        with self.assertRaises(ValueError):
            session.restore_state(invalid)

        self.assertIs(retained, session)
        self.assertEqual(before, session.snapshot())

        fresh = ExerciseSession(self.definition())
        baseline = fresh.snapshot()
        fresh.submit("e4")
        fresh.restore_state(baseline)
        self.assertIsNotNone(fresh.current_step())
        self.assertEqual(baseline, fresh.snapshot())

    def test_projection_has_message_contract_on_initial_snapshot(self) -> None:
        presenter = TrainingPresenter(ExerciseSession(self.definition()), language=UILanguage.EN)
        projection = TrainingWebViewProjection(presenter, language=UILanguage.EN)

        snapshot = projection.snapshot()

        self.assertEqual("", presenter.message)
        self.assertIsNone(presenter.message_key)
        self.assertEqual("ready", snapshot["status"])

    def test_presentation_message_relocalizes_but_authored_hint_does_not(self) -> None:
        presenter = TrainingPresenter(ExerciseSession(self.definition()), language=UILanguage.EN)
        projection = TrainingWebViewProjection(presenter, language=UILanguage.EN)

        wrong = projection.submit("Nf3")
        self.assertEqual("retry", presenter.message_key)
        self.assertIn("Try again", wrong.payload["announcement"])

        switched = projection.set_language(UILanguage.UA)
        self.assertEqual("retry", presenter.message_key)
        self.assertEqual("Спробуйте ще раз.", presenter.message)
        self.assertEqual("Спробуйте ще раз.", switched.payload["snapshot"]["message"])

        hinted = projection.hint()
        self.assertEqual("Authored hint", hinted.payload["announcement"])
        self.assertIsNone(presenter.message_key)
        projection.set_language(UILanguage.EN)
        self.assertEqual("Authored hint", presenter.message)

    def test_presenter_restore_relocalizes_owned_message_for_target_locale(self) -> None:
        definition = self.definition()
        session = ExerciseSession(definition)
        snapshot = session.snapshot()

        restored = TrainingPresenter.restore(
            definition,
            snapshot,
            language=UILanguage.UA,
            message="Try again.",
            message_key="retry",
        )

        self.assertEqual("retry", restored.message_key)
        self.assertEqual("Спробуйте ще раз.", restored.message)

    def test_projection_host_restore_preserves_presenter_and_session_identity(self) -> None:
        presenter = TrainingPresenter(ExerciseSession(self.definition()), language=UILanguage.EN)
        projection = TrainingWebViewProjection(presenter, language=UILanguage.EN)
        retained_session = presenter.session
        before = presenter.snapshot()

        projection.submit("e4")
        projection.restore_state(
            before,
            language=UILanguage.EN,
            message="Try again.",
            message_key="retry",
        )

        self.assertIs(retained_session, presenter.session)
        self.assertEqual(before, presenter.snapshot())
        self.assertEqual("retry", presenter.message_key)
        self.assertEqual("Try again.", presenter.message)

    def test_invalid_message_key_is_rejected_before_progress_restore(self) -> None:
        presenter = TrainingPresenter(ExerciseSession(self.definition()), language=UILanguage.EN)
        before = presenter.snapshot()
        presenter.session.submit("e4")
        progressed = presenter.snapshot()

        with self.assertRaisesRegex(ValueError, "message key is invalid"):
            presenter.restore_state(before, message="stale", message_key="unknown")

        self.assertEqual(progressed, presenter.snapshot())

    def test_failed_submit_render_rolls_back_progress_message_and_identity(self) -> None:
        presenter = TrainingPresenter(ExerciseSession(self.definition()), language=UILanguage.EN)
        projection = TrainingWebViewProjection(presenter, language=UILanguage.EN)
        projection.submit("Nf3")
        before = presenter.snapshot()
        before_message = presenter.message
        before_key = presenter.message_key
        retained = presenter.session

        with patch.object(projection, "_render", side_effect=ValueError("render failed")):
            with self.assertRaisesRegex(ValueError, "render failed"):
                projection.submit("e4")

        self.assertIs(retained, presenter.session)
        self.assertEqual(before, presenter.snapshot())
        self.assertEqual(before_message, presenter.message)
        self.assertEqual(before_key, presenter.message_key)

    def test_failed_hint_reset_reveal_and_retry_renders_are_atomic(self) -> None:
        operations = ("hint", "reset", "reveal", "retry")
        for operation in operations:
            with self.subTest(operation=operation):
                presenter = TrainingPresenter(
                    ExerciseSession(self.definition()),
                    language=UILanguage.EN,
                )
                projection = TrainingWebViewProjection(presenter, language=UILanguage.EN)
                projection.submit("Nf3")
                before = presenter.snapshot()
                before_message = presenter.message
                before_key = presenter.message_key

                with patch.object(projection, "_render", side_effect=ValueError("render failed")):
                    with self.assertRaisesRegex(ValueError, "render failed"):
                        if operation == "hint":
                            projection.hint()
                        elif operation == "reset":
                            projection.reset(confirmed=True)
                        elif operation == "reveal":
                            projection.reveal()
                        else:
                            projection.retry()

                self.assertEqual(before, presenter.snapshot())
                self.assertEqual(before_message, presenter.message)
                self.assertEqual(before_key, presenter.message_key)

    def test_workspace_persistence_failure_rolls_back_in_place(self) -> None:
        document = BookDocument(
            title="Training rollback",
            blocks=[
                Exercise(
                    fen=Board.START,
                    prompt="Play e4",
                    answer_text="e4",
                    block_id="exercise-one",
                )
            ],
        )
        reader = BookReader(document)
        with tempfile.TemporaryDirectory(prefix="training-authority-") as raw:
            workspace = Version2BookTrainingWorkspace(
                reader,
                progress_root=Path(raw),
                language=UILanguage.EN,
            )
            retained_bridge = workspace.start_current()
            retained_session = workspace.session
            before = workspace.session.snapshot()
            store = workspace._store
            self.assertIsNotNone(store)
            assert store is not None

            with patch.object(store, "save", side_effect=RuntimeError("durable write failed")):
                with self.assertRaisesRegex(RuntimeError, "durable write failed"):
                    workspace.dispatch("training.submit", {"answer": "e4"})

            self.assertIs(retained_session, workspace.session)
            self.assertIs(retained_bridge, workspace.bridge)
            self.assertEqual(before, workspace.session.snapshot())
            self.assertEqual("", workspace.presenter_message)
            self.assertIsNone(workspace.presenter_message_key)

    def test_workspace_rejects_command_subclass_before_strip_hook(self) -> None:
        class HostileCommand(str):
            touched = False

            def strip(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("command subclass strip must never execute")

        document = BookDocument(
            title="Training hostile command",
            blocks=[
                Exercise(
                    fen=Board.START,
                    prompt="Play e4",
                    answer_text="e4",
                    block_id="exercise-one",
                )
            ],
        )
        reader = BookReader(document)
        with tempfile.TemporaryDirectory(prefix="training-hostile-command-") as raw:
            workspace = Version2BookTrainingWorkspace(
                reader,
                progress_root=Path(raw),
                language=UILanguage.EN,
            )
            retained_bridge = workspace.start_current()
            retained_session = workspace.session
            before = workspace.session.snapshot()

            event = workspace.dispatch(HostileCommand("training.hint"), {})

            self.assertEqual("error", event.kind)
            self.assertFalse(HostileCommand.touched)
            self.assertIs(retained_session, workspace.session)
            self.assertIs(retained_bridge, workspace.bridge)
            self.assertEqual(before, workspace.session.snapshot())

    def test_workspace_generic_error_does_not_replace_live_training_objects(self) -> None:
        document = BookDocument(
            title="Training rejected command",
            blocks=[
                Exercise(
                    fen=Board.START,
                    prompt="Play e4",
                    answer_text="e4",
                    block_id="exercise-one",
                )
            ],
        )
        reader = BookReader(document)
        with tempfile.TemporaryDirectory(prefix="training-rejected-") as raw:
            workspace = Version2BookTrainingWorkspace(
                reader,
                progress_root=Path(raw),
                language=UILanguage.EN,
            )
            retained_bridge = workspace.start_current()
            retained_session = workspace.session
            before = workspace.session.snapshot()

            event = workspace.dispatch("training.submit", {"unexpected": "field"})

            self.assertEqual("error", event.kind)
            self.assertIs(retained_session, workspace.session)
            self.assertIs(retained_bridge, workspace.bridge)
            self.assertEqual(before, workspace.session.snapshot())

    def test_application_book_and_training_command_subclasses_fail_before_hooks(self) -> None:
        class HostileCommand(str):
            touched = False

            def strip(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("application must not strip command subclasses")

            def __eq__(self, _other):
                type(self).touched = True
                raise AssertionError("application must not compare command subclasses")

            def __hash__(self):
                type(self).touched = True
                raise AssertionError("application must not hash command subclasses")

        with tempfile.TemporaryDirectory(prefix="training-app-command-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            app = Version2Application(
                database,
                progress_store=BookProgressStore(root / "book-progress.json"),
                engine_assistance=EngineAssistedWorkflowService(analysis),
                board_dispatch=lambda *_args: None,
            )
            source = root / "training.md"
            source.write_text("# Training\n", encoding="utf-8")
            document = BookDocument(
                title="Training",
                blocks=[
                    Exercise(
                        fen=Board.START,
                        prompt="Play e4",
                        answer_text="e4",
                        block_id="exercise-one",
                    )
                ],
            )
            imported = SimpleNamespace(
                book_key="training-command-book",
                document=document,
                warnings=(),
            )
            with patch("acs.version2_application.import_text_book", return_value=imported):
                app.open_book(source)

            book_reader_before = app.reader
            book_snapshot_before = app.reader.snapshot()
            book_result = app.browser_command("books", HostileCommand("book.next"), {})
            self.assertEqual("error", book_result["kind"])
            self.assertFalse(HostileCommand.touched)
            self.assertIs(book_reader_before, app.reader)
            self.assertEqual(book_snapshot_before, app.reader.snapshot())

            routed = app.browser_command("shell", "screen.training")
            self.assertEqual("route", routed["kind"])
            retained_workspace = app.training_workspace
            retained_bridge = app.training
            retained_session = retained_workspace.session
            training_before = retained_session.snapshot()

            training_result = app.browser_command(
                "training",
                HostileCommand("training.hint"),
                {},
            )
            self.assertEqual("error", training_result["kind"])
            self.assertFalse(HostileCommand.touched)
            self.assertIs(retained_workspace, app.training_workspace)
            self.assertIs(retained_bridge, app.training)
            self.assertIs(retained_session, app.training_workspace.session)
            self.assertEqual(training_before, app.training_workspace.session.snapshot())

            # Close native resources before TemporaryDirectory cleanup on
            # Windows, where open SQLite handles can otherwise mask the real
            # regression result with a filesystem cleanup failure.
            analysis.close()
            database.close()

    def test_browser_payload_dict_subclasses_fail_before_hooks(self) -> None:
        class HostileDict(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("payload len must never execute")

            def items(self):
                type(self).touched = True
                raise AssertionError("payload items must never execute")

        book_presenter = BookReaderPresenter(
            BookReader(BookDocument(title="Book", blocks=[Heading(text="Heading", level=1)])),
            language=UILanguage.EN,
        )
        book = BookWebViewBridge(
            BookWebViewProjection(
                book_presenter,
                lambda _action, _payload: None,
                language=UILanguage.EN,
            )
        )
        training_presenter = TrainingPresenter(
            ExerciseSession(self.definition()),
            language=UILanguage.EN,
        )
        training = TrainingWebViewBridge(
            TrainingWebViewProjection(training_presenter, language=UILanguage.EN)
        )

        self.assertEqual("error", book.dispatch("book.next", HostileDict()).kind)
        self.assertFalse(HostileDict.touched)
        self.assertEqual("error", training.dispatch("training.hint", HostileDict()).kind)
        self.assertFalse(HostileDict.touched)


if __name__ == "__main__":
    unittest.main()
