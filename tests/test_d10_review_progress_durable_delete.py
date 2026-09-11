from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs import classroom_domain as cd
from acs import education_workspace as ew
from acs.education_progress_lifecycle import delete_student_and_purge_reviews
from acs.education_progress_transaction import (
    EducationProgressDeletionTransaction,
    EducationProgressTransactionBusyError,
    EducationProgressTransactionConflictError,
)
from acs.education_workspace_store import EducationWorkspaceStore
from acs.student_progress import StudentProgressLedger
from acs.student_progress_store import StudentProgressStore


class _InjectedHardCrash(BaseException):
    pass


class D10ReviewProgressDurableDeleteTests(unittest.TestCase):
    @staticmethod
    def _workspace() -> ew.EducationWorkspace:
        classroom = cd.ClassroomSnapshot(
            students=(
                cd.Student("s1", "Knight-17", cd.ConsentState.GRANTED),
                cd.Student("s2", "Bishop-9"),
            )
        )
        return ew.EducationWorkspace.empty(classroom)

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

    @classmethod
    def _stores(cls, root: Path):
        workspace_store = EducationWorkspaceStore(root / "education-workspace.json")
        progress_store = StudentProgressStore(root / "student-progress.json")
        workspace_revision = workspace_store.save(cls._workspace(), expected_revision=None)
        progress_revision = progress_store.save(cls._progress(), expected_revision=None)
        return workspace_store, progress_store, workspace_revision, progress_revision

    @staticmethod
    def _assert_old_state(
        testcase: unittest.TestCase,
        workspace_store: EducationWorkspaceStore,
        progress_store: StudentProgressStore,
    ) -> None:
        workspace = workspace_store.load()
        progress = progress_store.load()
        testcase.assertIsNotNone(workspace)
        testcase.assertIsNotNone(progress)
        assert workspace is not None and progress is not None
        student = next(
            item
            for item in workspace.workspace.classroom.students
            if item.student_id == "s1"
        )
        testcase.assertFalse(student.deleted)
        records = progress.ledger.snapshot()["records"]
        testcase.assertEqual(
            sum(record["student_id"] == "s1" for record in records),
            2,
        )

    @staticmethod
    def _assert_new_state(
        testcase: unittest.TestCase,
        workspace_store: EducationWorkspaceStore,
        progress_store: StudentProgressStore,
    ) -> None:
        workspace = workspace_store.load()
        progress = progress_store.load()
        testcase.assertIsNotNone(workspace)
        testcase.assertIsNotNone(progress)
        assert workspace is not None and progress is not None
        student = next(
            item
            for item in workspace.workspace.classroom.students
            if item.student_id == "s1"
        )
        testcase.assertTrue(student.deleted)
        testcase.assertEqual(student.pseudonym, "")
        records = progress.ledger.snapshot()["records"]
        testcase.assertFalse(any(record["student_id"] == "s1" for record in records))
        testcase.assertEqual(
            sum(record["student_id"] == "s2" for record in records),
            1,
        )

    @staticmethod
    def _assert_transaction_residue_clean(
        testcase: unittest.TestCase,
        root: Path,
        transaction: EducationProgressDeletionTransaction,
        workspace_store: EducationWorkspaceStore,
        progress_store: StudentProgressStore,
    ) -> None:
        testcase.assertFalse(transaction.journal_path.exists())
        testcase.assertFalse(workspace_store._lock_path.exists())
        testcase.assertFalse(progress_store._lock_path.exists())
        testcase.assertEqual(
            list(root.glob(".education-progress-transaction-*")),
            [],
        )

    def test_end_to_end_delete_publishes_both_canonical_stores(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            workspace_store, progress_store, _, _ = self._stores(root)
            transaction = EducationProgressDeletionTransaction(
                workspace_store,
                progress_store,
            )

            publication = transaction.delete_student(
                student_id="s1",
                operation_id="durable-delete-s1",
                expected_student_revision=0,
                expected_ledger_revision=0,
            )

            self.assertEqual(publication.purged_record_count, 2)
            self.assertEqual(
                workspace_store.load().revision,  # type: ignore[union-attr]
                publication.workspace_revision,
            )
            self.assertEqual(
                progress_store.load().revision,  # type: ignore[union-attr]
                publication.progress_revision,
            )
            self._assert_new_state(self, workspace_store, progress_store)
            self._assert_transaction_residue_clean(
                self,
                root,
                transaction,
                workspace_store,
                progress_store,
            )

    def test_hard_crash_before_commit_point_recovers_to_exact_old_pair(self) -> None:
        for crash_phase in ("staging", "locking", "locked"):
            with self.subTest(crash_phase=crash_phase):
                with tempfile.TemporaryDirectory() as raw_dir:
                    root = Path(raw_dir)
                    (
                        workspace_store,
                        progress_store,
                        workspace_revision,
                        progress_revision,
                    ) = self._stores(root)
                    old_workspace = workspace_store.path.read_bytes()
                    old_progress = progress_store.path.read_bytes()
                    transaction = EducationProgressDeletionTransaction(
                        workspace_store,
                        progress_store,
                    )

                    def crash(phase: str) -> None:
                        if phase == crash_phase:
                            raise _InjectedHardCrash(phase)

                    with patch.object(transaction, "_after_phase", side_effect=crash):
                        with self.assertRaises(_InjectedHardCrash):
                            transaction.delete_student(
                                student_id="s1",
                                operation_id=f"crash-before-{crash_phase}",
                                expected_student_revision=0,
                                expected_ledger_revision=0,
                            )

                    recovered = EducationProgressDeletionTransaction(
                        workspace_store,
                        progress_store,
                    )
                    self.assertTrue(recovered.recover_pending())
                    self.assertEqual(workspace_store.path.read_bytes(), old_workspace)
                    self.assertEqual(progress_store.path.read_bytes(), old_progress)
                    self.assertEqual(
                        workspace_store.load().revision,  # type: ignore[union-attr]
                        workspace_revision,
                    )
                    self.assertEqual(
                        progress_store.load().revision,  # type: ignore[union-attr]
                        progress_revision,
                    )
                    self._assert_old_state(self, workspace_store, progress_store)
                    self._assert_transaction_residue_clean(
                        self,
                        root,
                        recovered,
                        workspace_store,
                        progress_store,
                    )

    def test_hard_crash_after_commit_point_rolls_forward_to_exact_new_pair(self) -> None:
        for crash_phase in ("prepared", "workspace_published", "both_published"):
            with self.subTest(crash_phase=crash_phase):
                with tempfile.TemporaryDirectory() as raw_dir:
                    root = Path(raw_dir)
                    workspace_store, progress_store, _, _ = self._stores(root)
                    transaction = EducationProgressDeletionTransaction(
                        workspace_store,
                        progress_store,
                    )

                    def crash(phase: str) -> None:
                        if phase == crash_phase:
                            raise _InjectedHardCrash(phase)

                    with patch.object(transaction, "_after_phase", side_effect=crash):
                        with self.assertRaises(_InjectedHardCrash):
                            transaction.delete_student(
                                student_id="s1",
                                operation_id=f"crash-after-{crash_phase}",
                                expected_student_revision=0,
                                expected_ledger_revision=0,
                            )

                    recovered = EducationProgressDeletionTransaction(
                        workspace_store,
                        progress_store,
                    )
                    self.assertTrue(recovered.recover_pending())
                    self._assert_new_state(self, workspace_store, progress_store)
                    self._assert_transaction_residue_clean(
                        self,
                        root,
                        recovered,
                        workspace_store,
                        progress_store,
                    )

    def test_committed_recovery_preserves_unknown_newer_bytes_and_stays_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            workspace_store, progress_store, _, _ = self._stores(root)
            transaction = EducationProgressDeletionTransaction(
                workspace_store,
                progress_store,
            )

            def crash(phase: str) -> None:
                if phase == "prepared":
                    raise _InjectedHardCrash(phase)

            with patch.object(transaction, "_after_phase", side_effect=crash):
                with self.assertRaises(_InjectedHardCrash):
                    transaction.delete_student(
                        student_id="s1",
                        operation_id="prepared-conflict",
                        expected_student_revision=0,
                        expected_ledger_revision=0,
                    )

            # Simulate a non-cooperating external writer/tamper. Normal canonical
            # writers cannot do this because the transaction owns their peer lock.
            unknown = b'{"external":"newer-unknown"}'
            progress_store.path.write_bytes(unknown)
            recovered = EducationProgressDeletionTransaction(
                workspace_store,
                progress_store,
            )
            with self.assertRaises(EducationProgressTransactionConflictError):
                recovered.recover_pending()
            self.assertEqual(progress_store.path.read_bytes(), unknown)
            self.assertTrue(recovered.journal_path.exists())

    def test_foreign_peer_writer_blocks_without_touching_either_store(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            workspace_store, progress_store, _, _ = self._stores(root)
            old_workspace = workspace_store.path.read_bytes()
            old_progress = progress_store.path.read_bytes()
            progress_store._lock_path.mkdir()
            try:
                transaction = EducationProgressDeletionTransaction(
                    workspace_store,
                    progress_store,
                )
                with self.assertRaises(EducationProgressTransactionBusyError):
                    transaction.delete_student(
                        student_id="s1",
                        operation_id="busy-delete",
                        expected_student_revision=0,
                        expected_ledger_revision=0,
                    )
                self.assertEqual(workspace_store.path.read_bytes(), old_workspace)
                self.assertEqual(progress_store.path.read_bytes(), old_progress)
                self.assertFalse(transaction.journal_path.exists())
            finally:
                progress_store._lock_path.rmdir()

    def test_stale_store_revision_fails_before_commit_and_preserves_newer_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            (
                workspace_store,
                progress_store,
                workspace_revision,
                progress_revision,
            ) = self._stores(root)
            loaded_workspace = workspace_store.load()
            loaded_progress = progress_store.load()
            assert loaded_workspace is not None and loaded_progress is not None
            result = delete_student_and_purge_reviews(
                loaded_workspace.workspace,
                loaded_progress.ledger,
                student_id="s1",
                operation_id="stale-publish",
                expected_student_revision=0,
                expected_ledger_revision=0,
            )

            # A legitimate peer updates progress after the transition was built.
            newer = loaded_progress.ledger
            newer.append_game_review(
                record_id="s2-newer",
                student_id="s2",
                session_id="lesson-b",
                sequence=1,
                game_ref="game-newer",
                source_revision="rev-newer",
            )
            newer_revision = progress_store.save(
                newer,
                expected_revision=progress_revision,
            )
            newer_bytes = progress_store.path.read_bytes()

            transaction = EducationProgressDeletionTransaction(
                workspace_store,
                progress_store,
            )
            with self.assertRaises(EducationProgressTransactionConflictError):
                transaction.publish(
                    result,
                    expected_workspace_revision=workspace_revision,
                    expected_progress_revision=progress_revision,
                )
            self.assertEqual(progress_store.path.read_bytes(), newer_bytes)
            self.assertEqual(
                progress_store.load().revision,  # type: ignore[union-attr]
                newer_revision,
            )
            self.assertFalse(transaction.journal_path.exists())
            self._assert_transaction_residue_clean(
                self,
                root,
                transaction,
                workspace_store,
                progress_store,
            )

    def test_missing_progress_file_is_created_as_empty_privacy_safe_authority(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            workspace_store = EducationWorkspaceStore(root / "education-workspace.json")
            workspace_store.save(self._workspace(), expected_revision=None)
            progress_store = StudentProgressStore(root / "student-progress.json")
            transaction = EducationProgressDeletionTransaction(
                workspace_store,
                progress_store,
            )

            result = transaction.delete_student(
                student_id="s1",
                operation_id="delete-without-progress-file",
                expected_student_revision=0,
                expected_ledger_revision=0,
            )

            self.assertEqual(result.purged_record_count, 0)
            loaded_workspace = workspace_store.load()
            loaded_progress = progress_store.load()
            self.assertIsNotNone(loaded_workspace)
            self.assertIsNotNone(loaded_progress)
            assert loaded_workspace is not None and loaded_progress is not None
            student = next(
                item
                for item in loaded_workspace.workspace.classroom.students
                if item.student_id == "s1"
            )
            self.assertTrue(student.deleted)
            self.assertEqual(loaded_progress.ledger.snapshot()["records"], [])


if __name__ == "__main__":
    unittest.main()
