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
from acs.training_progress_store import TrainingProgressDurabilityUnknownError
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
        self.assertEqual(("tactic", "opening"), session.definition.tags)
        self.assertEqual({"origin": "book"}, session.definition.metadata)
        self.assertTrue(session.submit("e4").completed)

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

        with self.assertRaisesRegex(ValueError, "authority was replaced"):
            session.current_step()
        with self.assertRaisesRegex(ValueError, "authority was replaced"):
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

        with self.assertRaisesRegex(ValueError, "metadata changed during session"):
            session.snapshot()
        self.assertFalse(HostileDict.touched)

    def test_canonical_definition_is_detached_from_live_authority(self) -> None:
        session = ExerciseSession(self.definition())
        detached = session.canonical_definition
        self.assertIsNot(detached, session.definition)
        self.assertIsNot(detached.steps[0], session.definition.steps[0])

        object.__setattr__(detached.steps[0], "accepted_moves", frozenset({"d4"}))

        self.assertEqual(frozenset({"e4"}), session.current_step().accepted_moves)
        self.assertTrue(session.submit("e4").accepted)

    def test_session_restore_state_is_atomic_on_bounded_mapping_failure(self) -> None:
        class InfiniteKeys(UserDict):
            yielded = 0

            def __len__(self):
                raise AssertionError("restore_state must not trust Mapping.__len__")

            def __iter__(self):
                type(self).yielded = 0
                while True:
                    type(self).yielded += 1
                    yield f"field_{type(self).yielded}"

        session = ExerciseSession(self.definition())
        session.submit("e4")
        before = session.snapshot()
        authority = session.definition

        with self.assertRaisesRegex(ValueError, "field count"):
            session.restore_state(InfiniteKeys(before))

        self.assertEqual(11, InfiniteKeys.yielded)
        self.assertIs(authority, session.definition)
        self.assertEqual(before, session.snapshot())

    def test_session_restore_state_valid_commit_preserves_authority_identity(self) -> None:
        session = ExerciseSession(self.definition())
        authority = session.definition
        baseline = session.snapshot()
        session.submit("e4")
        self.assertNotEqual(baseline, session.snapshot())

        session.restore_state(baseline)

        self.assertIs(authority, session.definition)
        self.assertEqual(baseline, session.snapshot())

    def test_snapshot_non_text_key_fails_deterministically(self) -> None:
        session = ExerciseSession(self.definition())
        snapshot = session.snapshot()
        snapshot[7] = snapshot.pop("status")  # type: ignore[index]

        with self.assertRaisesRegex(TypeError, "field names must be strings"):
            ExerciseSession.restore(self.definition(), snapshot)

    def test_presenter_restore_state_is_atomic_and_preserves_session_identity(self) -> None:
        presenter = TrainingPresenter(ExerciseSession(self.definition()), language=UILanguage.EN)
        retained = presenter.session
        presenter.session.submit("e4")
        before = presenter.snapshot()
        invalid = dict(before)
        invalid["status"] = "ready"

        with self.assertRaises(ValueError):
            presenter.restore_state(invalid, message="", message_key=None)

        self.assertIs(retained, presenter.session)
        self.assertEqual(before, presenter.snapshot())

        baseline_presenter = TrainingPresenter(
            ExerciseSession(self.definition()),
            language=UILanguage.EN,
        )
        baseline = baseline_presenter.snapshot()
        presenter.restore_state(baseline, message="", message_key=None)
        self.assertIs(retained, presenter.session)
        self.assertIsNotNone(presenter.session.current_step())
        self.assertEqual(baseline, presenter.snapshot())

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

    def test_workspace_post_publication_failure_reconciles_canonical_progress_in_place(self) -> None:
        document = BookDocument(
            title="Training durability reconcile",
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
        with tempfile.TemporaryDirectory(prefix="training-durability-reconcile-") as raw:
            workspace = Version2BookTrainingWorkspace(
                reader,
                progress_root=Path(raw),
                language=UILanguage.EN,
            )
            retained_bridge = workspace.start_current()
            retained_session = workspace.session
            store = workspace._store
            self.assertIsNotNone(store)
            assert store is not None

            with patch(
                "acs.training_progress_store._sync_published_path",
                side_effect=OSError("injected post-publication durability failure"),
            ):
                with self.assertRaises(TrainingProgressDurabilityUnknownError) as raised:
                    workspace.dispatch("training.submit", {"answer": "e4"})

            loaded = store.load(workspace.material.definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertIs(retained_session, workspace.session)
            self.assertIs(retained_bridge, workspace.bridge)
            self.assertTrue(workspace.session.completed)
            self.assertEqual(loaded.session.snapshot(), workspace.session.snapshot())
            self.assertEqual(loaded.revision, workspace._revision)
            self.assertEqual(loaded.revision, raised.exception.published_revision)
            self.assertIsInstance(raised.exception.__cause__, OSError)
            self.assertEqual("", workspace.presenter_message)
            self.assertIsNone(workspace.presenter_message_key)

    def test_workspace_direct_save_reconciles_post_publication_failure(self) -> None:
        document = BookDocument(
            title="Training direct-save durability",
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
        with tempfile.TemporaryDirectory(prefix="training-direct-save-") as raw:
            workspace = Version2BookTrainingWorkspace(
                reader,
                progress_root=Path(raw),
                language=UILanguage.EN,
            )
            retained_bridge = workspace.start_current()
            retained_session = workspace.session
            store = workspace._store
            self.assertIsNotNone(store)
            assert store is not None
            workspace.session.submit("e4")

            with patch(
                "acs.training_progress_store._sync_published_path",
                side_effect=OSError("injected direct-save durability failure"),
            ):
                with self.assertRaises(TrainingProgressDurabilityUnknownError):
                    workspace.save()

            loaded = store.load(workspace.material.definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertIs(retained_session, workspace.session)
            self.assertIs(retained_bridge, workspace.bridge)
            self.assertEqual(loaded.session.snapshot(), workspace.session.snapshot())
            self.assertEqual(loaded.revision, workspace._revision)
            self.assertTrue(workspace.session.completed)

    def test_workspace_unreadable_post_publication_state_is_not_rolled_back(self) -> None:
        document = BookDocument(
            title="Training durability unreadable",
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
        with tempfile.TemporaryDirectory(prefix="training-durability-unreadable-") as raw:
            workspace = Version2BookTrainingWorkspace(
                reader,
                progress_root=Path(raw),
                language=UILanguage.EN,
            )
            retained_bridge = workspace.start_current()
            retained_session = workspace.session
            store = workspace._store
            self.assertIsNotNone(store)
            assert store is not None
            published_revision = "a" * 64
            ambiguity = TrainingProgressDurabilityUnknownError(
                "published state requires reconciliation",
                published_revision=published_revision,
            )

            with (
                patch.object(store, "save", side_effect=ambiguity),
                patch.object(store, "load", side_effect=ValueError("canonical state unavailable")),
            ):
                with self.assertRaises(TrainingProgressDurabilityUnknownError) as raised:
                    workspace.dispatch("training.submit", {"answer": "e4"})

            self.assertIsInstance(raised.exception.__cause__, ValueError)
            self.assertIn("canonical state unavailable", str(raised.exception.__cause__))
            self.assertEqual(published_revision, raised.exception.published_revision)
            self.assertIs(retained_session, workspace.session)
            self.assertIs(retained_bridge, workspace.bridge)
            self.assertTrue(workspace.session.completed)
            self.assertEqual(("e4",), workspace.session.accepted_path)
            self.assertEqual(published_revision, workspace._revision)

    def test_workspace_rejects_command_subclass_before_strip_hook(self) -> None:
        class HostileCommand(str):
            touched = False

            def strip(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("command subclass strip must never execute")

            def __eq__(self, _other):
                type(self).touched = True
                raise AssertionError("command subclass equality must never execute")

            def __hash__(self):
                type(self).touched = True
                raise AssertionError("command subclass hash must never execute")

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

    def test_workspace_overlong_command_is_rejected_without_state_or_identity_drift(self) -> None:
        document = BookDocument(
            title="Training overlong command",
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
        with tempfile.TemporaryDirectory(prefix="training-overlong-command-") as raw:
            workspace = Version2BookTrainingWorkspace(
                reader,
                progress_root=Path(raw),
                language=UILanguage.EN,
            )
            retained_bridge = workspace.start_current()
            retained_session = workspace.session
            before = workspace.session.snapshot()

            event = workspace.dispatch("training." + ("x" * 80), {})

            self.assertEqual("error", event.kind)
            self.assertIs(retained_session, workspace.session)
            self.assertIs(retained_bridge, workspace.bridge)
            self.assertEqual(before, workspace.session.snapshot())
            self.assertEqual((), tuple(Path(raw).glob("*.json")))

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

        class HostileArea(str):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("application must not size area subclasses")

            def __eq__(self, _other):
                type(self).touched = True
                raise AssertionError("application must not compare area subclasses")

            def __hash__(self):
                type(self).touched = True
                raise AssertionError("application must not hash area subclasses")

        class HostilePayload(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("application must not size payload subclasses")

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

            area_result = app.browser_command(HostileArea("books"), "book.next", {})
            self.assertEqual("error", area_result["kind"])
            self.assertFalse(HostileArea.touched)
            self.assertIs(book_reader_before, app.reader)
            self.assertEqual(book_snapshot_before, app.reader.snapshot())

            shell_payload_result = app.browser_command(
                "shell",
                "screen.library",
                HostilePayload(),
            )
            self.assertEqual("error", shell_payload_result["kind"])
            self.assertFalse(HostilePayload.touched)
            self.assertIs(book_reader_before, app.reader)
            self.assertEqual(book_snapshot_before, app.reader.snapshot())

            review_result = app.browser_command(
                "review",
                HostileCommand("pgn.return"),
                {},
            )
            self.assertEqual("error", review_result["kind"])
            self.assertFalse(HostileCommand.touched)
            self.assertIs(book_reader_before, app.reader)
            self.assertEqual(book_snapshot_before, app.reader.snapshot())

            overlong_shell = app.browser_command(
                "shell",
                "screen." + ("x" * 80),
                {},
            )
            self.assertEqual("error", overlong_shell["kind"])
            self.assertIs(book_reader_before, app.reader)
            self.assertEqual(book_snapshot_before, app.reader.snapshot())

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
