from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest
import zipfile

from scripts.verify_w4_candidate_artifact import CandidateArtifactError, verify


SHA = "f" * 40


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _candidate_bytes(
    *,
    tamper: str | None = None,
    nvda_verified: bool = False,
    human_tested: bool = False,
) -> bytes:
    payload = {
        "AccessibleChess/AccessibleChess.exe": b"exe",
        "AccessibleChess/engines/stockfish/stockfish.exe": b"stockfish",
        "AccessibleChess/release-content/w2-starter/manifest.json": b"{}",
        "AccessibleChess/release-content/w2-starter/starter_uk.pgn": b"[Event \"Starter\"]\n",
        "AccessibleChess/release-content/w2-starter/stress_uk.pgn": b"[Event \"Stress\"]\n",
        "AccessibleChess/release-content/w2-starter/sample_library.acsdb": b"sqlite-fixture",
        "AccessibleChess/web/index.html": b"<!doctype html>",
    }
    manifest_payload: dict[str, object] = {
        "integration_sha": SHA,
        "human_tested": human_tested,
        "nvda_verified": nvda_verified,
    }
    manifest = json.dumps(manifest_payload).encode()
    checksummed = dict(payload)
    checksummed["RELEASE_MANIFEST.json"] = manifest
    checksums = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        for name, data in sorted(checksummed.items())
    )
    files = dict(checksummed)
    files["SHA256SUMS.txt"] = checksums.encode()
    if tamper is not None:
        files[tamper] = b"tampered"
    return _zip_bytes(files)



def _copy_evidence(product_sha: str = SHA, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "product_sha": product_sha,
        "static_document_outside_edit": True,
        "native_copy_focus_verified": True,
        "foreground_product_verified": True,
        "manifest_product_sha_verified": True,
        "executable_checksum_verified": True,
        "textpattern_selection_supported": True,
        "ctrl_c_exact_clipboard": True,
        "move_input_focus_verified": True,
        "move_input_native_ctrl_a_ctrl_c": True,
        "static_document_text": "Інформація про гру",
        "clipboard_equality": "case-sensitive exact string equality",
        "human_tested": False,
        "nvda_verified": False,
    }
    value.update(overrides)
    return value


def _strict_uia_evidence(product_sha: str = SHA, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "product_sha": product_sha,
        "classification": "A",
        "evidence_complete": True,
        "move_runtime_id": "42.17.3",
        "e4_fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        "invalid_e9_fen_unchanged": True,
        "clipboard": "e9",
        "semantic_square_count": 64,
        "board_focus_continuity": True,
        "black_e5_fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
        "raw_exception_noise": False,
    }
    value.update(overrides)
    return value


def _p0g_evidence(product_sha: str = SHA, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "product_sha": product_sha,
        "native_keyboard_dispatch": True,
        "foreground_product_verified": True,
        "manifest_product_sha_verified": True,
        "executable_checksum_verified": True,
        "alt_1_action_occurred": True,
        "alt_1_accessible_result_exposed": True,
        "alt_2_action_occurred": True,
        "alt_2_accessible_result_exposed": True,
        "board_application_entered": False,
        "raw_uci_or_debug_exposed": False,
        "alt_1_precondition_selected_state": "Variant 2 selected",
        "alt_1_selected_state": "Variant 1 selected",
        "alt_1_result": "Variant 1 depth 12 eval +0.30",
        "alt_2_precondition_selected_state": "Variant 1 selected",
        "alt_2_selected_state": "Variant 2 selected",
        "alt_2_result": "Variant 2 depth 12 eval +0.10",
        "human_tested": False,
        "nvda_verified": False,
    }
    value.update(overrides)
    return value


