from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from acs.cbz_extractor import (
    CbzExtractCode,
    CbzExtractError,
    _WORKSPACE_MARKER,
    _WORKSPACE_PREFIX,
    _WORKSPACE_PURPOSE,
    _WORKSPACE_SCHEMA_VERSION,
    recover_stale_cbz_workspaces,
)


class CbzCrashResidueRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _workspace(self, suffix: str, *, owner_pid: int = 424242, age_seconds: float = 10.0, marker: bool = True) -> Path:
        workspace = self.root / f"{_WORKSPACE_PREFIX}{suffix}"
        workspace.mkdir()
        if marker:
            payload = {
                "schema_version": _WORKSPACE_SCHEMA_VERSION,
                "purpose": _WORKSPACE_PURPOSE,
                "workspace_name": workspace.name,
                "owner_pid": owner_pid,
                "created_unix_ns": time.time_ns() - int(age_seconds * 1_000_000_000),
            }
            (workspace / _WORKSPACE_MARKER).write_text(
                json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return workspace

    def test_stale_marker_qualified_dead_owner_is_removed(self) -> None:
        workspace = self._workspace("dead")
        (workspace / "payload.cbv").write_bytes(b"\x08\x00private-decrypted-data")
        extracted = workspace / "extracted"
        extracted.mkdir()
        (extracted / "db.cbh").write_bytes(b"private-cbh")
        with mock.patch("acs.cbz_extractor._pid_is_running", return_value=False):
            report = recover_stale_cbz_workspaces(
                self.root,
                min_age_seconds=1,
                max_scan_entries=32,
                max_workspace_entries=32,
                max_workspace_bytes=1024 * 1024,
            )
        self.assertFalse(workspace.exists())
        self.assertEqual(report.removed, 1)
        self.assertEqual(report.candidates, 1)
        self.assertGreater(report.bytes_removed, 0)
        self.assertEqual(report.failed, 0)

    def test_fresh_workspace_is_preserved_even_when_owner_is_dead(self) -> None:
        workspace = self._workspace("fresh", age_seconds=0.0)
        with mock.patch("acs.cbz_extractor._pid_is_running", return_value=False):
            report = recover_stale_cbz_workspaces(self.root, min_age_seconds=60)
        self.assertTrue(workspace.is_dir())
        self.assertEqual(report.removed, 0)
        self.assertEqual(report.skipped_fresh, 1)

    def test_stale_workspace_owned_by_current_process_is_preserved(self) -> None:
        workspace = self._workspace("active", owner_pid=os.getpid())
        report = recover_stale_cbz_workspaces(self.root, min_age_seconds=1)
        self.assertTrue(workspace.is_dir())
        self.assertEqual(report.removed, 0)
        self.assertEqual(report.skipped_active, 1)

    def test_owner_is_rechecked_immediately_before_delete(self) -> None:
        workspace = self._workspace("race")
        with mock.patch("acs.cbz_extractor._pid_is_running", side_effect=[False, True]) as running:
            report = recover_stale_cbz_workspaces(self.root, min_age_seconds=1)
        self.assertEqual(running.call_count, 2)
        self.assertTrue(workspace.is_dir())
        self.assertEqual(report.removed, 0)
        self.assertEqual(report.skipped_active, 1)

    def test_unmarked_and_duplicate_key_markers_are_never_deleted(self) -> None:
        unmarked = self._workspace("unmarked", marker=False)
        malformed = self._workspace("duplicate", marker=False)
        created = time.time_ns() - 10_000_000_000
        (malformed / _WORKSPACE_MARKER).write_text(
            (
                '{"created_unix_ns":%d,"owner_pid":424242,"owner_pid":424243,'
                '"purpose":"%s","schema_version":%d,"workspace_name":"%s"}\n'
            )
            % (created, _WORKSPACE_PURPOSE, _WORKSPACE_SCHEMA_VERSION, malformed.name),
            encoding="utf-8",
        )
        with mock.patch("acs.cbz_extractor._pid_is_running", return_value=False):
            report = recover_stale_cbz_workspaces(self.root, min_age_seconds=1)
        self.assertTrue(unmarked.is_dir())
        self.assertTrue(malformed.is_dir())
        self.assertEqual(report.removed, 0)
        self.assertEqual(report.skipped_untrusted, 2)

    def test_marker_bound_to_different_workspace_name_is_preserved(self) -> None:
        workspace = self._workspace("wrong-name")
        marker = workspace / _WORKSPACE_MARKER
        payload = json.loads(marker.read_text(encoding="utf-8"))
        payload["workspace_name"] = f"{_WORKSPACE_PREFIX}someone-else"
        marker.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
        with mock.patch("acs.cbz_extractor._pid_is_running", return_value=False):
            report = recover_stale_cbz_workspaces(self.root, min_age_seconds=1)
        self.assertTrue(workspace.is_dir())
        self.assertEqual(report.removed, 0)
        self.assertEqual(report.skipped_untrusted, 1)

    def test_unsafe_symlink_inside_workspace_is_preserved(self) -> None:
        workspace = self._workspace("symlink")
        outside = self.root / "outside-private.bin"
        outside.write_bytes(b"do-not-touch")
        try:
            os.symlink(outside, workspace / "payload.cbv")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with mock.patch("acs.cbz_extractor._pid_is_running", return_value=False):
            report = recover_stale_cbz_workspaces(self.root, min_age_seconds=1)
        self.assertTrue(workspace.is_dir())
        self.assertEqual(outside.read_bytes(), b"do-not-touch")
        self.assertEqual(report.removed, 0)
        self.assertEqual(report.skipped_unsafe, 1)

    def test_workspace_resource_bound_prevents_delete(self) -> None:
        workspace = self._workspace("oversized")
        (workspace / "payload.cbv").write_bytes(b"x" * 64)
        with mock.patch("acs.cbz_extractor._pid_is_running", return_value=False):
            report = recover_stale_cbz_workspaces(
                self.root,
                min_age_seconds=1,
                max_workspace_entries=32,
                max_workspace_bytes=16,
            )
        self.assertTrue(workspace.is_dir())
        self.assertEqual(report.removed, 0)
        self.assertEqual(report.skipped_oversized, 1)

    def test_root_scan_bound_fails_before_any_candidate_deletion(self) -> None:
        workspace = self._workspace("candidate")
        (self.root / "foreign-a").mkdir()
        (self.root / "foreign-b").mkdir()
        with mock.patch("acs.cbz_extractor._pid_is_running", return_value=False):
            with self.assertRaises(CbzExtractError) as caught:
                recover_stale_cbz_workspaces(self.root, min_age_seconds=1, max_scan_entries=2)
        self.assertEqual(caught.exception.code, CbzExtractCode.RESOURCE_LIMIT)
        self.assertTrue(workspace.is_dir())

    def test_report_contains_counts_only_not_private_paths(self) -> None:
        workspace = self._workspace("privacy")
        (workspace / "payload.cbv").write_bytes(b"\x08\x00secret")
        with mock.patch("acs.cbz_extractor._pid_is_running", return_value=False):
            report = recover_stale_cbz_workspaces(self.root, min_age_seconds=1)
        rendered = repr(report)
        self.assertNotIn(str(self.root), rendered)
        self.assertNotIn(workspace.name, rendered)
        self.assertNotIn("payload.cbv", rendered)
        self.assertEqual(report.removed, 1)

    def test_machine_contract_keeps_cbz_blocked_and_recovery_bounded(self) -> None:
        manifest = (
            Path(__file__).parents[1]
            / "docs"
            / "automation"
            / "V2_CBZ_CRASH_RESIDUE_RECOVERY.json"
        )
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload["scope"], "cbz-crash-residue-recovery-only")
        self.assertEqual(payload["format_status"], "BLOCKED")
        self.assertFalse(payload["support_promotion_allowed"])
        self.assertTrue(payload["recovery_contract"]["explicit_root_only"])
        self.assertTrue(payload["recovery_contract"]["marker_qualified_only"])
        self.assertTrue(payload["recovery_contract"]["active_owner_preserved"])
        self.assertTrue(payload["recovery_contract"]["predelete_revalidation"])
        self.assertTrue(payload["recovery_contract"]["resource_bounded"])
        self.assertFalse(payload["integration"]["windows_host_wired"])


if __name__ == "__main__":
    unittest.main()
