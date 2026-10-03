from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.book_training import build_book_training_material
from acs.bookdocument import BookDocument, Exercise, Heading, Paragraph
from acs.bookreader import BookReader
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.full_product_ui_shell import UILanguage
from acs.starter_books_training_content import STARTER_COURSE_BOOK_KEY
from acs.starter_books_training_release import (
    STARTER_BOOKLET_CHAPTERS,
    STARTER_BOOKLET_COUNT,
    STARTER_RELEASE_LICENSE_ID,
    STARTER_RELEASE_LICENSE_TERMS_UK,
    build_release_booklets,
    build_training_task_catalogue,
    starter_release_manifest,
)
from acs.starter_books_training_runtime import build_training_ready_starter_course
from acs.training_progress_store import TrainingProgressConflictError
from acs.version2_starter_content_application import Version2StarterContentApplication
from acs.version2_training_workspace import Version2BookTrainingWorkspace


EXPECTED_BOOKLETS = 24
EXPECTED_TRAINING_EXERCISES = 144
MIN_UNIQUE_TRAINING_FENS = 64


class StarterBooksTrainingReleaseTests(unittest.TestCase):
    def test_release_manifest_meets_p0f_volume_license_and_substance_gate(self) -> None:
        manifest = starter_release_manifest()
        self.assertEqual(1, manifest["schema_version"])
        self.assertEqual("uk", manifest["language"])
        self.assertEqual(STARTER_RELEASE_LICENSE_ID, manifest["license"]["id"])
        self.assertTrue(STARTER_RELEASE_LICENSE_TERMS_UK.strip())
        self.assertEqual(EXPECTED_BOOKLETS, manifest["material_count"])
        self.assertGreaterEqual(manifest["material_count"], 24)
        self.assertEqual(EXPECTED_TRAINING_EXERCISES, manifest["training_exercise_count"])
        self.assertGreaterEqual(manifest["training_exercise_count"], 100)
        self.assertGreaterEqual(manifest["training_unique_fen_count"], MIN_UNIQUE_TRAINING_FENS)

        materials = manifest["materials"]
        self.assertEqual(EXPECTED_BOOKLETS, len(materials))
        self.assertEqual(EXPECTED_BOOKLETS, len({item["material_id"] for item in materials}))
        self.assertEqual(EXPECTED_BOOKLETS, len({item["title"] for item in materials}))
        for item in materials:
            self.assertEqual(STARTER_BOOKLET_CHAPTERS, item["chapter_count"])
            self.assertGreaterEqual(item["word_count"], 1000)
            self.assertEqual(STARTER_RELEASE_LICENSE_ID, item["license_id"])
            self.assertTrue(item["source"].strip())

    def test_release_booklets_are_substantial_canonical_bookdocuments(self) -> None:
        booklets = build_release_booklets()
        self.assertEqual(STARTER_BOOKLET_COUNT, len(booklets))
        self.assertEqual(STARTER_BOOKLET_COUNT, len({book.title for book in booklets}))
        for book in booklets:
            self.assertEqual("uk", book.language)
            self.assertIn(STARTER_RELEASE_LICENSE_ID, book.source_rights)
            self.assertEqual([], book.validate_structure())
            headings = [block for block in book.blocks if isinstance(block, Heading)]
            paragraphs = [block for block in book.blocks if isinstance(block, Paragraph)]
            exercises = [block for block in book.blocks if isinstance(block, Exercise)]
            self.assertEqual(1 + STARTER_BOOKLET_CHAPTERS, len(headings))
            self.assertGreaterEqual(len(paragraphs), STARTER_BOOKLET_CHAPTERS * 8)
            self.assertEqual([], exercises)
            self.assertGreaterEqual(
                sum(len(block.text.split()) for block in headings + paragraphs),
                1000,
            )

    def test_training_catalogue_is_position_specific_legal_and_varied(self) -> None:
        tasks = build_training_task_catalogue()
        self.assertEqual(EXPECTED_TRAINING_EXERCISES, len(tasks))
        self.assertEqual(len(tasks), len({task.task_id for task in tasks}))
        self.assertGreaterEqual(len({task.opening for task in tasks}), 16)
        self.assertGreaterEqual(len({task.fen for task in tasks}), MIN_UNIQUE_TRAINING_FENS)
        self.assertEqual({"w", "b"}, {task.fen.split()[1] for task in tasks})

        course = build_training_ready_starter_course()
        self.assertEqual("uk", course.language)
        self.assertIn(STARTER_RELEASE_LICENSE_ID, course.source_rights)
        self.assertEqual([], course.validate_structure())
        exercises = [block for block in course.blocks if isinstance(block, Exercise)]
        self.assertEqual(EXPECTED_TRAINING_EXERCISES, len(exercises))
        self.assertGreaterEqual(
            len({exercise.fen for exercise in exercises}),
            MIN_UNIQUE_TRAINING_FENS,
        )

        exercise_indexes = [
            index for index, block in enumerate(course.blocks) if isinstance(block, Exercise)
        ]
        for index in exercise_indexes:
            material = build_book_training_material(course, index)
            self.assertEqual(1, len(material.definition.steps))
            self.assertTrue(material.definition.steps[0].accepted_moves)

    def test_release_inventory_text_is_derived_from_current_catalogue(self) -> None:
        manifest = starter_release_manifest()
        course = build_training_ready_starter_course()
        introduction = course.blocks[1]
        self.assertIsInstance(introduction, Paragraph)
        self.assertIn(str(manifest["material_count"]), introduction.text)
        self.assertIn(str(manifest["training_exercise_count"]), introduction.text)
        self.assertNotIn("120 вправ", introduction.text)

    def test_final_product_application_preloads_books_and_starts_real_training(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-release-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    self.assertEqual(STARTER_COURSE_BOOK_KEY, app.book_key)
                    self.assertIsNotNone(app.reader)
                    self.assertIsNotNone(app.books)
                    self.assertEqual("Heading", app.reader.location().kind)
                    self.assertEqual(
                        EXPECTED_TRAINING_EXERCISES,
                        len(app.reader.document.exercises()),
                    )

                    catalogue = app.snapshot()["books"]["starter_materials"]
                    self.assertEqual(EXPECTED_BOOKLETS, catalogue["booklet_count"])
                    self.assertEqual(EXPECTED_BOOKLETS + 1, len(catalogue["items"]))
                    self.assertEqual("starter-course", catalogue["current_id"])
                    self.assertEqual(
                        EXPECTED_BOOKLETS,
                        len(
                            [
                                item
                                for item in catalogue["items"]
                                if item["material_id"].startswith("starter-booklet-")
                            ]
                        ),
                    )

                    self.assertTrue(app._start_training_from_current_book())
                    self.assertEqual("Exercise", app.reader.location().kind)
                    self.assertIsNotNone(app.training_workspace)
                    self.assertIsNotNone(app.training)
                    snapshot = app.training_workspace.snapshot()
                    self.assertIsNotNone(snapshot)
                    self.assertTrue(snapshot["title"].strip())
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()

    def test_training_start_revalidates_after_durable_prepare(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-training-start-revision-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    exercise_index = next(
                        index
                        for index, block in enumerate(app.reader.document.blocks)
                        if isinstance(block, Exercise)
                    )
                    app.reader.go_to(exercise_index)
                    workspace = Version2BookTrainingWorkspace(
                        app.reader,
                        progress_root=root / "training-start-progress",
                    )
                    original_prepare = Version2BookTrainingWorkspace._prepare
                    drift = {}

                    def mutate_after_prepare(
                        self,
                        material,
                        *,
                        message="",
                        message_key=None,
                    ):
                        prepared = original_prepare(
                            self,
                            material,
                            message=message,
                            message_key=message_key,
                        )
                        block = self.reader.document.blocks[self.reader.index]
                        if not isinstance(block, Exercise):
                            raise AssertionError("Training start did not target an Exercise")
                        drift["index"] = self.reader.index
                        drift["prompt"] = block.prompt
                        block.prompt = block.prompt + " [prepare drift]"
                        return prepared

                    with patch.object(
                        Version2BookTrainingWorkspace,
                        "_prepare",
                        mutate_after_prepare,
                    ):
                        with self.assertRaisesRegex(
                            RuntimeError,
                            "changed after BookReader creation",
                        ):
                            workspace.start_current()

                    self.assertTrue(drift)
                    app.reader.document.blocks[drift["index"]].prompt = drift["prompt"]
                    self.assertEqual(exercise_index, app.reader.location().index)
                    self.assertIsNone(workspace.material)
                    self.assertIsNone(workspace.bridge)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_training_presentation_only_commands_do_not_depend_on_progress_writes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-training-presentation-only-") as raw:
            root = Path(raw)
            document = BookDocument(
                title="Presentation-only Training",
                language="en",
                blocks=[
                    Exercise(
                        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                        prompt="Exercise",
                        answer_text="e4",
                        block_id="exercise",
                    )
                ],
            )
            workspace = Version2BookTrainingWorkspace(
                BookReader(document),
                progress_root=root / "training-progress",
                language=UILanguage.UA,
            )
            workspace.start_current()
            before = workspace.session.snapshot()
            store = workspace._store
            self.assertIsNotNone(store)

            with patch.object(
                store,
                "save",
                side_effect=AssertionError(
                    "presentation-only Training command must not write progress"
                ),
            ) as save:
                language = workspace.dispatch(
                    " training.language ",
                    {"language": "en"},
                )
                revealed = workspace.dispatch(" training.reveal ", {})
                retried = workspace.dispatch(" training.retry ", {})

            save.assert_not_called()
            self.assertEqual("render", language.kind)
            self.assertEqual("en", language.payload["snapshot"]["document"]["lang"])
            self.assertEqual(UILanguage.EN, workspace.language)
            self.assertEqual("render", revealed.kind)
            self.assertEqual(("e4",), revealed.payload["solution"])
            self.assertEqual("render", retried.kind)
            self.assertEqual(before, workspace.session.snapshot())

            with patch.object(
                store,
                "save",
                side_effect=AssertionError(
                    "no-op Book Training hint must not write progress"
                ),
            ) as save:
                hinted = workspace.dispatch(" training.hint ", {})

            self.assertEqual("render", hinted.kind)
            self.assertEqual(0, workspace.session.hints_used)
            self.assertEqual(before, workspace.session.snapshot())
            save.assert_not_called()

            with patch.object(
                store,
                "save",
                wraps=store.save,
            ) as save:
                wrong = workspace.dispatch(" training.submit ", {"answer": "d4"})

            self.assertEqual("render", wrong.kind)
            self.assertEqual(1, workspace.session.attempts)
            self.assertEqual(1, workspace.session.mistakes)
            save.assert_called_once()

    def test_whitespace_command_cannot_bypass_completed_training_action_fence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-training-command-fence-") as raw:
            root = Path(raw)
            document = BookDocument(
                title="Training command fence",
                language="en",
                blocks=[
                    Exercise(
                        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                        prompt="Exercise",
                        answer_text="e4",
                        block_id="exercise",
                    )
                ],
            )
            workspace = Version2BookTrainingWorkspace(
                BookReader(document),
                progress_root=root / "training-progress",
            )
            workspace.start_current()
            completed = workspace.dispatch("training.submit", {"answer": "e4"})
            self.assertEqual("render", completed.kind)
            self.assertTrue(workspace.session.completed)
            before = workspace.session.snapshot()
            before_message = workspace.presenter_message
            store = workspace._store
            self.assertIsNotNone(store)

            with patch.object(
                store,
                "save",
                side_effect=AssertionError(
                    "disabled stale Training command must not reach persistence"
                ),
            ) as save:
                rejected_hint = workspace.dispatch(" training.hint ", {})
                rejected_reveal = workspace.dispatch(" training.reveal ", {})
                rejected_retry = workspace.dispatch(" training.retry ", {})

            save.assert_not_called()
            self.assertEqual("error", rejected_hint.kind)
            self.assertEqual("error", rejected_reveal.kind)
            self.assertEqual("error", rejected_retry.kind)
            self.assertEqual(before, workspace.session.snapshot())
            self.assertEqual(before_message, workspace.presenter_message)

    def test_training_save_skips_only_a_proven_identical_durable_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-training-durable-snapshot-") as raw:
            root = Path(raw)
            document = BookDocument(
                title="Durable snapshot",
                language="en",
                blocks=[
                    Exercise(
                        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                        prompt="Exercise",
                        answer_text="e4",
                        block_id="exercise",
                    )
                ],
            )
            workspace = Version2BookTrainingWorkspace(
                BookReader(document),
                progress_root=root / "training-progress",
            )
            workspace.start_current()
            store = workspace._store
            self.assertIsNotNone(store)
            self.assertIsNone(workspace._revision)

            with patch.object(store, "save", wraps=store.save) as save:
                first_revision = workspace.save()
            save.assert_called_once()
            self.assertIsNotNone(first_revision)
            durable = store.path.read_bytes()

            with patch(
                "acs.training_progress_store.tempfile.mkstemp",
                side_effect=AssertionError(
                    "identical durable snapshot must not allocate a publication temp"
                ),
            ) as mkstemp:
                second_revision = workspace.save()
            mkstemp.assert_not_called()
            self.assertEqual(first_revision, second_revision)
            self.assertEqual(durable, store.path.read_bytes())

            # Cached in-memory equality is not durability evidence. External
            # replacement or deletion must still be detected by the no-op path.
            store.path.write_bytes(durable + b" ")
            with self.assertRaises(TrainingProgressConflictError):
                workspace.save()
            self.assertEqual(durable + b" ", store.path.read_bytes())

            store.path.write_bytes(durable)
            store.path.unlink()
            with self.assertRaises(TrainingProgressConflictError):
                workspace.save()
            self.assertFalse(store.path.exists())
            store.path.write_bytes(durable)

            workspace.session.submit("d4")
            with patch.object(store, "save", wraps=store.save) as save:
                changed_revision = workspace.save()
            save.assert_called_once()
            self.assertNotEqual(first_revision, changed_revision)

    def test_training_continue_does_not_rewrite_already_committed_origin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-training-continue-no-rewrite-") as raw:
            root = Path(raw)
            document = BookDocument(
                title="Continue without rewrite",
                language="en",
                blocks=[
                    Exercise(
                        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                        prompt="First",
                        answer_text="e4",
                        block_id="first",
                    ),
                    Exercise(
                        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                        prompt="Second",
                        answer_text="d4",
                        block_id="second",
                    ),
                ],
            )
            workspace = Version2BookTrainingWorkspace(
                BookReader(document),
                progress_root=root / "training-progress",
            )
            workspace.start_current()
            completed = workspace.dispatch("training.submit", {"answer": "e4"})
            self.assertEqual("render", completed.kind)
            self.assertTrue(workspace.session.completed)
            origin_store = workspace._store
            self.assertIsNotNone(origin_store)
            durable_before = origin_store.path.read_bytes()
            origin_revision = workspace._revision

            with patch(
                "acs.training_progress_store.tempfile.mkstemp",
                side_effect=AssertionError(
                    "already committed completed origin must not allocate a rewrite temp"
                ),
            ) as mkstemp:
                continued = workspace.continue_next()

            mkstemp.assert_not_called()
            self.assertEqual("render", continued.kind)
            self.assertEqual(1, workspace.reader.index)
            self.assertFalse(workspace.session.completed)
            self.assertEqual(durable_before, origin_store.path.read_bytes())
            self.assertEqual(origin_revision, hashlib.sha256(durable_before).hexdigest())

    def test_workspace_continue_render_error_restores_exact_local_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-workspace-continue-atomic-") as raw:
            root = Path(raw)
            document = BookDocument(
                title="Workspace Continue atomicity",
                language="en",
                blocks=[
                    Exercise(
                        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                        prompt="First",
                        answer_text="e4",
                        block_id="first",
                    ),
                    Exercise(
                        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                        prompt="Second",
                        answer_text="d4",
                        block_id="second",
                    ),
                ],
            )
            workspace = Version2BookTrainingWorkspace(
                BookReader(document),
                progress_root=root / "training-progress",
            )
            workspace.start_current()
            current = workspace.material.definition.steps[0]
            completed = workspace.dispatch(
                "training.submit",
                {"answer": next(iter(current.accepted_moves))},
            )
            self.assertEqual("render", completed.kind)
            self.assertTrue(workspace.session.completed)

            before_index = workspace.reader.index
            before_material = workspace.material
            before_session = workspace._session
            before_bridge = workspace.bridge
            before_store = workspace._store
            before_revision = workspace._revision
            before_snapshot = workspace.snapshot()
            progress_path = before_store.path
            durable_before = progress_path.read_bytes()

            with patch(
                "acs.training_webview_projection.TrainingWebViewProjection.retry",
                side_effect=RuntimeError("simulated next Training render failure"),
            ):
                rejected = workspace.dispatch("training.continue", {})

            self.assertEqual("error", rejected.kind)
            self.assertEqual(before_index, workspace.reader.index)
            self.assertIs(before_material, workspace.material)
            self.assertIs(before_session, workspace._session)
            self.assertIs(before_bridge, workspace.bridge)
            self.assertIs(before_store, workspace._store)
            self.assertEqual(before_revision, workspace._revision)
            self.assertEqual(before_snapshot, workspace.snapshot())
            self.assertEqual(durable_before, progress_path.read_bytes())


    def test_training_start_normalizes_mid_derivation_malformed_revision(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-training-start-mid-drift-") as raw:
            root = Path(raw)
            document = BookDocument(
                title="Start mid-derivation drift",
                language="en",
                blocks=[
                    Exercise(
                        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                        prompt="Exercise",
                        answer_text="e4",
                        block_id="exercise",
                    )
                ],
            )
            workspace = Version2BookTrainingWorkspace(
                BookReader(document),
                progress_root=root / "training-progress",
            )

            def fail_after_live_mutation(_reader):
                document.blocks.append(object())
                raise AttributeError("internal mutable-document failure")

            with patch(
                "acs.version2_training_workspace.build_current_book_training_material",
                side_effect=fail_after_live_mutation,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "changed after BookReader creation",
                ):
                    workspace.start_current()

            self.assertIsNone(workspace.material)
            self.assertIsNone(workspace.bridge)
            self.assertIsNone(workspace._session)


    def test_training_successor_probe_normalizes_mid_provenance_malformed_revision(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-training-successor-mid-drift-") as raw:
            root = Path(raw)
            document = BookDocument(
                title="Successor mid-provenance drift",
                language="en",
                blocks=[
                    Exercise(
                        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                        prompt="First",
                        answer_text="e4",
                        block_id="first",
                    ),
                    Exercise(
                        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                        prompt="Second",
                        answer_text="d4",
                        block_id="second",
                    ),
                ],
            )
            workspace = Version2BookTrainingWorkspace(
                BookReader(document),
                progress_root=root / "training-progress",
            )
            workspace.start_current()

            def fail_after_live_mutation(_document, _origin):
                document.blocks.append(object())
                raise AttributeError("internal provenance failure")

            with patch(
                "acs.version2_training_workspace.resolve_book_training_origin",
                side_effect=fail_after_live_mutation,
            ):
                self.assertFalse(workspace.has_next())

            self.assertIsNotNone(workspace.material)
            self.assertIsNotNone(workspace.bridge)


    def test_training_successor_probe_rejects_malformed_live_revision_before_provenance_or_persistence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-training-malformed-revision-") as raw:
            root = Path(raw)
            document = BookDocument(
                title="Malformed live revision",
                language="en",
                blocks=[
                    Exercise(
                        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                        prompt="First",
                        answer_text="e4",
                        block_id="first",
                    ),
                    Exercise(
                        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                        prompt="Second",
                        answer_text="d4",
                        block_id="second",
                    ),
                ],
            )
            workspace = Version2BookTrainingWorkspace(
                BookReader(document),
                progress_root=root / "training-progress",
            )
            workspace.start_current()
            current = workspace.material.definition.steps[0]
            workspace.session.submit(next(iter(current.accepted_moves)))
            self.assertTrue(workspace.session.completed)

            document.blocks.append(object())
            with patch(
                "acs.version2_training_workspace.resolve_book_training_origin",
                side_effect=AssertionError(
                    "malformed live revision must be rejected before provenance resolution"
                ),
            ) as resolve, patch.object(
                workspace._store,
                "save",
                side_effect=AssertionError(
                    "malformed live revision must be rejected before Training persistence"
                ),
            ) as save:
                self.assertFalse(workspace.has_next())
                with self.assertRaisesRegex(
                    RuntimeError,
                    "changed after BookReader creation",
                ):
                    workspace.continue_next()

            resolve.assert_not_called()
            save.assert_not_called()


    def test_training_continue_fails_closed_on_live_book_revision_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-training-revision-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    self.assertTrue(app._start_training_from_current_book())
                    workspace = app.training_workspace
                    self.assertIsNotNone(workspace)
                    answer = next(iter(workspace.material.definition.steps[0].accepted_moves))
                    workspace.session.submit(answer)
                    self.assertTrue(workspace.session.completed)

                    before_index = app.reader.index
                    before_material = workspace.material
                    before_bridge = workspace.bridge
                    drift = {}

                    def mutate_during_material_build(document, target):
                        candidate = build_book_training_material(document, target)
                        if not drift:
                            block = document.blocks[target]
                            self.assertIsInstance(block, Exercise)
                            drift["index"] = target
                            drift["prompt"] = block.prompt
                            block.prompt = block.prompt + " [concurrent drift]"
                        return candidate

                    with patch(
                        "acs.version2_training_workspace.build_book_training_material",
                        side_effect=mutate_during_material_build,
                    ), patch.object(
                        workspace._store,
                        "save",
                        side_effect=AssertionError(
                            "revision-drifted Continue must fail before Training persistence"
                        ),
                    ) as save:
                        with self.assertRaisesRegex(
                            RuntimeError,
                            "changed after BookReader creation",
                        ):
                            workspace.continue_next()

                    save.assert_not_called()
                    self.assertTrue(drift)
                    document = app.reader.document
                    document.blocks[drift["index"]].prompt = drift["prompt"]
                    self.assertEqual(before_index, app.reader.location().index)
                    self.assertIs(before_material, workspace.material)
                    self.assertIs(before_bridge, workspace.bridge)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_all_24_booklets_are_discoverable_openable_and_keep_isolated_progress(self) -> None:
        manifest = starter_release_manifest()
        expected_titles = {
            item["material_id"]: item["title"] for item in manifest["materials"]
        }
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-discovery-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    opened_books = app.browser_command("shell", "screen.books")
                    self.assertEqual("route", opened_books["kind"])
                    self.assertEqual("books", app.shell.current_route.route_id)
                    initial = app.snapshot()["books"]["starter_materials"]
                    booklet_items = [
                        item
                        for item in initial["items"]
                        if item["material_id"].startswith("starter-booklet-")
                    ]
                    self.assertEqual(EXPECTED_BOOKLETS, len(booklet_items))
                    self.assertEqual(
                        set(expected_titles),
                        {item["material_id"] for item in booklet_items},
                    )

                    for item in booklet_items:
                        material_id = item["material_id"]
                        result = app.browser_command(
                            "books",
                            "book.open_starter_material",
                            {"material_id": material_id},
                        )
                        self.assertEqual("render", result["kind"])
                        self.assertEqual(expected_titles[material_id], app.reader.document.title)
                        self.assertEqual(material_id, result["payload"]["snapshot"]["starter_materials"]["current_id"])
                        self.assertEqual("Heading", app.reader.location().kind)
                        self.assertIn(material_id, app.book_key)

                    first_id = booklet_items[0]["material_id"]
                    second_id = booklet_items[1]["material_id"]
                    app.browser_command(
                        "books", "book.open_starter_material", {"material_id": first_id}
                    )
                    moved = app.browser_command("books", "book.next", {})
                    self.assertEqual("render", moved["kind"])
                    remembered_index = app.reader.location().index
                    self.assertGreater(remembered_index, 0)
                    app.browser_command(
                        "books", "book.open_starter_material", {"material_id": second_id}
                    )
                    app.browser_command(
                        "books", "book.open_starter_material", {"material_id": first_id}
                    )
                    self.assertEqual(remembered_index, app.reader.location().index)

                    before_key = app.book_key
                    before_title = app.reader.document.title
                    rejected = app.browser_command(
                        "books",
                        "book.open_starter_material",
                        {"material_id": "starter-booklet-does-not-exist"},
                    )
                    self.assertEqual("error", rejected["kind"])
                    self.assertEqual(before_key, app.book_key)
                    self.assertEqual(before_title, app.reader.document.title)

                    # Training remains a first-class route after reading any
                    # booklet: it returns to the canonical exercise-bearing
                    # starter course, rather than leaving a dead Training page.
                    self.assertTrue(app._start_training_from_current_book())
                    self.assertEqual(STARTER_COURSE_BOOK_KEY, app.book_key)
                    self.assertEqual("Exercise", app.reader.location().kind)
                    self.assertIsNotNone(app.training_workspace)
                    self.assertIsNotNone(app.training)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_hidden_books_surface_cannot_replace_starter_material(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-hidden-books-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    opened_books = app.browser_command("shell", "screen.books")
                    self.assertEqual("route", opened_books["kind"])
                    self.assertEqual("books", app.shell.current_route.route_id)
                    catalogue = app.snapshot()["books"]["starter_materials"]
                    booklet = next(
                        item
                        for item in catalogue["items"]
                        if item["material_id"].startswith("starter-booklet-")
                    )
                    before_key = app.book_key
                    before_title = app.reader.document.title
                    before_reader = app.reader.snapshot()
                    before_material = catalogue["current_id"]

                    routed = app.browser_command("shell", "screen.library")
                    self.assertEqual("route", routed["kind"])
                    self.assertEqual("library", app.shell.current_route.route_id)

                    rejected = app.browser_command(
                        "books",
                        "book.open_starter_material",
                        {"material_id": booklet["material_id"]},
                    )

                    self.assertEqual("error", rejected["kind"])
                    self.assertEqual("library", app.shell.current_route.route_id)
                    self.assertEqual(before_key, app.book_key)
                    self.assertEqual(before_title, app.reader.document.title)
                    self.assertEqual(before_reader, app.reader.snapshot())
                    self.assertEqual(
                        before_material,
                        app.snapshot()["books"]["starter_materials"]["current_id"],
                    )
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_native_training_route_starts_real_workspace_before_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-native-training-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    self.assertIsNone(app.training_workspace)
                    command = app.adapter.activate_action("screen.training")
                    self.assertEqual("route", command.kind)
                    self.assertEqual("training", app.shell.current_route.route_id)

                    self.assertTrue(app.native_command(command))
                    self.assertEqual("training", app.shell.current_route.route_id)
                    self.assertIsNotNone(app.training_workspace)
                    self.assertIsNotNone(app.training)
                    self.assertEqual("Exercise", app.reader.location().kind)
                    events = app.drain_events()
                    self.assertEqual("route", events[-1]["kind"])
                    self.assertEqual("training", events[-1]["payload"]["route_id"])
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()

    def test_training_cannot_retarget_reader_while_book_board_owns_origin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-board-training-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    app.browser_command("shell", "screen.books")
                    moved = app.browser_command("books", "book.next_position")
                    self.assertEqual("render", moved["kind"])
                    opened = app.browser_command("books", "book.open_position")
                    self.assertEqual("delegated", opened["kind"])
                    self.assertTrue(app.book_workflow.active)
                    self.assertEqual("board", app.shell.current_route.route_id)
                    opened_events = app.drain_events()
                    self.assertEqual(
                        ["book-board"],
                        [item["kind"] for item in opened_events],
                    )
                    reader_before = app.reader.snapshot()
                    board_before = app.book_workflow.view()

                    rejected = app.browser_command("shell", "screen.training")
                    self.assertEqual("error", rejected["kind"])
                    self.assertEqual("board", app.shell.current_route.route_id)
                    self.assertEqual(reader_before, app.reader.snapshot())
                    self.assertEqual(board_before, app.book_workflow.view())
                    self.assertIsNone(app.training_workspace)

                    command = app.adapter.activate_action("screen.training")
                    self.assertEqual("training", app.shell.current_route.route_id)
                    self.assertFalse(app.native_command(command))
                    self.assertEqual("board", app.shell.current_route.route_id)
                    self.assertEqual(reader_before, app.reader.snapshot())
                    self.assertEqual(board_before, app.book_workflow.view())
                    self.assertIsNone(app.training_workspace)
                    events = app.drain_events()
                    self.assertEqual(["route", "error"], [item["kind"] for item in events])
                    self.assertEqual("board", events[0]["payload"]["route_id"])
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_modal_dialog_blocks_hidden_starter_and_training_preflight_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-modal-fence-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    opened_books = app.browser_command("shell", "screen.books")
                    self.assertEqual("route", opened_books["kind"])
                    self.assertEqual("books", app.shell.current_route.route_id)
                    catalogue = app.snapshot()["books"]["starter_materials"]
                    booklet = next(
                        item
                        for item in catalogue["items"]
                        if item["material_id"].startswith("starter-booklet-")
                    )
                    before_key = app.book_key
                    before_title = app.reader.document.title
                    before_reader = app.reader.snapshot()
                    before_material = catalogue["current_id"]

                    opened_dialog = app.adapter.open_dialog(
                        "test-modal",
                        opener_focus_id="book-reader",
                        initial_focus_id="test-modal-confirm",
                    )
                    self.assertEqual("dialog-open", opened_dialog.kind)
                    self.assertEqual("test-modal", app.shell.active_dialog_id)

                    rejected_material = app.browser_command(
                        "books",
                        "book.open_starter_material",
                        {"material_id": booklet["material_id"]},
                    )
                    rejected_training = app.browser_command("shell", "screen.training")

                    self.assertEqual("error", rejected_material["kind"])
                    self.assertEqual("error", rejected_training["kind"])
                    self.assertEqual("books", app.shell.current_route.route_id)
                    self.assertEqual("test-modal", app.shell.active_dialog_id)
                    self.assertEqual(before_key, app.book_key)
                    self.assertEqual(before_title, app.reader.document.title)
                    self.assertEqual(before_reader, app.reader.snapshot())
                    self.assertEqual(
                        before_material,
                        app.snapshot()["books"]["starter_materials"]["current_id"],
                    )
                    self.assertIsNone(app.training_workspace)
                    self.assertIsNone(app.training)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_training_auto_seek_save_failure_restores_exact_reader_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-training-save-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    before = app.reader.snapshot()
                    before_key = app.book_key
                    self.assertNotEqual("Exercise", app.reader.location().kind)

                    with patch.object(
                        app.progress_store,
                        "save",
                        side_effect=OSError("simulated progress write failure"),
                    ):
                        browser_result = app.browser_command("shell", "screen.training")

                    self.assertEqual("error", browser_result["kind"])
                    self.assertEqual(before_key, app.book_key)
                    self.assertEqual(before, app.reader.snapshot())
                    self.assertIsNone(app.training_workspace)
                    self.assertIsNone(app.training)

                    command = app.adapter.activate_action("screen.training")
                    self.assertEqual("training", app.shell.current_route.route_id)
                    with patch.object(
                        app.progress_store,
                        "save",
                        side_effect=OSError("simulated progress write failure"),
                    ):
                        self.assertFalse(app.native_command(command))

                    self.assertEqual("books", app.shell.current_route.route_id)
                    self.assertEqual(before_key, app.book_key)
                    self.assertEqual(before, app.reader.snapshot())
                    self.assertIsNone(app.training_workspace)
                    self.assertIsNone(app.training)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_native_book_open_cannot_replace_reader_behind_modal_dialog(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-modal-open-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    replacement = root / "replacement.md"
                    replacement.write_text("# Replacement\n\nHidden replacement body.\n", encoding="utf-8")
                    picker_calls = []
                    app.open_book_dialog = lambda: picker_calls.append(True) or replacement
                    before_key = app.book_key
                    before_title = app.reader.document.title
                    before_reader = app.reader.snapshot()

                    app.adapter.open_dialog(
                        "test-modal-open",
                        opener_focus_id="book-reader",
                        initial_focus_id="test-modal-open-confirm",
                    )
                    result = app.adapter.activate_action("book.open")

                    self.assertEqual("error", result.kind)
                    self.assertEqual([], picker_calls)
                    self.assertEqual("test-modal-open", app.shell.active_dialog_id)
                    self.assertEqual(before_key, app.book_key)
                    self.assertEqual(before_title, app.reader.document.title)
                    self.assertEqual(before_reader, app.reader.snapshot())
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_hidden_training_surface_cannot_mutate_training_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-hidden-training-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    opened = app.browser_command("shell", "screen.training")
                    self.assertEqual("route", opened["kind"])
                    self.assertEqual("training", app.shell.current_route.route_id)
                    self.assertIsNotNone(app.training_workspace)
                    before = app.training_workspace.snapshot()

                    routed = app.browser_command("shell", "screen.library")
                    self.assertEqual("route", routed["kind"])
                    self.assertEqual("library", app.shell.current_route.route_id)

                    with patch.object(
                        app.training_workspace,
                        "dispatch",
                        side_effect=AssertionError(
                            "hidden Training commands must be rejected before workspace dispatch"
                        ),
                    ) as dispatch:
                        browser_result = app.browser_command("training", "training.hint")
                        native_result = app.adapter.activate_action("training.hint")

                    self.assertEqual("error", browser_result["kind"])
                    self.assertEqual("error", native_result.kind)
                    self.assertEqual(
                        app._error()["payload"]["message"],
                        browser_result["payload"]["message"],
                    )
                    self.assertEqual(
                        browser_result["payload"]["message"],
                        native_result.payload["message"],
                    )
                    dispatch.assert_not_called()
                    self.assertEqual(before, app.training_workspace.snapshot())
                    self.assertEqual("library", app.shell.current_route.route_id)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_modal_dialog_blocks_book_board_open_mutation_and_return(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-modal-board-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    app.browser_command("shell", "screen.books")
                    moved = app.browser_command("books", "book.next_position")
                    self.assertEqual("render", moved["kind"])
                    reader_before = app.reader.snapshot()

                    app.adapter.open_dialog(
                        "test-book-open-modal",
                        opener_focus_id="book-reader",
                        initial_focus_id="test-book-open-modal-confirm",
                    )
                    with patch.object(
                        app.book_workflow,
                        "dispatch",
                        side_effect=AssertionError(
                            "modal Book Board open must be rejected before workflow dispatch"
                        ),
                    ) as dispatch:
                        rejected_open = app.browser_command("books", "book.open_position")
                    self.assertEqual("error", rejected_open["kind"])
                    dispatch.assert_not_called()
                    self.assertFalse(app.book_workflow.active)
                    self.assertEqual(reader_before, app.reader.snapshot())
                    app.adapter.close_dialog("test-book-open-modal")

                    opened = app.browser_command("books", "book.open_position")
                    self.assertEqual("delegated", opened["kind"])
                    self.assertTrue(app.book_workflow.active)
                    board_before = app.book_workflow.view()
                    app.adapter.open_dialog(
                        "test-book-return-modal",
                        opener_focus_id="board-launcher",
                        initial_focus_id="test-book-return-modal-confirm",
                    )
                    with patch.object(
                        app.book_workflow,
                        "dispatch",
                        side_effect=AssertionError(
                            "modal Book Board return must be rejected before workflow dispatch"
                        ),
                    ) as dispatch:
                        rejected_return = app.browser_command("review", "book.return")
                    self.assertEqual("error", rejected_return["kind"])
                    dispatch.assert_not_called()
                    self.assertTrue(app.book_workflow.active)
                    self.assertEqual(board_before, app.book_workflow.view())
                    self.assertEqual("board", app.shell.current_route.route_id)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_training_render_errors_restore_session_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-training-render-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    opened = app.browser_command("shell", "screen.training")
                    self.assertEqual("route", opened["kind"])

                    before_submit = app.training_workspace.session.snapshot()
                    revision_before_submit = app.training_workspace._revision
                    with patch(
                        "acs.training_webview_projection.TrainingWebViewProjection._render",
                        side_effect=RuntimeError("simulated submit render failure"),
                    ):
                        rejected_submit = app.browser_command(
                            "training",
                            "training.submit",
                            {"answer": "not-a-legal-move"},
                        )

                    self.assertEqual("error", rejected_submit["kind"])
                    self.assertEqual(before_submit, app.training_workspace.session.snapshot())
                    self.assertEqual(revision_before_submit, app.training_workspace._revision)

                    progressed = app.browser_command(
                        "training",
                        "training.submit",
                        {"answer": "not-a-legal-move"},
                    )
                    self.assertEqual("render", progressed["kind"])
                    before_reset = app.training_workspace.session.snapshot()
                    revision_before_reset = app.training_workspace._revision
                    self.assertEqual(1, before_reset["attempts"])

                    with patch(
                        "acs.training_webview_projection.TrainingWebViewProjection._render",
                        side_effect=RuntimeError("simulated reset render failure"),
                    ):
                        rejected_reset = app.browser_command(
                            "training",
                            "training.reset",
                            {"confirmed": True},
                        )

                    self.assertEqual("error", rejected_reset["kind"])
                    self.assertEqual(before_reset, app.training_workspace.session.snapshot())
                    self.assertEqual(revision_before_reset, app.training_workspace._revision)
                    self.assertEqual("training", app.shell.current_route.route_id)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_training_transient_message_survives_rejected_and_failed_actions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-training-message-rollback-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    opened = app.browser_command("shell", "screen.training")
                    self.assertEqual("route", opened["kind"])

                    seeded = app.browser_command("training", "training.reveal")
                    self.assertEqual("render", seeded["kind"])
                    message_before = app.training_workspace.snapshot()["message"]
                    session_before = app.training_workspace.session.snapshot()
                    revision_before = app.training_workspace._revision
                    self.assertTrue(message_before)

                    rejected = app.browser_command(
                        "training",
                        "training.submit",
                        {"wrong": "field"},
                    )
                    self.assertEqual("error", rejected["kind"])
                    self.assertEqual(message_before, app.training_workspace.snapshot()["message"])
                    self.assertEqual(session_before, app.training_workspace.session.snapshot())
                    self.assertEqual(revision_before, app.training_workspace._revision)

                    with patch(
                        "acs.training_webview_projection.TrainingWebViewProjection._render",
                        side_effect=RuntimeError("simulated retry render failure"),
                    ):
                        retry_failed = app.browser_command("training", "training.retry")
                    self.assertEqual("error", retry_failed["kind"])
                    self.assertEqual(message_before, app.training_workspace.snapshot()["message"])
                    self.assertEqual(session_before, app.training_workspace.session.snapshot())
                    self.assertEqual(revision_before, app.training_workspace._revision)

                    with patch(
                        "acs.training_webview_projection.TrainingWebViewProjection._render",
                        side_effect=RuntimeError("simulated reveal render failure"),
                    ):
                        reveal_failed = app.browser_command("training", "training.reveal")
                    self.assertEqual("error", reveal_failed["kind"])
                    self.assertEqual(message_before, app.training_workspace.snapshot()["message"])
                    self.assertEqual(session_before, app.training_workspace.session.snapshot())
                    self.assertEqual(revision_before, app.training_workspace._revision)

                    with patch.object(
                        app.training_workspace._store,
                        "save",
                        side_effect=AssertionError(
                            "presentation-only retry must not write Training progress"
                        ),
                    ) as save:
                        retried = app.browser_command("training", "training.retry")
                    self.assertEqual("render", retried["kind"])
                    save.assert_not_called()
                    self.assertEqual("", app.training_workspace.snapshot()["message"])
                    self.assertEqual(session_before, app.training_workspace.session.snapshot())
                    self.assertEqual(revision_before, app.training_workspace._revision)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_completed_training_rejects_disabled_actions_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-training-completed-fence-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    opened = app.browser_command("shell", "screen.training")
                    self.assertEqual("route", opened["kind"])
                    current = app.training_workspace.material.definition.steps[0]
                    completed = app.browser_command(
                        "training",
                        "training.submit",
                        {"answer": next(iter(current.accepted_moves))},
                    )
                    self.assertEqual("render", completed["kind"])
                    self.assertTrue(app.training_workspace.session.completed)
                    completed_actions = {
                        item["command"]: item
                        for item in app.training_workspace.snapshot()["actions"]
                    }
                    for command in ("training.hint", "training.reveal", "training.retry"):
                        self.assertFalse(completed_actions[command]["enabled"])

                    session_before = app.training_workspace.session.snapshot()
                    surface_before = app.training_workspace.snapshot()
                    revision_before = app.training_workspace._revision

                    with patch.object(
                        app.training_workspace._store,
                        "save",
                        side_effect=AssertionError(
                            "disabled completed Training actions must not persist"
                        ),
                    ) as save:
                        for command in ("training.hint", "training.reveal", "training.retry"):
                            with self.subTest(browser=command):
                                rejected = app.browser_command("training", command)
                                self.assertEqual("error", rejected["kind"])
                                self.assertEqual(
                                    session_before,
                                    app.training_workspace.session.snapshot(),
                                )
                                self.assertEqual(
                                    surface_before,
                                    app.training_workspace.snapshot(),
                                )
                                self.assertEqual(
                                    revision_before,
                                    app.training_workspace._revision,
                                )

                        for action in (
                            "training.hint",
                            "training.reveal_solution",
                            "training.retry",
                        ):
                            with self.subTest(native=action):
                                rejected = app.adapter.activate_action(action)
                                self.assertEqual("error", rejected.kind)
                                self.assertEqual(
                                    session_before,
                                    app.training_workspace.session.snapshot(),
                                )
                                self.assertEqual(
                                    surface_before,
                                    app.training_workspace.snapshot(),
                                )
                                self.assertEqual(
                                    revision_before,
                                    app.training_workspace._revision,
                                )
                    save.assert_not_called()

                    malformed_before = app.training_workspace.snapshot()
                    malformed = app.training_workspace.dispatch([], None)
                    self.assertEqual("error", malformed.kind)
                    self.assertEqual(
                        malformed_before,
                        app.training_workspace.snapshot(),
                    )
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_disabled_continue_without_successor_rejects_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-training-no-successor-") as raw:
            root = Path(raw)
            document = BookDocument(
                title="Single exercise",
                language="uk",
                blocks=[
                    Exercise(
                        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                        prompt="Знайдіть хід.",
                        answer_text="e4",
                        block_id="single-exercise",
                    )
                ],
            )
            workspace = Version2BookTrainingWorkspace(
                BookReader(document),
                progress_root=root / "training-progress",
            )
            workspace.start_current()
            current = workspace.material.definition.steps[0]
            completed = workspace.dispatch(
                "training.submit",
                {"answer": next(iter(current.accepted_moves))},
            )
            self.assertEqual("render", completed.kind)
            self.assertTrue(workspace.session.completed)
            actions = {
                item["command"]: item
                for item in workspace.snapshot()["actions"]
            }
            self.assertFalse(actions["training.continue"]["enabled"])

            session_before = workspace.session.snapshot()
            surface_before = workspace.snapshot()
            revision_before = workspace._revision
            with patch.object(
                workspace._store,
                "save",
                side_effect=AssertionError(
                    "disabled Continue without a successor must not persist"
                ),
            ) as save:
                rejected = workspace.dispatch("training.continue", {})

            self.assertEqual("error", rejected.kind)
            save.assert_not_called()
            self.assertEqual(session_before, workspace.session.snapshot())
            self.assertEqual(surface_before, workspace.snapshot())
            self.assertEqual(revision_before, workspace._revision)


    def test_training_language_survives_bridge_rebuild_after_render_rollback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-training-language-rollback-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    opened = app.browser_command("shell", "screen.training")
                    self.assertEqual("route", opened["kind"])
                    switched = app.browser_command(
                        "training",
                        "training.language",
                        {"language": "en"},
                    )
                    self.assertEqual("render", switched["kind"])
                    self.assertEqual(
                        "en",
                        app.training_workspace.snapshot()["document"]["lang"],
                    )

                    before = app.training_workspace.session.snapshot()
                    with patch(
                        "acs.training_webview_projection.TrainingWebViewProjection._render",
                        side_effect=RuntimeError("simulated post-language render failure"),
                    ):
                        rejected = app.browser_command(
                            "training",
                            "training.submit",
                            {"answer": "not-a-legal-move"},
                        )

                    self.assertEqual("error", rejected["kind"])
                    self.assertEqual(before, app.training_workspace.session.snapshot())
                    rebuilt = app.training_workspace.snapshot()
                    self.assertEqual("en", rebuilt["document"]["lang"])
                    self.assertEqual("Training", rebuilt["heading"])

                    # A failed language render used to return the generic error
                    # from the rejected target language even though the workspace
                    # correctly rolled back to the prior language. Compare with a
                    # same-state control error so the event and restored surface
                    # must remain language-coherent for screen-reader output.
                    control_error = app.browser_command(
                        "training",
                        "training.unsupported",
                    )
                    self.assertEqual("error", control_error["kind"])
                    with patch(
                        "acs.training_webview_projection.TrainingWebViewProjection.snapshot",
                        side_effect=RuntimeError("simulated language render failure"),
                    ):
                        failed_language = app.browser_command(
                            "training",
                            "training.language",
                            {"language": "ua"},
                        )

                    self.assertEqual("error", failed_language["kind"])
                    rebuilt = app.training_workspace.snapshot()
                    self.assertEqual("en", rebuilt["document"]["lang"])
                    self.assertEqual("Training", rebuilt["heading"])
                    self.assertEqual(
                        control_error["payload"]["message"],
                        failed_language["payload"]["message"],
                    )

                    with patch(
                        "acs.training_webview_projection.TrainingWebViewProjection._render",
                        side_effect=RuntimeError("simulated native Training render failure"),
                    ):
                        native_failed = app.adapter.activate_action("training.hint")
                    self.assertEqual("error", native_failed.kind)
                    self.assertEqual(
                        control_error["payload"]["message"],
                        native_failed.payload["message"],
                    )
                    self.assertEqual(
                        "en",
                        app.training_workspace.snapshot()["document"]["lang"],
                    )

                    reset_before = app.training_workspace.session.snapshot()
                    native_reset = app.adapter.activate_action("training.reset")
                    self.assertEqual("error", native_reset.kind)
                    self.assertEqual(
                        control_error["payload"]["message"],
                        native_reset.payload["message"],
                    )
                    self.assertEqual(
                        reset_before,
                        app.training_workspace.session.snapshot(),
                    )
                    self.assertEqual(
                        "en",
                        app.training_workspace.snapshot()["document"]["lang"],
                    )
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_training_escaped_error_projection_failure_restores_session(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-training-double-failure-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    opened = app.browser_command("shell", "screen.training")
                    self.assertEqual("route", opened["kind"])
                    before = app.training_workspace.session.snapshot()
                    revision_before = app.training_workspace._revision

                    with patch(
                        "acs.training_webview_projection.TrainingWebViewProjection._render",
                        side_effect=RuntimeError("simulated submit render failure"),
                    ), patch(
                        "acs.training_webview_projection.TrainingWebViewProjection.generic_error",
                        side_effect=RuntimeError("simulated error projection failure"),
                    ):
                        rejected = app.browser_command(
                            "training",
                            "training.submit",
                            {"answer": "not-a-legal-move"},
                        )

                    self.assertEqual("error", rejected["kind"])
                    self.assertEqual(before, app.training_workspace.session.snapshot())
                    self.assertEqual(revision_before, app.training_workspace._revision)
                    self.assertEqual("training", app.shell.current_route.route_id)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_training_continue_book_progress_failure_restores_completed_origin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-continue-save-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    opened = app.browser_command("shell", "screen.training")
                    self.assertEqual("route", opened["kind"])
                    current = app.training_workspace.material.definition.steps[0]
                    completed = app.browser_command(
                        "training",
                        "training.submit",
                        {"answer": next(iter(current.accepted_moves))},
                    )
                    self.assertEqual("render", completed["kind"])
                    self.assertTrue(app.training_workspace.session.completed)
                    reader_before = app.reader.snapshot()
                    training_before = app.training_workspace.snapshot()
                    key_before = app.book_key

                    with patch.object(
                        app.progress_store,
                        "save",
                        side_effect=OSError("simulated Book progress failure"),
                    ):
                        rejected = app.browser_command("training", "training.continue")

                    self.assertEqual("error", rejected["kind"])
                    self.assertEqual("training", app.shell.current_route.route_id)
                    self.assertEqual(key_before, app.book_key)
                    self.assertEqual(reader_before, app.reader.snapshot())
                    self.assertEqual(training_before, app.training_workspace.snapshot())
                    self.assertTrue(app.training_workspace.session.completed)

                    with patch.object(
                        app.progress_store,
                        "save",
                        side_effect=OSError("simulated Book progress failure"),
                    ):
                        native = app.adapter.activate_action("training.continue")
                    self.assertEqual("error", native.kind)
                    self.assertEqual("training", app.shell.current_route.route_id)
                    self.assertEqual(reader_before, app.reader.snapshot())
                    self.assertEqual(training_before, app.training_workspace.snapshot())
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_training_continue_render_error_restores_completed_origin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-continue-render-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    opened = app.browser_command("shell", "screen.training")
                    self.assertEqual("route", opened["kind"])
                    switched = app.browser_command(
                        "training",
                        "training.language",
                        {"language": "en"},
                    )
                    self.assertEqual("render", switched["kind"])
                    current = app.training_workspace.material.definition.steps[0]
                    completed = app.browser_command(
                        "training",
                        "training.submit",
                        {"answer": next(iter(current.accepted_moves))},
                    )
                    self.assertEqual("render", completed["kind"])
                    self.assertTrue(app.training_workspace.session.completed)
                    reader_before = app.reader.snapshot()
                    training_before = app.training_workspace.snapshot()
                    message_before = app.training_workspace.presenter_message
                    message_key_before = app.training_workspace.presenter_message_key
                    self.assertEqual("Exercise completed.", message_before)
                    self.assertEqual("completed", message_key_before)
                    key_before = app.book_key
                    durable_before = app.progress_store.restore(
                        key_before,
                        app.reader.document,
                    ).snapshot()

                    with patch(
                        "acs.training_webview_projection.TrainingWebViewProjection.retry",
                        side_effect=RuntimeError("simulated next exercise render failure"),
                    ):
                        rejected = app.browser_command("training", "training.continue")

                    self.assertEqual("error", rejected["kind"])
                    self.assertEqual("training", app.shell.current_route.route_id)
                    self.assertEqual(key_before, app.book_key)
                    self.assertEqual(reader_before, app.reader.snapshot())
                    self.assertEqual(training_before, app.training_workspace.snapshot())
                    self.assertEqual(message_before, app.training_workspace.presenter_message)
                    self.assertEqual(
                        message_key_before,
                        app.training_workspace.presenter_message_key,
                    )
                    self.assertEqual(
                        durable_before,
                        app.progress_store.restore(
                            key_before,
                            app.reader.document,
                        ).snapshot(),
                    )
                    self.assertTrue(app.training_workspace.session.completed)
                    self.assertEqual(
                        "en",
                        app.training_workspace.snapshot()["document"]["lang"],
                    )

                    with patch(
                        "acs.training_webview_projection.TrainingWebViewProjection.retry",
                        side_effect=RuntimeError("simulated native continuation render failure"),
                    ):
                        native = app.adapter.activate_action("training.continue")

                    self.assertEqual("error", native.kind)
                    self.assertEqual("training", app.shell.current_route.route_id)
                    self.assertEqual(key_before, app.book_key)
                    self.assertEqual(reader_before, app.reader.snapshot())
                    self.assertEqual(training_before, app.training_workspace.snapshot())
                    self.assertEqual(message_before, app.training_workspace.presenter_message)
                    self.assertEqual(
                        message_key_before,
                        app.training_workspace.presenter_message_key,
                    )
                    self.assertEqual(
                        durable_before,
                        app.progress_store.restore(
                            key_before,
                            app.reader.document,
                        ).snapshot(),
                    )
                    self.assertTrue(app.training_workspace.session.completed)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_training_continue_render_error_does_not_require_secondary_rebuild(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-render-local-rollback-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    opened = app.browser_command("shell", "screen.training")
                    self.assertEqual("route", opened["kind"])
                    current = app.training_workspace.material.definition.steps[0]
                    completed = app.browser_command(
                        "training",
                        "training.submit",
                        {"answer": next(iter(current.accepted_moves))},
                    )
                    self.assertEqual("render", completed["kind"])
                    self.assertTrue(app.training_workspace.session.completed)
                    reader_before = app.reader.snapshot()
                    training_before = app.training_workspace.snapshot()
                    key_before = app.book_key
                    durable_before = app.progress_store.restore(
                        key_before,
                        app.reader.document,
                    ).snapshot()

                    with patch(
                        "acs.training_webview_projection.TrainingWebViewProjection.retry",
                        side_effect=RuntimeError("simulated next exercise render failure"),
                    ), patch(
                        "acs.version2_application.Version2BookTrainingWorkspace.start_current",
                        side_effect=AssertionError(
                            "local workspace rollback must avoid secondary Training rebuild"
                        ),
                    ) as rebuild:
                        rejected = app.browser_command("training", "training.continue")

                    self.assertEqual("error", rejected["kind"])
                    rebuild.assert_not_called()
                    self.assertEqual("training", app.shell.current_route.route_id)
                    self.assertEqual(reader_before, app.reader.snapshot())
                    self.assertEqual(training_before, app.training_workspace.snapshot())
                    self.assertIs(app.training, app.training_workspace.bridge)
                    self.assertTrue(app.training_workspace.session.completed)
                    self.assertEqual(
                        durable_before,
                        app.progress_store.restore(
                            key_before,
                            app.reader.document,
                        ).snapshot(),
                    )
                    self.assertFalse(
                        any(
                            item["kind"] == "route"
                            and item["payload"].get("route_id") == "books"
                            for item in app.drain_events()
                        )
                    )
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_training_continue_escaped_error_projection_failure_restores_completed_origin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-render-double-failure-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    opened = app.browser_command("shell", "screen.training")
                    self.assertEqual("route", opened["kind"])
                    current = app.training_workspace.material.definition.steps[0]
                    completed = app.browser_command(
                        "training",
                        "training.submit",
                        {"answer": next(iter(current.accepted_moves))},
                    )
                    self.assertEqual("render", completed["kind"])
                    self.assertTrue(app.training_workspace.session.completed)
                    reader_before = app.reader.snapshot()
                    training_before = app.training_workspace.snapshot()
                    key_before = app.book_key
                    durable_before = app.progress_store.restore(
                        key_before,
                        app.reader.document,
                    ).snapshot()

                    with patch(
                        "acs.training_webview_projection.TrainingWebViewProjection.retry",
                        side_effect=RuntimeError("simulated next exercise render failure"),
                    ), patch(
                        "acs.training_webview_projection.TrainingWebViewProjection.generic_error",
                        side_effect=RuntimeError("simulated error projection failure"),
                    ):
                        rejected = app.browser_command("training", "training.continue")

                    self.assertEqual("error", rejected["kind"])
                    self.assertEqual("training", app.shell.current_route.route_id)
                    self.assertEqual(key_before, app.book_key)
                    self.assertEqual(reader_before, app.reader.snapshot())
                    self.assertEqual(training_before, app.training_workspace.snapshot())
                    self.assertEqual(
                        durable_before,
                        app.progress_store.restore(
                            key_before,
                            app.reader.document,
                        ).snapshot(),
                    )
                    self.assertTrue(app.training_workspace.session.completed)

                    with patch(
                        "acs.training_webview_projection.TrainingWebViewProjection.retry",
                        side_effect=RuntimeError("simulated native next exercise render failure"),
                    ), patch(
                        "acs.training_webview_projection.TrainingWebViewProjection.generic_error",
                        side_effect=RuntimeError("simulated native error projection failure"),
                    ):
                        native = app.adapter.activate_action("training.continue")

                    self.assertEqual("error", native.kind)
                    self.assertEqual("training", app.shell.current_route.route_id)
                    self.assertEqual(key_before, app.book_key)
                    self.assertEqual(reader_before, app.reader.snapshot())
                    self.assertEqual(training_before, app.training_workspace.snapshot())
                    self.assertEqual(
                        durable_before,
                        app.progress_store.restore(
                            key_before,
                            app.reader.document,
                        ).snapshot(),
                    )
                    self.assertTrue(app.training_workspace.session.completed)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_training_continue_secondary_restore_failure_recovers_to_books(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-secondary-restore-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    opened = app.browser_command("shell", "screen.training")
                    self.assertEqual("route", opened["kind"])
                    current = app.training_workspace.material.definition.steps[0]
                    app.browser_command(
                        "training",
                        "training.submit",
                        {"answer": next(iter(current.accepted_moves))},
                    )
                    reader_before = app.reader.snapshot()

                    with patch.object(
                        app.progress_store,
                        "save",
                        side_effect=OSError("simulated Book progress failure"),
                    ), patch(
                        "acs.version2_application.Version2BookTrainingWorkspace.start_current",
                        side_effect=ValueError("simulated Training restore failure"),
                    ):
                        rejected = app.browser_command("training", "training.continue")

                    self.assertEqual("error", rejected["kind"])
                    self.assertEqual(reader_before, app.reader.snapshot())
                    self.assertIsNone(app.training_workspace)
                    self.assertIsNone(app.training)
                    self.assertEqual("books", app.shell.current_route.route_id)
                    events = app.drain_events()
                    self.assertTrue(
                        any(
                            item["kind"] == "route"
                            and item["payload"].get("route_id") == "books"
                            for item in events
                        )
                    )
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_modal_dialog_blocks_training_mutations_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-training-modal-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    opened = app.browser_command("shell", "screen.training")
                    self.assertEqual("route", opened["kind"])
                    switched = app.browser_command(
                        "training",
                        "training.language",
                        {"language": "en"},
                    )
                    self.assertEqual("render", switched["kind"])
                    training_error = app.training_workspace.bridge.projection.generic_error()
                    before = app.training_workspace.snapshot()
                    dialog = app.adapter.open_dialog(
                        "training-modal",
                        opener_focus_id="training-answer",
                        initial_focus_id="training-modal-confirm",
                    )
                    self.assertEqual("dialog-open", dialog.kind)

                    with patch.object(
                        app.training_workspace,
                        "dispatch",
                        side_effect=AssertionError(
                            "modal Training commands must be rejected before workspace dispatch"
                        ),
                    ) as dispatch:
                        browser_result = app.browser_command("training", "training.hint")
                        native_result = app.adapter.activate_action("training.hint")

                    self.assertEqual("error", browser_result["kind"])
                    self.assertEqual("error", native_result.kind)
                    self.assertEqual(
                        training_error.payload["message"],
                        browser_result["payload"]["message"],
                    )
                    self.assertEqual(
                        browser_result["payload"]["message"],
                        native_result.payload["message"],
                    )
                    dispatch.assert_not_called()
                    self.assertEqual(before, app.training_workspace.snapshot())
                    self.assertEqual("training-modal", app.shell.active_dialog_id)
                    self.assertEqual("training", app.shell.current_route.route_id)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_active_book_board_blocks_native_picker_before_selection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-board-picker-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    app.browser_command("shell", "screen.books")
                    self.assertEqual(
                        "render",
                        app.browser_command("books", "book.next_position")["kind"],
                    )
                    self.assertEqual(
                        "delegated",
                        app.browser_command("books", "book.open_position")["kind"],
                    )
                    self.assertTrue(app.book_workflow.active)
                    picker_calls = []
                    app.open_book_dialog = lambda: picker_calls.append(True) or None

                    result = app.adapter.activate_action("book.open")

                    self.assertEqual("error", result.kind)
                    self.assertEqual([], picker_calls)
                    self.assertTrue(app.book_workflow.active)
                    self.assertEqual("board", app.shell.current_route.route_id)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


if __name__ == "__main__":
    unittest.main()