def _outer_bytes(
    *,
    candidate: bytes | None = None,
    copy_sha: str = SHA,
    p0g_sha: str = SHA,
    uia_sha: str = SHA,
    candidate_name: str | None = None,
    copy_overrides: dict[str, object] | None = None,
    p0g_overrides: dict[str, object] | None = None,
    uia_overrides: dict[str, object] | None = None,
) -> bytes:
    copy = _copy_evidence(copy_sha, **(copy_overrides or {}))
    p0g = _p0g_evidence(p0g_sha, **(p0g_overrides or {}))
    uia = _strict_uia_evidence(uia_sha, **(uia_overrides or {}))
    return _zip_bytes(
        {
            candidate_name or "Accessible-Chess-V2-fffffff-NVDA-test-candidate.zip": candidate or _candidate_bytes(),
            "p0-evidence/packaged-v2-document-copy-summary.json": json.dumps(copy).encode(),
            "p0-evidence/packaged-p0g-hotkey-result-summary.json": json.dumps(p0g).encode(),
            "p0-evidence/packaged-uia-strict-summary.json": json.dumps(uia).encode(),
        }
    )


class VerifyW4CandidateArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "artifact.zip"
        self.path.write_bytes(_outer_bytes())

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_complete_artifact_passes(self) -> None:
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        verify(self.path, SHA, digest)

    def test_prefixed_outer_digest_passes(self) -> None:
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        verify(self.path, SHA, f"sha256:{digest}")

    def test_outer_size_bound_fails_before_reading_bytes(self) -> None:
        oversized = Path(self.temp.name) / "oversized.zip"
        oversized.write_bytes(b"x" * 16)
        with patch("scripts.verify_w4_candidate_artifact.MAX_OUTER_BYTES", 8):
            with patch.object(Path, "read_bytes", side_effect=AssertionError("must not read")):
                with self.assertRaisesRegex(CandidateArtifactError, "outer artifact size"):
                    verify(oversized, SHA)

    def test_outer_uncompressed_size_bound_fails_before_member_reads(self) -> None:
        with patch("scripts.verify_w4_candidate_artifact.MAX_OUTER_UNCOMPRESSED_BYTES", 8):
            with patch.object(zipfile.ZipFile, "read", side_effect=AssertionError("must not decompress")):
                with self.assertRaisesRegex(CandidateArtifactError, "outer artifact uncompressed size"):
                    verify(self.path, SHA)

    def test_evidence_size_bound_fails_before_evidence_read(self) -> None:
        original_read = zipfile.ZipFile.read

        def guarded_read(archive, name, *args, **kwargs):
            if str(name).endswith(".json"):
                raise AssertionError("oversized evidence must not be decompressed")
            return original_read(archive, name, *args, **kwargs)

        with patch("scripts.verify_w4_candidate_artifact.MAX_EVIDENCE_BYTES", 8):
            with patch.object(zipfile.ZipFile, "read", new=guarded_read):
                with self.assertRaisesRegex(CandidateArtifactError, "outer evidence JSON size"):
                    verify(self.path, SHA)

    def test_inner_zip_size_bound_fails_before_decompression(self) -> None:
        original_read = zipfile.ZipFile.read

        def guarded_read(archive, name, *args, **kwargs):
            if str(name).endswith("-NVDA-test-candidate.zip"):
                raise AssertionError("oversized candidate must not be decompressed")
            return original_read(archive, name, *args, **kwargs)

        with patch("scripts.verify_w4_candidate_artifact.MAX_INNER_BYTES", 8):
            with patch.object(zipfile.ZipFile, "read", new=guarded_read):
                with self.assertRaisesRegex(CandidateArtifactError, "candidate ZIP size"):
                    verify(self.path, SHA)

    def test_candidate_metadata_size_bound_fails_before_metadata_read(self) -> None:
        original_read = zipfile.ZipFile.read

        def guarded_read(archive, name, *args, **kwargs):
            normalized = str(name).replace("\\", "/")
            if normalized in {"RELEASE_MANIFEST.json", "SHA256SUMS.txt"}:
                raise AssertionError("oversized candidate metadata must not be read")
            return original_read(archive, name, *args, **kwargs)

        with patch("scripts.verify_w4_candidate_artifact.MAX_CANDIDATE_METADATA_BYTES", 8):
            with patch.object(zipfile.ZipFile, "read", new=guarded_read):
                with self.assertRaisesRegex(CandidateArtifactError, "candidate metadata size"):
                    verify(self.path, SHA)

    def test_candidate_uncompressed_size_bound_fails_before_member_reads(self) -> None:
        original_read = zipfile.ZipFile.read

        def guarded_read(archive, name, *args, **kwargs):
            normalized = str(name).replace("\\", "/")
            if normalized == "RELEASE_MANIFEST.json" or normalized == "SHA256SUMS.txt" or normalized.startswith("AccessibleChess/"):
                raise AssertionError("oversized candidate member must not be read")
            return original_read(archive, name, *args, **kwargs)

        with patch("scripts.verify_w4_candidate_artifact.MAX_CANDIDATE_UNCOMPRESSED_BYTES", 8):
            with patch.object(zipfile.ZipFile, "read", new=guarded_read):
                with self.assertRaisesRegex(CandidateArtifactError, "candidate ZIP uncompressed size"):
                    verify(self.path, SHA)

    def test_payload_checksum_hashing_is_streamed_not_read_whole(self) -> None:
        original_read = zipfile.ZipFile.read

        def guarded_read(archive, name, *args, **kwargs):
            if str(name).replace("\\", "/") == "AccessibleChess/AccessibleChess.exe":
                raise AssertionError("package payload must be streamed while hashing")
            return original_read(archive, name, *args, **kwargs)

        with patch.object(zipfile.ZipFile, "read", new=guarded_read):
            verify(self.path, SHA)

    def test_wrong_outer_digest_fails(self) -> None:
        with self.assertRaises(CandidateArtifactError):
            verify(self.path, SHA, "0" * 64)

    def test_malformed_prefixed_digest_fails(self) -> None:
        with self.assertRaises(CandidateArtifactError):
            verify(self.path, SHA, "sha256:xyz")


    def test_wrong_candidate_filename_product_prefix_fails(self) -> None:
        self.path.write_bytes(
            _outer_bytes(candidate_name="Accessible-Chess-V2-1234567-NVDA-test-candidate.zip")
        )
        with self.assertRaisesRegex(CandidateArtifactError, "filename Product prefix mismatch"):
            verify(self.path, SHA)



    def test_strict_uia_evidence_is_required_and_sha_bound(self) -> None:
        self.path.write_bytes(_outer_bytes(uia_sha="1" * 40))
        with self.assertRaisesRegex(CandidateArtifactError, "strict UIA evidence product_sha mismatch"):
            verify(self.path, SHA)

    def test_strict_uia_evidence_requires_classification_a(self) -> None:
        self.path.write_bytes(_outer_bytes(uia_overrides={"classification": "C"}))
        with self.assertRaisesRegex(CandidateArtifactError, "classification must be A"):
            verify(self.path, SHA)

    def test_strict_uia_evidence_requires_64_squares_and_board_focus(self) -> None:
        self.path.write_bytes(
            _outer_bytes(
                uia_overrides={
                    "semantic_square_count": 63,
                    "board_focus_continuity": False,
                }
            )
        )
        with self.assertRaises(CandidateArtifactError):
            verify(self.path, SHA)

    def test_strict_uia_evidence_requires_native_clipboard_and_canonical_fens(self) -> None:
        for overrides in (
            {"clipboard": "sentinel"},
            {"e4_fen": "8/8/8/8/8/8/8/8 w - - 0 1"},
            {"black_e5_fen": "8/8/8/8/8/8/8/8 w - - 0 1"},
        ):
            self.path.write_bytes(_outer_bytes(uia_overrides=overrides))
            with self.assertRaises(CandidateArtifactError):
                verify(self.path, SHA)

    def test_copy_evidence_requires_exact_clipboard_payload(self) -> None:
        self.path.write_bytes(
            _outer_bytes(copy_overrides={"clipboard_equality": "normalized equality"})
        )
        with self.assertRaisesRegex(CandidateArtifactError, "clipboard equality"):
            verify(self.path, SHA)

    def test_p0g_evidence_requires_distinct_accessible_results(self) -> None:
        same = "Variant 1 depth 12 eval +0.30"
        self.path.write_bytes(
            _outer_bytes(
                p0g_overrides={
                    "alt_2_result": same,
                    "alt_2_selected_state": "Variant 1 selected",
                }
            )
        )
        with self.assertRaises(CandidateArtifactError):
            verify(self.path, SHA)

    def test_copy_evidence_requires_native_move_input_copy_proof(self) -> None:
        self.path.write_bytes(
            _outer_bytes(copy_overrides={"move_input_native_ctrl_a_ctrl_c": False})
        )
        with self.assertRaisesRegex(CandidateArtifactError, "move_input_native_ctrl_a_ctrl_c"):
            verify(self.path, SHA)

    def test_p0g_evidence_requires_both_accessible_hotkey_results(self) -> None:
        self.path.write_bytes(
            _outer_bytes(p0g_overrides={"alt_2_accessible_result_exposed": False})
        )
        with self.assertRaisesRegex(CandidateArtifactError, "alt_2_accessible_result_exposed"):
            verify(self.path, SHA)

    def test_p0g_evidence_requires_board_application_to_remain_false(self) -> None:
        self.path.write_bytes(
            _outer_bytes(p0g_overrides={"board_application_entered": True})
        )
        with self.assertRaisesRegex(CandidateArtifactError, "board_application_entered"):
            verify(self.path, SHA)

    def test_wrong_evidence_sha_fails(self) -> None:
        self.path.write_bytes(_outer_bytes(copy_sha="1" * 40))
        with self.assertRaises(CandidateArtifactError):
            verify(self.path, SHA)

    def test_missing_p0g_evidence_fails(self) -> None:
        outer = _zip_bytes(
            {
                "Accessible-Chess-V2-fffffff-NVDA-test-candidate.zip": _candidate_bytes(),
                "p0-evidence/packaged-v2-document-copy-summary.json": json.dumps(
                    {"product_sha": SHA, "human_tested": False, "nvda_verified": False}
                ).encode(),
            }
        )
        self.path.write_bytes(outer)
        with self.assertRaises(CandidateArtifactError):
            verify(self.path, SHA)


    def test_missing_strict_uia_evidence_fails(self) -> None:
        outer = _zip_bytes(
            {
                "Accessible-Chess-V2-fffffff-NVDA-test-candidate.zip": _candidate_bytes(),
                "p0-evidence/packaged-v2-document-copy-summary.json": json.dumps(
                    _copy_evidence()
                ).encode(),
                "p0-evidence/packaged-p0g-hotkey-result-summary.json": json.dumps(
                    _p0g_evidence()
                ).encode(),
            }
        )
        self.path.write_bytes(outer)
        with self.assertRaisesRegex(CandidateArtifactError, "strict UIA"):
            verify(self.path, SHA)

    def test_unexpected_outer_file_fails(self) -> None:
        outer = _zip_bytes(
            {
                "Accessible-Chess-V2-fffffff-NVDA-test-candidate.zip": _candidate_bytes(),
                "p0-evidence/packaged-v2-document-copy-summary.json": json.dumps(
                    {"product_sha": SHA, "human_tested": False, "nvda_verified": False}
                ).encode(),
                "p0-evidence/packaged-p0g-hotkey-result-summary.json": json.dumps(
                    {"product_sha": SHA, "human_tested": False, "nvda_verified": False}
                ).encode(),
                "p0-evidence/packaged-uia-strict-summary.json": json.dumps(
                    _strict_uia_evidence()
                ).encode(),
                "unexpected.bin": b"not part of canonical candidate artifact",
            }
        )
        self.path.write_bytes(outer)
        with self.assertRaisesRegex(CandidateArtifactError, "unexpected files"):
            verify(self.path, SHA)

    def test_candidate_payload_tamper_fails(self) -> None:
        self.path.write_bytes(
            _outer_bytes(candidate=_candidate_bytes(tamper="AccessibleChess/AccessibleChess.exe"))
        )
        with self.assertRaises(CandidateArtifactError):
            verify(self.path, SHA)

    def test_missing_release_critical_p0f_file_fails(self) -> None:
        candidate = _candidate_bytes()
        with zipfile.ZipFile(io.BytesIO(candidate), "r") as archive:
            files = {
                name: archive.read(name)
                for name in archive.namelist()
                if name != "AccessibleChess/release-content/w2-starter/sample_library.acsdb"
            }
        self.path.write_bytes(_outer_bytes(candidate=_zip_bytes(files)))
        with self.assertRaises(CandidateArtifactError):
            verify(self.path, SHA)

    def test_manifest_missing_human_acceptance_flag_fails_closed(self) -> None:
        candidate = _candidate_bytes()
        with zipfile.ZipFile(io.BytesIO(candidate), "r") as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(files["RELEASE_MANIFEST.json"])
        del manifest["human_tested"]
        files["RELEASE_MANIFEST.json"] = json.dumps(manifest).encode()
        checksummed = {
            name: payload
            for name, payload in files.items()
            if name != "SHA256SUMS.txt"
        }
        files["SHA256SUMS.txt"] = "".join(
            f"{hashlib.sha256(payload).hexdigest()}  {name}\n"
            for name, payload in sorted(checksummed.items())
        ).encode()
        self.path.write_bytes(_outer_bytes(candidate=_zip_bytes(files)))
        with self.assertRaisesRegex(CandidateArtifactError, "human_tested"):
            verify(self.path, SHA)

    def test_manifest_non_boolean_nvda_acceptance_flag_fails_closed(self) -> None:
        candidate = _candidate_bytes()
        with zipfile.ZipFile(io.BytesIO(candidate), "r") as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(files["RELEASE_MANIFEST.json"])
        manifest["nvda_verified"] = "no"
        files["RELEASE_MANIFEST.json"] = json.dumps(manifest).encode()
        checksummed = {
            name: payload
            for name, payload in files.items()
            if name != "SHA256SUMS.txt"
        }
        files["SHA256SUMS.txt"] = "".join(
            f"{hashlib.sha256(payload).hexdigest()}  {name}\n"
            for name, payload in sorted(checksummed.items())
        ).encode()
        self.path.write_bytes(_outer_bytes(candidate=_zip_bytes(files)))
        with self.assertRaisesRegex(CandidateArtifactError, "nvda_verified"):
            verify(self.path, SHA)

    def test_manifest_nvda_overclaim_fails(self) -> None:
        self.path.write_bytes(_outer_bytes(candidate=_candidate_bytes(nvda_verified=True)))
        with self.assertRaises(CandidateArtifactError):
            verify(self.path, SHA)

    def test_manifest_human_overclaim_fails(self) -> None:
        self.path.write_bytes(_outer_bytes(candidate=_candidate_bytes(human_tested=True)))
        with self.assertRaisesRegex(CandidateArtifactError, "human/NVDA acceptance claim"):
            verify(self.path, SHA)

    def test_evidence_human_overclaim_fails(self) -> None:
        outer = _zip_bytes(
            {
                "Accessible-Chess-V2-fffffff-NVDA-test-candidate.zip": _candidate_bytes(),
                "p0-evidence/packaged-v2-document-copy-summary.json": json.dumps(
                    {"product_sha": SHA, "human_tested": True, "nvda_verified": False}
                ).encode(),
                "p0-evidence/packaged-p0g-hotkey-result-summary.json": json.dumps(
                    {"product_sha": SHA, "human_tested": False, "nvda_verified": False}
                ).encode(),
                "p0-evidence/packaged-uia-strict-summary.json": json.dumps(
                    _strict_uia_evidence()
                ).encode(),
            }
        )
        self.path.write_bytes(outer)
        with self.assertRaises(CandidateArtifactError):
            verify(self.path, SHA)

    def test_duplicate_outer_path_casefold_fails(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("A.json", b"{}")
            archive.writestr("a.json", b"{}")
        self.path.write_bytes(buffer.getvalue())
        with self.assertRaises(CandidateArtifactError):
            verify(self.path, SHA)


if __name__ == "__main__":
    unittest.main()
