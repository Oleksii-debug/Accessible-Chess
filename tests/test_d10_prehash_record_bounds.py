from __future__ import annotations

import unittest
from unittest.mock import patch

from acs import classroom_domain as cd
from acs import education_records as er
from acs import education_workspace as ew
from acs.teaching_session import PositionSourceKind, TeachingPositionSource


class D10PrehashRecordBoundsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classroom = cd.ClassroomSnapshot()
        self.ledger = er.EducationLedger.empty(self.classroom)
        self.workspace = ew.EducationWorkspace.empty(self.classroom)

    def test_ledger_collection_bound_runs_before_digest(self) -> None:
        record = self.ledger.to_record()
        record["submissions"] = [{}] * (er.MAX_RECORDS_PER_COLLECTION + 1)

        with patch.object(
            er,
            "_digest",
            side_effect=AssertionError("digest must not run before list bound"),
        ) as digest:
            with self.assertRaisesRegex(
                er.EducationRecordsError,
                "bounded JSON array",
            ):
                er.EducationLedger.from_record(record)
            digest.assert_not_called()

    def test_ledger_nested_field_validation_runs_before_digest(self) -> None:
        record = self.ledger.to_record()
        record["operation_receipts"] = [
            {
                "operation_id": "x" * 10_000,
                "operation_kind": "test",
                "payload_digest": "a" * 64,
            }
        ]

        with patch.object(
            er,
            "_digest",
            side_effect=AssertionError("digest must not run before field bounds"),
        ) as digest:
            with self.assertRaises(er.EducationRecordsError):
                er.EducationLedger.from_record(record)
            digest.assert_not_called()

    def test_workspace_prepared_position_bound_runs_before_outer_digest(self) -> None:
        record = self.workspace.to_record()
        record["prepared_positions"] = [{}] * (ew.MAX_PREPARED_POSITIONS + 1)

        with patch.object(
            ew,
            "_digest",
            side_effect=AssertionError("outer digest must not run before position bound"),
        ) as digest:
            with self.assertRaisesRegex(
                ew.EducationWorkspaceError,
                "bounded JSON array",
            ):
                ew.EducationWorkspace.from_record(record)
            digest.assert_not_called()

    def test_workspace_nested_ledger_bound_runs_before_any_outer_digest(self) -> None:
        record = self.workspace.to_record()
        record["ledger"]["submissions"] = [{}] * (
            er.MAX_RECORDS_PER_COLLECTION + 1
        )

        with (
            patch.object(
                er,
                "_digest",
                side_effect=AssertionError("ledger digest must not run before bound"),
            ) as ledger_digest,
            patch.object(
                ew,
                "_digest",
                side_effect=AssertionError("outer digest must not run first"),
            ) as workspace_digest,
        ):
            with self.assertRaisesRegex(
                ew.EducationWorkspaceError,
                "invalid nested education workspace state",
            ):
                ew.EducationWorkspace.from_record(record)
            ledger_digest.assert_not_called()
            workspace_digest.assert_not_called()

    def test_current_workspace_digest_round_trip_remains_exact(self) -> None:
        source = TeachingPositionSource(PositionSourceKind.START)
        changed = ew.save_prepared_position(
            self.workspace,
            position_id="prep-one",
            source=source,
            expected_position_revision=0,
            title="Start position",
            student_prompt="Name the center squares.",
            tags=("opening",),
            order_index=2,
            teacher_notes="Teacher-only note.",
        )
        record = changed.to_record()
        restored = ew.EducationWorkspace.from_record(record)

        self.assertEqual(restored, changed)
        self.assertEqual(restored.to_record(), record)
        self.assertEqual(restored.digest, changed.digest)

    def test_legacy_workspace_digest_migrates_from_bounded_canonical_body(self) -> None:
        legacy_body = {
            "version": self.workspace.version,
            "classroom": self.workspace.classroom.to_record(),
            "ledger": self.workspace.ledger.to_record(),
        }
        legacy = dict(legacy_body)
        legacy["digest"] = ew._digest(legacy_body)

        restored = ew.EducationWorkspace.from_record(legacy)
        self.assertEqual(restored.classroom, self.workspace.classroom)
        self.assertEqual(restored.ledger, self.workspace.ledger)
        self.assertEqual(restored.prepared_positions, ())

        tampered = dict(legacy)
        tampered["digest"] = "0" * 64
        with self.assertRaisesRegex(
            ew.EducationWorkspaceError,
            "digest mismatch",
        ):
            ew.EducationWorkspace.from_record(tampered)

    def test_ledger_wire_byte_gate_runs_before_json_parse(self) -> None:
        with (
            patch.object(er, "MAX_SNAPSHOT_BYTES", 4),
            patch.object(
                er.json,
                "loads",
                side_effect=AssertionError("json.loads must not run after overflow"),
            ) as loads,
        ):
            with self.assertRaisesRegex(
                er.EducationRecordsError,
                "size limit",
            ):
                er.EducationLedger.from_json('"ééé"')
            loads.assert_not_called()

        with patch.object(
            er.json,
            "loads",
            side_effect=AssertionError("json.loads must not receive surrogate text"),
        ) as loads:
            with self.assertRaisesRegex(
                er.EducationRecordsError,
                "invalid Unicode",
            ):
                er.EducationLedger.from_json("\ud800")
            loads.assert_not_called()

    def test_workspace_wire_byte_gate_runs_before_json_parse(self) -> None:
        with (
            patch.object(ew, "MAX_WORKSPACE_JSON_BYTES", 4),
            patch.object(
                ew.json,
                "loads",
                side_effect=AssertionError("json.loads must not run after overflow"),
            ) as loads,
        ):
            with self.assertRaisesRegex(
                ew.EducationWorkspaceError,
                "size limit",
            ):
                ew.EducationWorkspace.from_json('"ééé"')
            loads.assert_not_called()

        with patch.object(
            ew.json,
            "loads",
            side_effect=AssertionError("json.loads must not receive surrogate text"),
        ) as loads:
            with self.assertRaisesRegex(
                ew.EducationWorkspaceError,
                "invalid Unicode",
            ):
                ew.EducationWorkspace.from_json("\ud800")
            loads.assert_not_called()


if __name__ == "__main__":
    unittest.main()
