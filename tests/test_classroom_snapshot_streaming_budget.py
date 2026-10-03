from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

from acs import classroom_domain as cd
from acs import education_workspace as ew


class ClassroomSnapshotStreamingBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = cd.ClassroomSnapshot()

    def test_streaming_digest_matches_existing_canonical_json_bytes(self) -> None:
        payload = {
            "z": ["é", 7, {"nested": True}],
            "a": "canonical",
        }
        expected = hashlib.sha256(
            cd._canonical_json_text(payload).encode("utf-8")
        ).hexdigest()
        self.assertEqual(cd._digest(payload), expected)

    def test_direct_record_budget_includes_digest_without_full_text_build(self) -> None:
        record = self.snapshot.to_record()
        body = {key: value for key, value in record.items() if key != "digest"}
        body_size = len(cd._canonical_json_text(body).encode("utf-8"))
        full_size = len(cd._canonical_json_text(record).encode("utf-8"))
        self.assertGreater(full_size, body_size)

        with (
            patch.object(cd, "MAX_SNAPSHOT_BYTES", body_size),
            patch.object(
                cd,
                "_canonical_json_text",
                side_effect=AssertionError("full canonical text must not be built"),
            ) as canonical_json,
        ):
            with self.assertRaisesRegex(
                cd.ClassroomDomainError,
                "size limit",
            ):
                cd.ClassroomSnapshot.from_record(record)
            canonical_json.assert_not_called()

    def test_to_record_never_emits_an_over_budget_snapshot(self) -> None:
        record = self.snapshot.to_record()
        full_size = len(cd._canonical_json_text(record).encode("utf-8"))

        with patch.object(cd, "MAX_SNAPSHOT_BYTES", full_size - 1):
            with self.assertRaisesRegex(
                cd.ClassroomDomainError,
                "size limit",
            ):
                self.snapshot.to_record()

    def test_to_json_rejects_before_over_limit_text_materialization(self) -> None:
        record = self.snapshot.to_record()
        full_size = len(cd._canonical_json_text(record).encode("utf-8"))

        with (
            patch.object(cd, "MAX_SNAPSHOT_BYTES", full_size - 1),
            patch.object(
                cd,
                "_canonical_json_text",
                side_effect=AssertionError("over-limit text must not be built"),
            ) as canonical_json,
        ):
            with self.assertRaisesRegex(
                cd.ClassroomDomainError,
                "size limit",
            ):
                self.snapshot.to_json()
            canonical_json.assert_not_called()

    def test_wire_byte_gate_runs_before_json_parse(self) -> None:
        with (
            patch.object(cd, "MAX_SNAPSHOT_BYTES", 4),
            patch.object(
                cd.json,
                "loads",
                side_effect=AssertionError("json.loads must not run after overflow"),
            ) as loads,
        ):
            with self.assertRaisesRegex(
                cd.ClassroomDomainError,
                "size limit",
            ):
                cd.ClassroomSnapshot.from_json('"ééé"')
            loads.assert_not_called()

        with patch.object(
            cd.json,
            "loads",
            side_effect=AssertionError("json.loads must not receive surrogate text"),
        ) as loads:
            with self.assertRaisesRegex(
                cd.ClassroomDomainError,
                "invalid Unicode",
            ):
                cd.ClassroomSnapshot.from_json("\ud800")
            loads.assert_not_called()

    def test_snapshot_round_trip_remains_exact(self) -> None:
        student = cd.Student("s1", "Knight-17", consent=cd.ConsentState.GRANTED)
        snapshot = cd.ClassroomSnapshot(students=(student,))
        record = snapshot.to_record()

        restored = cd.ClassroomSnapshot.from_record(record)
        self.assertEqual(restored, snapshot)
        self.assertEqual(restored.to_record(), record)
        self.assertEqual(restored.to_json(), snapshot.to_json())

    def test_d10_workspace_cannot_embed_an_over_budget_classroom_record(self) -> None:
        workspace = ew.EducationWorkspace.empty(self.snapshot)
        classroom_record = self.snapshot.to_record()
        classroom_size = len(
            cd._canonical_json_text(classroom_record).encode("utf-8")
        )

        with patch.object(cd, "MAX_SNAPSHOT_BYTES", classroom_size - 1):
            with self.assertRaisesRegex(
                cd.ClassroomDomainError,
                "size limit",
            ):
                workspace.to_record()

    def test_d10_workspace_rejects_over_budget_nested_classroom_on_reopen(self) -> None:
        workspace = ew.EducationWorkspace.empty(self.snapshot)
        record = workspace.to_record()
        classroom_size = len(
            cd._canonical_json_text(record["classroom"]).encode("utf-8")
        )

        with patch.object(cd, "MAX_SNAPSHOT_BYTES", classroom_size - 1):
            with self.assertRaisesRegex(
                ew.EducationWorkspaceError,
                "invalid nested education workspace state",
            ):
                ew.EducationWorkspace.from_record(record)


if __name__ == "__main__":
    unittest.main()
