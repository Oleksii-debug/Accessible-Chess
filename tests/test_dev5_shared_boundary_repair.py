from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.chessbase_adapter import probe_chessbase_source, report_safe_path_name
from acs.chessbase_integrity import ChessBaseIntegritySnapshot, SourceFileEvidence
from acs.chessbase_manifest import ChessBaseBundleManifest, ComponentEvidence, verify_manifest_unchanged
from acs.gametree import parse_games
from acs.pgn_service import save_pgn_atomic


class Dev5SharedBoundaryRepairTests(unittest.TestCase):
    WINDOWS_PRIVATE_PATH = r"C:\Users\PrivateUser\Documents\Training Database.CBH"
    SAFE_NAME = "Training Database.CBH"

    def test_report_name_is_host_independent_for_both_separator_conventions(self) -> None:
        self.assertEqual(report_safe_path_name(self.WINDOWS_PRIVATE_PATH), self.SAFE_NAME)
        self.assertEqual(
            report_safe_path_name("/home/private/Documents/Training Database.CBH"),
            self.SAFE_NAME,
        )
        self.assertEqual(
            report_safe_path_name(r"mixed/root\private/Training Database.CBH"),
            self.SAFE_NAME,
        )

    def test_all_chessbase_serialized_sinks_share_safe_filename_semantics(self) -> None:
        adapter = probe_chessbase_source(self.WINDOWS_PRIVATE_PATH).as_report_fields()
        evidence = SourceFileEvidence(
            path=Path(self.WINDOWS_PRIVATE_PATH),
            extension=".cbh",
            role="primary_source",
            size_bytes=1,
            sha256="0" * 64,
        )
        integrity = ChessBaseIntegritySnapshot(
            primary_path=Path(self.WINDOWS_PRIVATE_PATH),
            files=(evidence,),
        ).as_report_fields()
        component = ComponentEvidence(
            path=self.WINDOWS_PRIVATE_PATH,
            extension=".cbh",
            role="primary database source",
            size=1,
            sha256="0" * 64,
        )
        manifest = ChessBaseBundleManifest(
            schema_version=1,
            primary_path=self.WINDOWS_PRIVATE_PATH,
            source_kind="component_set",
            family_name="ChessBase classic database",
            status="evidence_collected",
            primary=component,
        ).as_dict()

        values = (
            adapter["source_path"],
            integrity["primary_path"],
            integrity["files"][0]["path"],
            manifest["primary_path"],
            manifest["primary"]["path"],
        )
        self.assertEqual(values, (self.SAFE_NAME,) * len(values))
        for value in values:
            self.assertNotIn("PrivateUser", str(value))
            self.assertNotIn("Documents", str(value))

    def test_manifest_verification_problem_does_not_reemit_private_windows_path(self) -> None:
        component = ComponentEvidence(
            path=self.WINDOWS_PRIVATE_PATH,
            extension=".cbh",
            role="primary database source",
            size=1,
            sha256="0" * 64,
        )
        manifest = ChessBaseBundleManifest(
            schema_version=1,
            primary_path=self.WINDOWS_PRIVATE_PATH,
            source_kind="component_set",
            family_name="ChessBase classic database",
            status="evidence_collected",
            primary=component,
        )
        unchanged, problems = verify_manifest_unchanged(manifest)
        self.assertFalse(unchanged)
        self.assertTrue(problems)
        rendered = "\n".join(problems)
        self.assertIn(self.SAFE_NAME, rendered)
        self.assertNotIn("PrivateUser", rendered)
        self.assertNotIn("Documents", rendered)

    def test_no_clobber_temp_cleanup_failure_is_nonfatal_after_atomic_commit(self) -> None:
        games = parse_games('[Event "Committed"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "new.pgn"
            real_unlink = Path.unlink

            def fail_redundant_temp(path: Path, *args, **kwargs):
                if path.name.startswith(destination.name + ".") and path.name.endswith(".tmp"):
                    raise OSError("simulated redundant temp cleanup failure")
                return real_unlink(path, *args, **kwargs)

            with mock.patch("pathlib.Path.unlink", autospec=True, side_effect=fail_redundant_temp):
                result = save_pgn_atomic(destination, games, overwrite=False)

            self.assertTrue(destination.exists())
            self.assertIn("Committed", destination.read_text(encoding="utf-8"))
            self.assertEqual(result.sha256, result.sha256.lower())
            self.assertEqual(len(result.sha256), 64)


if __name__ == "__main__":
    unittest.main()
