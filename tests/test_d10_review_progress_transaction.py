from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs import classroom_domain as cd
from acs import education_workspace as ew
from acs.education_progress_transaction import (
    EducationProgressJournalError,
    EducationProgressRecoveryRequired,
    EducationProgressTransactionConflict,
    delete_student_and_purge_reviews_durable,
    recover_pending_student_deletion,
)
from acs.education_workspace_store import EducationWorkspaceStore
from acs.student_progress import StudentProgressLedger
from acs.student_progress_store import StudentProgressStore


class _SimulatedCrash(BaseException):
    pass


class D10ReviewProgressTransactionTests(unittest.TestCase):
    @staticmethod
    def _workspace() -> ew.EducationWorkspace:
        return ew.EducationWorkspace.empty(
            cd.ClassroomSnapshot(
                students=(
                    cd.Student("s1", "Knight-17", cd.ConsentState.GRANTED),
                    cd.Student("s2", "Bishop-9"),
                )
            )
        )

    @staticmethod
    def _progress() -> StudentProgressLedger:
        progress = StudentProgressLedger()
        progress.append_game_review(
            record_id="s1-review-a",
            student_id="s1",
            session_id="lesson-a",
            sequence=1,
            game_ref="game-a",
            source_revision="rev-a",
        )
        progress.append_game_review(
            record_id="s2-review",
            student_id="s2",
            session_id="lesson-a",
            sequence=1,
            game_ref="game-b",
            source_revision="rev-b",
        )
        progress.append_game_review(
            record_id="s1-review-b",
            student_id="s1",
            session_id="lesson-b",
            sequence=1,
            game_ref="game-c",
            source_revision="rev-c",
        )
        return progress

    @staticmethod
    def _stores(root: Path) -> tuple[EducationWorkspaceStore, StudentProgressStore]:
        return (
            EducationWorkspaceStore(root / "education-workspace.json"),
            StudentProgressStore(root / "student-progress.json"),
        )

    def _seed(
        self,
        root: Path,
    ) -> tuple[EducationWorkspaceStore, StudentProgressStore, str, str]:
        workspace_store, progress_store = self._stores(root)
        workspace_revision = workspace_store.save(
            self._workspace(),
            expected_revision=None,
        )
        progress_revision = progress_store.save(
            self._progress(),
            expected_revision=None,
        )
        return (
            workspace_store,
            progress_store,
            workspace_revision,
            progress_revision,
        )

    @staticmethod
    def _journal_path(workspace_store: EducationWorkspaceStore) -> Path:
        return workspace_store.path.with_name(
            f".{workspace_store.path.name}.student-delete.journal"
        )

    @staticmethod
    def _assert_deleted(
        workspace_store: EducationWorkspaceStore,
        progress_store: StudentProgressStore,
    ) -> None:
        loaded_workspace = workspace_store.load()
        loaded_progress = progress_store.load()
        assert loaded_workspace is not None
        assert loaded_progress is not None
        deleted = next(
            student
            for student in loaded_workspace.workspace.classroom.students
            if student.student_id == "s1"
        )
        assert deleted.deleted
        assert deleted.pseudonym == ""
        records = loaded_progress.ledger.snapshot()["records"]
        assert not any(record["student_id"] == "s1" for record in records)
        assert any(record["student_id"] == "s2" for record in records)

    def test_durable_delete_publishes_both_stores_and_cleans_journal(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            workspace_store, progress_store, _workspace_rev, _progress_rev = self._seed(
                Path(raw_dir)
            )

            result = delete_student_and_purge_reviews_durable(
                workspace_store,
                progress_store,
                student_id="s1",
                operation_id="delete-s1",
                expected_student_revision=0,
                expected_ledger_revision=0,
            )

            self.assertEqual(result.purged_record_count, 2)
            self.assertFalse(result.recovered)
            self.assertFalse(self._journal_path(workspace_store).exists())
            self._assert_deleted(workspace_store, progress_store)

    def test_crash_before_progress_publication_recovers_by_rolling_forward(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            workspace_store, progress_store, workspace_rev, progress_rev = self._seed(
                Path(raw_dir)
            )

            with patch.object(
                progress_store,
                "save",
                side_effect=_SimulatedCrash("crash-before-progress"),
            ):
                with self.assertRaises(_SimulatedCrash):
                    delete_student_and_purge_reviews_durable(
                        workspace_store,
                        progress_store,
                        student_id="s1",
                        operation_id="delete-s1",
                        expected_student_revision=0,
                        expected_ledger_revision=0,
                    )

            self.assertTrue(self._journal_path(workspace_store).exists())
            self.assertEqual(workspace_store.load().revision, workspace_rev)  # type: ignore[union-attr]
            self.assertEqual(progress_store.load().revision, progress_rev)  # type: ignore[union-attr]

            recovered = recover_pending_student_deletion(
                workspace_store,
                progress_store,
            )
            self.assertIsNotNone(recovered)
            assert recovered is not None
            self.assertTrue(recovered.recovered)
            self.assertEqual(recovered.purged_record_count, 2)
            self.assertFalse(self._journal_path(workspace_store).exists())
            self._assert_deleted(workspace_store, progress_store)

    def test_crash_after_progress_publication_recovers_workspace_without_restoring_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            workspace_store, progress_store, workspace_rev, _progress_rev = self._seed(
                Path(raw_dir)
            )

            with patch.object(
                workspace_store,
                "save",
                side_effect=_SimulatedCrash("crash-after-progress"),
            ):
                with self.assertRaises(_SimulatedCrash):
                    delete_student_and_purge_reviews_durable(
                        workspace_store,
                        progress_store,
                        student_id="s1",
                        operation_id="delete-s1",
                        expected_student_revision=0,
                        expected_ledger_revision=0,
                    )

            self.assertTrue(self._journal_path(workspace_store).exists())
            self.assertEqual(workspace_store.load().revision, workspace_rev)  # type: ignore[union-attr]
            loaded_progress = progress_store.load()
            assert loaded_progress is not None
            self.assertFalse(
                any(
                    record["student_id"] == "s1"
                    for record in loaded_progress.ledger.snapshot()["records"]
                )
            )

            recovered = recover_pending_student_deletion(
                workspace_store,
                progress_store,
            )
            self.assertIsNotNone(recovered)
            assert recovered is not None
            self.assertTrue(recovered.recovered)
            self._assert_deleted(workspace_store, progress_store)

    def test_journal_contains_no_predelete_review_payload(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            workspace_store, progress_store, _workspace_rev, _progress_rev = self._seed(
                Path(raw_dir)
            )

            with patch.object(
                progress_store,
                "save",
                side_effect=_SimulatedCrash("inspect-journal"),
            ):
                with self.assertRaises(_SimulatedCrash):
                    delete_student_and_purge_reviews_durable(
                        workspace_store,
                        progress_store,
                        student_id="s1",
                        operation_id="delete-s1",
                        expected_student_revision=0,
                        expected_ledger_revision=0,
                    )

            journal = self._journal_path(workspace_store).read_text(encoding="utf-8")
            self.assertNotIn("s1-review-a", journal)
            self.assertNotIn("s1-review-b", journal)
            self.assertNotIn("game-a", journal)
            self.assertNotIn("source_revision", journal)

    def test_external_progress_change_after_intent_fails_closed_without_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            workspace_store, progress_store, workspace_rev, progress_rev = self._seed(
                Path(raw_dir)
            )

            with patch.object(
                progress_store,
                "save",
                side_effect=_SimulatedCrash("pause-before-progress"),
            ):
                with self.assertRaises(_SimulatedCrash):
                    delete_student_and_purge_reviews_durable(
                        workspace_store,
                        progress_store,
                        student_id="s1",
                        operation_id="delete-s1",
                        expected_student_revision=0,
                        expected_ledger_revision=0,
                    )

            concurrent = progress_store.load()
            assert concurrent is not None
            concurrent.ledger.append_game_review(
                record_id="s2-concurrent",
                student_id="s2",
                session_id="lesson-a",
                sequence=2,
                game_ref="game-concurrent",
                source_revision="rev-concurrent",
            )
            concurrent_revision = progress_store.save(
                concurrent.ledger,
                expected_revision=progress_rev,
            )

            with self.assertRaises(EducationProgressTransactionConflict):
                recover_pending_student_deletion(workspace_store, progress_store)

            self.assertTrue(self._journal_path(workspace_store).exists())
            self.assertEqual(workspace_store.load().revision, workspace_rev)  # type: ignore[union-attr]
            self.assertEqual(progress_store.load().revision, concurrent_revision)  # type: ignore[union-attr]
            loaded = progress_store.load()
            assert loaded is not None
            self.assertTrue(
                any(
                    record["record_id"] == "s2-concurrent"
                    for record in loaded.ledger.snapshot()["records"]
                )
            )

    def test_pending_transaction_blocks_second_delete_until_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            workspace_store, progress_store, _workspace_rev, _progress_rev = self._seed(
                Path(raw_dir)
            )

            with patch.object(
                progress_store,
                "save",
                side_effect=_SimulatedCrash("pending"),
            ):
                with self.assertRaises(_SimulatedCrash):
                    delete_student_and_purge_reviews_durable(
                        workspace_store,
                        progress_store,
                        student_id="s1",
                        operation_id="delete-s1",
                        expected_student_revision=0,
                        expected_ledger_revision=0,
                    )

            with self.assertRaises(EducationProgressRecoveryRequired):
                delete_student_and_purge_reviews_durable(
                    workspace_store,
                    progress_store,
                    student_id="s2",
                    operation_id="delete-s2",
                    expected_student_revision=0,
                    expected_ledger_revision=0,
                )

    def test_malformed_journal_fails_closed_and_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            workspace_store, progress_store, _workspace_rev, _progress_rev = self._seed(
                Path(raw_dir)
            )
            journal_path = self._journal_path(workspace_store)
            journal_path.write_text('{"schema_version":1, "broken":true}', encoding="utf-8")

            with self.assertRaises(EducationProgressJournalError):
                recover_pending_student_deletion(workspace_store, progress_store)

            self.assertTrue(journal_path.exists())

    def test_missing_progress_store_uses_single_store_atomic_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            workspace_store, progress_store = self._stores(root)
            workspace_store.save(self._workspace(), expected_revision=None)

            result = delete_student_and_purge_reviews_durable(
                workspace_store,
                progress_store,
                student_id="s1",
                operation_id="delete-s1-no-progress",
                expected_student_revision=0,
                expected_ledger_revision=0,
            )

            self.assertIsNone(result.progress_revision)
            self.assertEqual(result.purged_record_count, 0)
            self.assertFalse(progress_store.path.exists())
            self.assertFalse(self._journal_path(workspace_store).exists())
            loaded = workspace_store.load()
            assert loaded is not None
            deleted = next(
                student
                for student in loaded.workspace.classroom.students
                if student.student_id == "s1"
            )
            self.assertTrue(deleted.deleted)

    def test_no_pending_journal_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            workspace_store, progress_store, _workspace_rev, _progress_rev = self._seed(
                Path(raw_dir)
            )
            self.assertIsNone(
                recover_pending_student_deletion(workspace_store, progress_store)
            )


if __name__ == "__main__":
    unittest.main()
