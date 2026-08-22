from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.chessbase_adapter import probe_chessbase_source, report_safe_name
from acs.chessbase_integrity import ChessBaseIntegritySnapshot, SourceFileEvidence
from acs.chessbase_manifest import ChessBaseBundleManifest, ComponentEvidence
from acs.gametree import parse_games
from acs.pgn_service import save_pgn_atomic


class DevBChessBaseReportPrivacyTests(unittest.TestCase):
    WINDOWS_PRIVATE_PATH = r"C:\Users\PrivateUser\Documents\Training Database.CBH"
    SAFE_NAME = "Training Database.CBH"

    def assert_report_safe(self, value: object) -> None:
        rendered = str(value)
        self.assertEqual(self.SAFE_NAME, rendered)
        self.assertNotIn("PrivateUser", rendered)
        self.assertNotIn("Documents", rendered)
        self.assertNotIn("Users", rendered)

    def test_shared_report_name_is_separator_neutral(self) -> None:
        self.assertEqual(self.SAFE_NAME, report_safe_name(self.WINDOWS_PRIVATE_PATH))
        self.assertEqual(self.SAFE_NAME, report_safe_name("/srv/private/Training Database.CBH"))
        self.assertEqual(
            self.SAFE_NAME,
            report_safe_name(r"C:\private/mixed\Training Database.CBH"),
        )

    def test_adapter_integrity_and_manifest_share_report_safe_projection(self) -> None:
        adapter_report = probe_chessbase_source(self.WINDOWS_PRIVATE_PATH).as_report_fields()
        self.assert_report_safe(adapter_report["source_path"])

        source_evidence = SourceFileEvidence(
            path=Path(self.WINDOWS_PRIVATE_PATH),
            extension=".cbh",
            role="primary_source",
            size_bytes=1,
            sha256="0" * 64,
        )
        integrity_report = ChessBaseIntegritySnapshot(
            primary_path=Path(self.WINDOWS_PRIVATE_PATH),
            files=(source_evidence,),
        ).as_report_fields()
        self.assert_report_safe(integrity_report["primary_path"])
        self.assert_report_safe(integrity_report["files"][0]["path"])

        component_evidence = ComponentEvidence(
            path=self.WINDOWS_PRIVATE_PATH,
            extension=".cbh",
            role="primary database source",
            size=1,
            sha256="0" * 64,
        )
        manifest_report = ChessBaseBundleManifest(
            schema_version=1,
            primary_path=self.WINDOWS_PRIVATE_PATH,
            source_kind="component_set",
            family_name="ChessBase classic database",
            status="evidence_collected",
            primary=component_evidence,
        ).as_dict()
        self.assert_report_safe(manifest_report["primary_path"])
        self.assert_report_safe(manifest_report["primary"]["path"])


class DevBPgnNoClobberCommitTests(unittest.TestCase):
    def test_post_commit_temp_cleanup_failure_does_not_report_save_failure(self) -> None:
        games = parse_games('[Event "Committed"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "new.pgn"
            real_unlink = Path.unlink
            injected = False

            def fail_first_postcommit_temp_cleanup(path: Path, *args, **kwargs):
                nonlocal injected
                if (
                    not injected
                    and path.name.startswith(destination.name + ".")
                    and path.name.endswith(".tmp")
                    and destination.exists()
                ):
                    injected = True
                    raise OSError("temp cleanup failed after commit")
                return real_unlink(path, *args, **kwargs)

            with mock.patch(
                "pathlib.Path.unlink",
                autospec=True,
                side_effect=fail_first_postcommit_temp_cleanup,
            ):
                result = save_pgn_atomic(destination, games, overwrite=False)

            self.assertTrue(injected)
            self.assertTrue(destination.exists())
            self.assertIn("Committed", destination.read_text(encoding="utf-8"))
            self.assertEqual(result.sha256, result.sha256.lower())
            self.assertEqual(64, len(result.sha256))


if __name__ == "__main__":
    unittest.main()
