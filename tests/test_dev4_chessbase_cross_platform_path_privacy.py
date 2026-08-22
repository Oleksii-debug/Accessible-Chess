from __future__ import annotations

from pathlib import Path
import unittest

from acs.chessbase_adapter import probe_chessbase_source
from acs.chessbase_integrity import ChessBaseIntegritySnapshot, SourceFileEvidence
from acs.chessbase_manifest import ChessBaseBundleManifest, ComponentEvidence
from acs.report_paths import report_safe_name


class Dev4ChessBaseCrossPlatformPathPrivacyTests(unittest.TestCase):
    """Report-safe identifiers must not leak workstation directories cross-platform."""

    WINDOWS_PRIVATE_PATH = r"C:\Users\PrivateUser\Documents\Training Database.CBH"
    SAFE_NAME = "Training Database.CBH"

    def _assert_report_safe_name(self, serialized: object) -> None:
        value = str(serialized)
        self.assertNotIn("PrivateUser", value)
        self.assertNotIn("Documents", value)
        self.assertNotIn("Users", value)
        self.assertEqual(value, self.SAFE_NAME)

    def test_shared_sanitizer_is_host_independent_for_slash_and_backslash_paths(self) -> None:
        cases = (
            self.WINDOWS_PRIVATE_PATH,
            r"\\server\private-share\folder\Training Database.CBH",
            "/home/private-user/Documents/Training Database.CBH",
            r"C:/Users/PrivateUser\Documents/Training Database.CBH",
        )
        for source in cases:
            with self.subTest(source=source):
                self.assertEqual(report_safe_name(source), self.SAFE_NAME)

    def test_adapter_windows_style_private_path_is_not_serialized_whole_on_posix(self) -> None:
        report = probe_chessbase_source(self.WINDOWS_PRIVATE_PATH).as_report_fields()
        self._assert_report_safe_name(report["source_path"])

    def test_integrity_snapshot_windows_style_private_paths_are_report_safe(self) -> None:
        evidence = SourceFileEvidence(
            path=Path(self.WINDOWS_PRIVATE_PATH),
            extension=".cbh",
            role="primary_source",
            size_bytes=1,
            sha256="0" * 64,
        )
        report = ChessBaseIntegritySnapshot(
            primary_path=Path(self.WINDOWS_PRIVATE_PATH),
            files=(evidence,),
        ).as_report_fields()

        self._assert_report_safe_name(report["primary_path"])
        self._assert_report_safe_name(report["files"][0]["path"])

    def test_manifest_windows_style_private_paths_are_report_safe(self) -> None:
        evidence = ComponentEvidence(
            path=self.WINDOWS_PRIVATE_PATH,
            extension=".cbh",
            role="primary database source",
            size=1,
            sha256="0" * 64,
        )
        report = ChessBaseBundleManifest(
            schema_version=1,
            primary_path=self.WINDOWS_PRIVATE_PATH,
            source_kind="component_set",
            family_name="ChessBase classic database",
            status="evidence_collected",
            primary=evidence,
        ).as_dict()

        self._assert_report_safe_name(report["primary_path"])
        self._assert_report_safe_name(report["primary"]["path"])


if __name__ == "__main__":
    unittest.main()
