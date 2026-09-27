from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
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


def _candidate_bytes(*, tamper: str | None = None, nvda_verified: bool = False) -> bytes:
    payload = {
        "AccessibleChess/AccessibleChess.exe": b"exe",
        "AccessibleChess/engines/stockfish/stockfish.exe": b"stockfish",
        "AccessibleChess/release-content/w2-starter/manifest.json": b"{}",
        "AccessibleChess/release-content/w2-starter/starter_uk.pgn": b"[Event \"Starter\"]\n",
        "AccessibleChess/release-content/w2-starter/stress_uk.pgn": b"[Event \"Stress\"]\n",
        "AccessibleChess/release-content/w2-starter/sample_library.acsdb": b"sqlite-fixture",
        "AccessibleChess/web/index.html": b"<!doctype html>",
    }
    manifest = json.dumps(
        {"integration_sha": SHA, "nvda_verified": nvda_verified}
    ).encode()
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
    candidate_name: str | None = None,
    copy_overrides: dict[str, object] | None = None,
    p0g_overrides: dict[str, object] | None = None,
) -> bytes:
    copy = _copy_evidence(copy_sha, **(copy_overrides or {}))
    p0g = _p0g_evidence(p0g_sha, **(p0g_overrides or {}))
    return _zip_bytes(
        {
            candidate_name or "Accessible-Chess-V2-fffffff-NVDA-test-candidate.zip": candidate or _candidate_bytes(),
            "p0-evidence/packaged-v2-document-copy-summary.json": json.dumps(copy).encode(),
            "p0-evidence/packaged-p0g-hotkey-result-summary.json": json.dumps(p0g).encode(),
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

    def test_manifest_nvda_overclaim_fails(self) -> None:
        self.path.write_bytes(_outer_bytes(candidate=_candidate_bytes(nvda_verified=True)))
        with self.assertRaises(CandidateArtifactError):
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
