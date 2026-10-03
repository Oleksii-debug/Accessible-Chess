from __future__ import annotations

import copy
import hashlib
import unittest
from unittest.mock import patch

from acs import classroom_domain as cd
from acs import education_records as er
from acs import education_workspace as ew
from acs.teaching_session import PositionSourceKind, TeachingPositionSource


class D10StreamingDigestBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classroom = cd.ClassroomSnapshot()
        self.ledger = er.EducationLedger.empty(self.classroom)
        self.workspace = ew.EducationWorkspace.empty(self.classroom)

    def test_streaming_digest_is_byte_identical_to_canonical_json(self) -> None:
        payload = {
            "z": ["é", 7, {"nested": True}],
            "a": "canonical",
        }
        expected_records = hashlib.sha256(
            er._canonical_json(payload).encode("utf-8")
        ).hexdigest()
        expected_workspace = hashlib.sha256(
            ew._canonical_json(payload).encode("utf-8")
        ).hexdigest()

        self.assertEqual(er._digest(payload), expected_records)
        self.assertEqual(ew._digest(payload), expected_workspace)

    def test_ledger_direct_record_budget_includes_digest_without_full_text_build(self) -> None:
        record = self.ledger.to_record()
        body = {key: value for key, value in record.items() if key != "digest"}
        body_size = len(er._canonical_json(body).encode("utf-8"))
        full_size = len(er._canonical_json(record).encode("utf-8"))
        self.assertGreater(full_size, body_size)

        with (
            patch.object(er, "MAX_SNAPSHOT_BYTES", body_size),
            patch.object(
                er,
                "_canonical_json",
                side_effect=AssertionError("full canonical text must not be built"),
            ) as canonical_json,
        ):
            with self.assertRaisesRegex(
                er.EducationRecordsError,
                "size limit",
            ):
                er.EducationLedger.from_record(record)
            canonical_json.assert_not_called()

    def test_workspace_direct_record_budget_includes_digest_without_full_text_build(self) -> None:
        record = self.workspace.to_record()
        body = {key: value for key, value in record.items() if key != "digest"}
        body_size = len(ew._canonical_json(body).encode("utf-8"))
        full_size = len(ew._canonical_json(record).encode("utf-8"))
        self.assertGreater(full_size, body_size)

        with (
            patch.object(ew, "MAX_WORKSPACE_JSON_BYTES", body_size),
            patch.object(
                ew,
                "_canonical_json",
                side_effect=AssertionError("full canonical text must not be built"),
            ) as canonical_json,
        ):
            with self.assertRaisesRegex(
                ew.EducationWorkspaceError,
                "size limit",
            ):
                ew.EducationWorkspace.from_record(record)
            canonical_json.assert_not_called()

    def test_ledger_to_json_rejects_before_over_limit_text_materialization(self) -> None:
        record = self.ledger.to_record()
        full_size = len(er._canonical_json(record).encode("utf-8"))

        with (
            patch.object(er, "MAX_SNAPSHOT_BYTES", full_size - 1),
            patch.object(
                er,
                "_canonical_json",
                side_effect=AssertionError("over-limit text must not be built"),
            ) as canonical_json,
        ):
            with self.assertRaisesRegex(
                er.EducationRecordsError,
                "size limit",
            ):
                self.ledger.to_json()
            canonical_json.assert_not_called()

    def test_workspace_to_json_rejects_before_over_limit_text_materialization(self) -> None:
        record = self.workspace.to_record()
        full_size = len(ew._canonical_json(record).encode("utf-8"))

        with (
            patch.object(ew, "MAX_WORKSPACE_JSON_BYTES", full_size - 1),
            patch.object(
                ew,
                "_canonical_json",
                side_effect=AssertionError("over-limit text must not be built"),
            ) as canonical_json,
        ):
            with self.assertRaisesRegex(
                ew.EducationWorkspaceError,
                "size limit",
            ):
                self.workspace.to_json()
            canonical_json.assert_not_called()

    def test_workspace_digest_authenticates_exact_current_wire_record(self) -> None:
        saved = ew.save_prepared_position(
            self.workspace,
            position_id="prep-one",
            source=TeachingPositionSource(PositionSourceKind.START),
            expected_position_revision=0,
        )
        record = saved.to_record()
        self.assertEqual(record["prepared_positions"][0]["title"], "prep-one")

        # Empty title is accepted by the in-memory constructor as a shorthand
        # and canonicalized to position_id.  The persisted current-schema wire
        # record must not be able to exploit that normalization while retaining
        # the digest of the canonical record.
        tampered = copy.deepcopy(record)
        tampered["prepared_positions"][0]["title"] = ""

        with self.assertRaisesRegex(
            ew.EducationWorkspaceError,
            "digest mismatch",
        ):
            ew.EducationWorkspace.from_record(tampered)

    def test_current_and_legacy_workspace_round_trips_remain_exact(self) -> None:
        saved = ew.save_prepared_position(
            self.workspace,
            position_id="prep-one",
            source=TeachingPositionSource(PositionSourceKind.START),
            expected_position_revision=0,
            title="Opening checkpoint",
            student_prompt="Name the central squares.",
        )
        current = saved.to_record()
        self.assertEqual(ew.EducationWorkspace.from_record(current), saved)

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


if __name__ == "__main__":
    unittest.main()
