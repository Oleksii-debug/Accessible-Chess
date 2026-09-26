from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from acs import classroom_domain as cd
from acs import education_workspace as ew
from acs import education_workspace_store as ews
from acs.teaching_session import PositionSourceKind, TeachingPositionSource


class PreparedPositionDurabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classroom = cd.ClassroomSnapshot()
        self.workspace = ew.EducationWorkspace.empty(self.classroom)

    def test_prepared_position_reuses_canonical_source_and_round_trips(self):
        source = TeachingPositionSource(
            PositionSourceKind.PGN,
            source_ref="game-001",
            source_index=17,
        )
        changed = ew.save_prepared_position(
            self.workspace,
            position_id="prep-001",
            source=source,
            expected_position_revision=0,
        )

        item = ew.get_prepared_position(changed, "prep-001")
        self.assertEqual(item.position_id, "prep-001")
        self.assertEqual(item.revision, 0)
        self.assertEqual(item.source, source)
        self.assertEqual(item.source.kind, PositionSourceKind.PGN)
        self.assertEqual(item.source.source_ref, "game-001")
        self.assertEqual(item.source.source_index, 17)

        restored = ew.EducationWorkspace.from_json(changed.to_json())
        self.assertEqual(restored, changed)
        self.assertEqual(restored.to_json(), changed.to_json())
        self.assertEqual(
            ew.get_prepared_position(restored, "prep-001").source.source_index,
            17,
        )

    def test_prepared_position_revision_is_cas_guarded_and_retry_is_idempotent(self):
        first_source = TeachingPositionSource(
            PositionSourceKind.PGN,
            source_ref="game-001",
            source_index=17,
        )
        created = ew.save_prepared_position(
            self.workspace,
            position_id="prep-001",
            source=first_source,
            expected_position_revision=0,
        )
        retry = ew.save_prepared_position(
            created,
            position_id="prep-001",
            source=first_source,
            expected_position_revision=0,
        )
        self.assertIs(retry, created)

        second_source = TeachingPositionSource(
            PositionSourceKind.FEN,
            fen="8/8/8/8/8/8/4K3/6k1 w - - 0 1",
        )
        updated = ew.save_prepared_position(
            created,
            position_id="prep-001",
            source=second_source,
            expected_position_revision=0,
        )
        item = ew.get_prepared_position(updated, "prep-001")
        self.assertEqual(item.revision, 1)
        self.assertEqual(item.source, second_source)

        before = updated.to_json()
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.save_prepared_position(
                updated,
                position_id="prep-001",
                source=first_source,
                expected_position_revision=0,
            )
        self.assertEqual(updated.to_json(), before)

    def test_workspace_store_save_reopen_preserves_position_identity_and_provenance(self):
        source = TeachingPositionSource(
            PositionSourceKind.DATABASE,
            source_ref="acsdb-game-42",
        )
        changed = ew.save_prepared_position(
            self.workspace,
            position_id="prep-db-42",
            source=source,
            expected_position_revision=0,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "education-workspace.json"
            store = ews.EducationWorkspaceStore(path)
            revision = store.save(changed, expected_revision=None)
            reopened = store.load()
            self.assertIsNotNone(reopened)
            self.assertEqual(reopened.revision, revision)
            self.assertEqual(reopened.workspace, changed)
            item = ew.get_prepared_position(reopened.workspace, "prep-db-42")
            self.assertEqual(item.position_id, "prep-db-42")
            self.assertEqual(item.revision, 0)
            self.assertEqual(item.source.kind, PositionSourceKind.DATABASE)
            self.assertEqual(item.source.source_ref, "acsdb-game-42")
            self.assertIsNone(item.source.source_index)

    def test_legacy_workspace_without_prepared_positions_migrates_losslessly(self):
        current = self.workspace
        legacy_body = {
            "version": current.version,
            "classroom": current.classroom.to_record(),
            "ledger": current.ledger.to_record(),
        }
        legacy_record = dict(legacy_body)
        legacy_record["digest"] = ew._digest(legacy_body)

        restored = ew.EducationWorkspace.from_record(legacy_record)
        self.assertEqual(restored.classroom, current.classroom)
        self.assertEqual(restored.ledger, current.ledger)
        self.assertEqual(restored.prepared_positions, ())
        self.assertIn("prepared_positions", restored.to_record())

    def test_duplicate_identity_and_noncanonical_source_fail_closed(self):
        source = TeachingPositionSource(PositionSourceKind.START)
        position = ew.PreparedPosition("prep-001", source)
        with self.assertRaises(ew.EducationWorkspaceError):
            replace(
                self.workspace,
                prepared_positions=(position, position),
            )
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.PreparedPosition("bad id with spaces", source)
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.PreparedPosition("prep-002", object())


if __name__ == "__main__":
    unittest.main()
