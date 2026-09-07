from __future__ import annotations

from pathlib import Path
import unittest

from acs.chessbase_adapter import probe_chessbase_source
from acs.chessbase_integrity import ChessBaseIntegritySnapshot, SourceFileEvidence
from acs.chessbase_manifest import ChessBaseBundleManifest, ComponentEvidence
from acs.report_paths import report_safe_name


class D04DriveRelativeReportPrivacyTests(unittest.TestCase):
    SAFE_NAME = "Training Database.CBH"
    DRIVE_RELATIVE_PATHS = (
        r"C:Users\PrivateUser\Documents\Training Database.CBH",
        r"D:private\course\Training Database.CBH",
        r"E:folder/PrivateUser\Training Database.CBH",
    )

    def _assert_drive_relative_is_redacted(self, value: object) -> None:
        rendered = str(value)
        self.assertEqual(rendered, self.SAFE_NAME)
        self.assertNotIn("PrivateUser", rendered)
        self.assertNotIn("Documents", rendered)
        self.assertNotIn("course", rendered)
        self.assertNotIn("folder", rendered)

    def test_shared_sanitizer_redacts_windows_drive_relative_paths(self) -> None:
        for source in self.DRIVE_RELATIVE_PATHS:
            with self.subTest(source=source):
                self._assert_drive_relative_is_redacted(report_safe_name(source))

    def test_safe_relative_provenance_is_still_preserved(self) -> None:
        self.assertEqual(
            report_safe_name(r"incoming\nested\Training Database.CBH"),
            "incoming/nested/Training Database.CBH",
        )

    def test_adapter_report_redacts_drive_relative_private_directories(self) -> None:
        for source in self.DRIVE_RELATIVE_PATHS:
            with self.subTest(source=source):
                report = probe_chessbase_source(source).as_report_fields()
                self._assert_drive_relative_is_redacted(report["source_path"])

    def test_integrity_report_redacts_drive_relative_private_directories(self) -> None:
        source = self.DRIVE_RELATIVE_PATHS[0]
        evidence = SourceFileEvidence(
            path=Path(source),
            extension=".cbh",
            role="primary_source",
            size_bytes=1,
            sha256="0" * 64,
        )
        report = ChessBaseIntegritySnapshot(
            primary_path=Path(source),
            files=(evidence,),
        ).as_report_fields()
        self._assert_drive_relative_is_redacted(report["primary_path"])
        self._assert_drive_relative_is_redacted(report["files"][0]["path"])

    def test_manifest_report_redacts_drive_relative_private_directories(self) -> None:
        source = self.DRIVE_RELATIVE_PATHS[0]
        evidence = ComponentEvidence(
            path=source,
            extension=".cbh",
            role="primary database source",
            size=1,
            sha256="0" * 64,
        )
        report = ChessBaseBundleManifest(
            schema_version=1,
            primary_path=source,
            source_kind="component_set",
            family_name="ChessBase classic database",
            status="evidence_collected",
            primary=evidence,
        ).as_dict()
        self._assert_drive_relative_is_redacted(report["primary_path"])
        self._assert_drive_relative_is_redacted(report["primary"]["path"])


if __name__ == "__main__":
    unittest.main()
