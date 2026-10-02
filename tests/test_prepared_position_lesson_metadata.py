from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs import classroom_domain as cd
from acs import education_workspace as ew
from acs import education_workspace_store as ews
from acs.teaching_session import PositionSourceKind, TeachingPositionSource


class PreparedPositionLessonMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = ew.EducationWorkspace.empty(cd.ClassroomSnapshot())
        self.source = TeachingPositionSource(
            PositionSourceKind.PGN,
            source_ref="game-lesson-001",
            source_index=11,
        )

    def _save_named(self) -> ew.EducationWorkspace:
        return ew.save_prepared_position(
            self.workspace,
            position_id="prep-fork",
            source=self.source,
            expected_position_revision=0,
            title="Knight fork",
            student_prompt="Find the forcing move and explain both threats.",
            tags=("tactics", "fork"),
            order_index=3,
            teacher_notes="Do not reveal the queen target before the student answers.",
        )

    def test_named_metadata_round_trips_without_copying_chess_authority(self) -> None:
        changed = self._save_named()
        item = ew.get_prepared_position(changed, "prep-fork")

        self.assertEqual(item.position_id, "prep-fork")
        self.assertEqual(item.source, self.source)
        self.assertEqual(item.revision, 0)
        self.assertEqual(item.title, "Knight fork")
        self.assertEqual(
            item.student_prompt,
            "Find the forcing move and explain both threats.",
        )
        self.assertEqual(item.tags, ("tactics", "fork"))
        self.assertEqual(item.order_index, 3)
        self.assertEqual(
            item.teacher_notes,
            "Do not reveal the queen target before the student answers.",
        )
        self.assertFalse(hasattr(item, "board"))

        restored = ew.EducationWorkspace.from_json(changed.to_json())
        self.assertEqual(restored, changed)
        self.assertEqual(restored.to_json(), changed.to_json())
        record = restored.to_record()["prepared_positions"][0]
        self.assertEqual(
            record["schema_version"],
            ew.PREPARED_POSITION_RECORD_VERSION,
        )

    def test_existing_source_only_call_preserves_metadata_and_is_idempotent(self) -> None:
        changed = self._save_named()
        retry = ew.save_prepared_position(
            changed,
            position_id="prep-fork",
            source=self.source,
            expected_position_revision=0,
        )
        self.assertIs(retry, changed)

        item = ew.get_prepared_position(retry, "prep-fork")
        self.assertEqual(item.title, "Knight fork")
        self.assertEqual(item.tags, ("tactics", "fork"))
        self.assertEqual(item.order_index, 3)

    def test_metadata_update_uses_same_position_cas_revision(self) -> None:
        changed = self._save_named()
        updated = ew.save_prepared_position(
            changed,
            position_id="prep-fork",
            source=self.source,
            expected_position_revision=0,
            student_prompt="Name the forked pieces.",
            tags=("tactics", "fork", "guided"),
            order_index=4,
            teacher_notes="Ask for both attacked pieces before showing arrows.",
        )
        item = ew.get_prepared_position(updated, "prep-fork")

        self.assertEqual(item.revision, 1)
        self.assertEqual(item.source, self.source)
        self.assertEqual(item.title, "Knight fork")
        self.assertEqual(item.student_prompt, "Name the forked pieces.")
        self.assertEqual(item.tags, ("tactics", "fork", "guided"))
        self.assertEqual(item.order_index, 4)

        with self.assertRaisesRegex(
            ew.EducationWorkspaceError,
            "stale prepared position revision",
        ):
            ew.save_prepared_position(
                updated,
                position_id="prep-fork",
                source=self.source,
                expected_position_revision=0,
                title="Stale overwrite",
            )

    def test_source_change_preserves_omitted_metadata_and_increments_revision(self) -> None:
        changed = self._save_named()
        new_source = TeachingPositionSource(
            PositionSourceKind.FEN,
            fen="8/8/8/8/8/8/4K3/6k1 w - -",
        )
        updated = ew.save_prepared_position(
            changed,
            position_id="prep-fork",
            source=new_source,
            expected_position_revision=0,
        )
        item = ew.get_prepared_position(updated, "prep-fork")
        self.assertEqual(item.revision, 1)
        self.assertEqual(item.source, new_source)
        self.assertEqual(item.title, "Knight fork")
        self.assertEqual(
            item.student_prompt,
            "Find the forcing move and explain both threats.",
        )
        self.assertEqual(item.tags, ("tactics", "fork"))
        self.assertEqual(
            item.teacher_notes,
            "Do not reveal the queen target before the student answers.",
        )

    def test_legacy_prepared_position_record_migrates_with_safe_named_defaults(self) -> None:
        source = TeachingPositionSource(PositionSourceKind.START)
        old_position = {
            "position_id": "legacy-prep",
            "source": {
                "kind": source.kind.value,
                "fen": source.fen,
                "source_ref": source.source_ref,
                "source_index": source.source_index,
            },
            "revision": 7,
        }
        body = {
            "version": self.workspace.version,
            "classroom": self.workspace.classroom.to_record(),
            "ledger": self.workspace.ledger.to_record(),
            "prepared_positions": [old_position],
        }
        record = dict(body)
        record["digest"] = ew._digest(body)

        restored = ew.EducationWorkspace.from_record(record)
        item = ew.get_prepared_position(restored, "legacy-prep")

        self.assertEqual(item.revision, 7)
        self.assertEqual(item.title, "legacy-prep")
        self.assertEqual(item.student_prompt, "")
        self.assertEqual(item.tags, ())
        self.assertEqual(item.order_index, 0)
        self.assertEqual(item.teacher_notes, "")
        new_record = restored.to_record()["prepared_positions"][0]
        self.assertEqual(
            new_record["schema_version"],
            ew.PREPARED_POSITION_RECORD_VERSION,
        )
        self.assertEqual(new_record["title"], "legacy-prep")


    def test_ordered_read_is_stable_by_order_index_then_position_id(self) -> None:
        workspace = self.workspace
        for position_id, order_index in (
            ("prep-z", 2),
            ("prep-b", 1),
            ("prep-a", 1),
        ):
            workspace = ew.save_prepared_position(
                workspace,
                position_id=position_id,
                source=self.source,
                expected_position_revision=0,
                title=position_id,
                order_index=order_index,
            )

        self.assertEqual(
            tuple(item.position_id for item in ew.ordered_prepared_positions(workspace)),
            ("prep-a", "prep-b", "prep-z"),
        )

        current = ew.get_prepared_position(workspace, "prep-z")
        workspace = ew.save_prepared_position(
            workspace,
            position_id="prep-z",
            source=current.source,
            expected_position_revision=current.revision,
            order_index=0,
        )
        moved = ew.get_prepared_position(workspace, "prep-z")
        self.assertEqual(moved.revision, 1)
        self.assertEqual(
            tuple(item.position_id for item in ew.ordered_prepared_positions(workspace)),
            ("prep-z", "prep-a", "prep-b"),
        )


    def test_delete_prepared_position_requires_exact_cas_and_preserves_peers(self) -> None:
        first = self._save_named()
        with_peer = ew.save_prepared_position(
            first,
            position_id="prep-peer",
            source=TeachingPositionSource(PositionSourceKind.START),
            expected_position_revision=0,
            title="Peer",
            order_index=9,
        )

        with self.assertRaisesRegex(
            ew.EducationWorkspaceError,
            "stale prepared position revision",
        ):
            ew.delete_prepared_position(
                with_peer,
                position_id="prep-fork",
                expected_position_revision=1,
            )
        self.assertEqual(len(with_peer.prepared_positions), 2)

        deleted = ew.delete_prepared_position(
            with_peer,
            position_id="prep-fork",
            expected_position_revision=0,
        )
        self.assertEqual(
            tuple(item.position_id for item in deleted.prepared_positions),
            ("prep-peer",),
        )
        self.assertEqual(
            ew.get_prepared_position(deleted, "prep-peer").title,
            "Peer",
        )
        with self.assertRaisesRegex(
            ew.EducationWorkspaceError,
            "unknown or ambiguous prepared position",
        ):
            ew.delete_prepared_position(
                deleted,
                position_id="prep-fork",
                expected_position_revision=0,
            )

    def test_deleted_prepared_position_stays_deleted_after_store_reopen(self) -> None:
        changed = self._save_named()
        deleted = ew.delete_prepared_position(
            changed,
            position_id="prep-fork",
            expected_position_revision=0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = ews.EducationWorkspaceStore(
                Path(tmp) / "education-workspace.json"
            )
            revision = store.save(deleted, expected_revision=None)
            loaded = store.load()
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.revision, revision)
            self.assertEqual(loaded.workspace.prepared_positions, ())
            with self.assertRaisesRegex(
                ew.EducationWorkspaceError,
                "unknown or ambiguous prepared position",
            ):
                ew.get_prepared_position(loaded.workspace, "prep-fork")

    def test_store_reopen_preserves_metadata_and_teacher_notes(self) -> None:
        changed = self._save_named()
        with tempfile.TemporaryDirectory() as tmp:
            store = ews.EducationWorkspaceStore(
                Path(tmp) / "education-workspace.json"
            )
            revision = store.save(changed, expected_revision=None)
            loaded = store.load()
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.revision, revision)
            self.assertEqual(loaded.workspace, changed)
            item = ew.get_prepared_position(loaded.workspace, "prep-fork")
            self.assertEqual(item.title, "Knight fork")
            self.assertEqual(item.tags, ("tactics", "fork"))
            self.assertEqual(
                item.teacher_notes,
                "Do not reveal the queen target before the student answers.",
            )

    def test_teacher_notes_are_excluded_from_dataclass_diagnostics(self) -> None:
        secret = "Private coaching note that must not enter routine repr output."
        position = ew.PreparedPosition(
            "prep-private",
            self.source,
            teacher_notes=secret,
        )
        self.assertEqual(position.teacher_notes, secret)
        self.assertNotIn(secret, repr(position))

    def test_source_only_legacy_caller_gets_stable_visible_title(self) -> None:
        changed = ew.save_prepared_position(
            self.workspace,
            position_id="prep-source-only",
            source=TeachingPositionSource(PositionSourceKind.START),
            expected_position_revision=0,
        )
        item = ew.get_prepared_position(changed, "prep-source-only")
        self.assertEqual(item.title, "prep-source-only")
        self.assertEqual(item.student_prompt, "")
        self.assertEqual(item.tags, ())
        self.assertEqual(item.order_index, 0)
        self.assertEqual(item.teacher_notes, "")

    def test_metadata_bounds_and_canonical_shapes_fail_closed(self) -> None:
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.PreparedPosition(
                "prep-title-space",
                self.source,
                title=" Leading space",
            )
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.PreparedPosition(
                "prep-title-newline",
                self.source,
                title="Two\nLines",
            )
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.PreparedPosition(
                "prep-tags-list",
                self.source,
                tags=["tactics"],
            )
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.PreparedPosition(
                "prep-tags-duplicate",
                self.source,
                tags=("fork", "fork"),
            )
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.PreparedPosition(
                "prep-tag-newline",
                self.source,
                tags=("fork\nx",),
            )
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.PreparedPosition(
                "prep-order-bool",
                self.source,
                order_index=True,
            )
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.PreparedPosition(
                "prep-prompt-long",
                self.source,
                student_prompt="x" * (ew.MAX_PREPARED_POSITION_PROMPT_CHARS + 1),
            )
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.PreparedPosition(
                "prep-notes-surrogate",
                self.source,
                teacher_notes="\ud800",
            )

    def test_future_or_malformed_metadata_record_fails_closed_after_valid_digest(self) -> None:
        changed = self._save_named()

        future = changed.to_record()
        future["prepared_positions"][0]["schema_version"] = 999
        body = {key: value for key, value in future.items() if key != "digest"}
        future["digest"] = ew._digest(body)
        with self.assertRaisesRegex(
            ew.EducationWorkspaceError,
            "unsupported prepared position schema version",
        ):
            ew.EducationWorkspace.from_record(future)

        malformed = changed.to_record()
        malformed["prepared_positions"][0]["tags"] = "tactics"
        body = {key: value for key, value in malformed.items() if key != "digest"}
        malformed["digest"] = ew._digest(body)
        with self.assertRaisesRegex(
            ew.EducationWorkspaceError,
            "tags must be a JSON array",
        ):
            ew.EducationWorkspace.from_record(malformed)

        unknown = changed.to_record()
        unknown["prepared_positions"][0]["unexpected"] = True
        body = {key: value for key, value in unknown.items() if key != "digest"}
        unknown["digest"] = ew._digest(body)
        with self.assertRaisesRegex(
            ew.EducationWorkspaceError,
            "prepared position schema mismatch",
        ):
            ew.EducationWorkspace.from_record(unknown)


if __name__ == "__main__":
    unittest.main()
