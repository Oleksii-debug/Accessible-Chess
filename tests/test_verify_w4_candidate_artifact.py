from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch
import tempfile
import unittest
import zipfile

from scripts.verify_w4_candidate_artifact import CandidateArtifactError, verify


SHA = "f" * 40
STARTER_ROOT = "AccessibleChess/release-content/w2-starter"
STARTER_GAMES = 240
STRESS_GAMES = 1200


def _zip_bytes(
    files: dict[str, bytes],
    *,
    compression: int = zipfile.ZIP_STORED,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _pgn_fixture(prefix: str, count: int) -> bytes:
    return "".join(
        f'[Event "{prefix} {index}"]\n'
        f'[White "White {index}"]\n'
        f'[Black "Black {index}"]\n'
        '[Result "1-0"]\n\n'
        '1. e4 e5 1-0\n\n'
        for index in range(count)
    ).encode("utf-8")


def _database_fixture_bytes(game_count: int = STARTER_GAMES) -> bytes:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE games ("
            "pgn_text TEXT NOT NULL, white TEXT NOT NULL, "
            "black TEXT NOT NULL, event TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO games(pgn_text, white, black, event) VALUES (?, ?, ?, ?)",
            [
                (
                    f"fixture-pgn-{index}",
                    f"White {index}",
                    f"Black {index}",
                    f"Event {index % 5}",
                )
                for index in range(game_count)
            ],
        )
        connection.commit()
        return connection.serialize()
    finally:
        connection.close()


def _starter_bundle_files(*, database_games: int = STARTER_GAMES) -> dict[str, bytes]:
    starter = _pgn_fixture("Starter", STARTER_GAMES)
    stress = _pgn_fixture("Stress", STRESS_GAMES)
    database = _database_fixture_bytes(database_games)
    file_payloads = {
        "starter_uk.pgn": starter,
        "stress_uk.pgn": stress,
        "sample_library.acsdb": database,
    }
    licenses = {
        "starter_uk.pgn": "CC0-1.0",
        "stress_uk.pgn": "LicenseRef-Accessible-Chess-Starter-Content-1.0",
        "sample_library.acsdb": "CC0-1.0",
    }
    selected_games = [
        {
            "source_index": index + 1,
            "record_sha256": hashlib.sha256(f"record-{index}".encode()).hexdigest(),
        }
        for index in range(STARTER_GAMES)
    ]
    manifest = {
        "schema_version": 3,
        "bundle_kind": "lawful-curated-real-game-starter",
        "runtime_network_required": False,
        "starter_source": {
            "name": "lichess-standard-rated-2013-01",
            "url": (
                "https://database.lichess.org/standard/"
                "lichess_db_standard_rated_2013-01.pgn.zst"
            ),
            "license_id": "CC0-1.0",
            "published_games": 121_332,
            "compressed_sha256": (
                "aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635"
            ),
            "compressed_bytes": 1_000_000,
            "selection": "accessible-chess-p0f-real-sample-v1",
            "subset_sha256": hashlib.sha256(starter).hexdigest(),
            "selected_games": STARTER_GAMES,
            "curation": {
                "policy_id": "accessible-chess-p0f-real-sample-v1",
                "parser": "acs.pgn_roundtrip.parse_pgn_text(strict=True)",
                "criteria": {
                    "minimum_plies": 20,
                    "valid_results": ["0-1", "1-0", "1/2-1/2"],
                    "required_metadata": ["Event", "White", "Black"],
                    "result_minimums": {"1-0": 20, "0-1": 20, "1/2-1/2": 8},
                    "length_band_minimums": {"20-59": 20, "60-99": 20, "100+": 8},
                    "minimum_distinct_opening_prefixes": 12,
                    "opening_prefix_plies": 4,
                    "maximum_scanned_games": 5000,
                },
                "selected_games": selected_games,
            },
        },
        "licenses": {
            "CC0-1.0": {
                "type": "public-domain-dedication",
                "url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "source": "Lichess standard database publication",
            },
            "LicenseRef-Accessible-Chess-Starter-Content-1.0": {
                "type": "project-owned-redistribution-grant",
                "terms_uk": "Fixture redistribution terms retained for readback qualification.",
            },
        },
        "counts": {
            "starter_games": STARTER_GAMES,
            "stress_games": STRESS_GAMES,
        },
        "sample_library": {
            "games": STARTER_GAMES,
            "distinct_games": STARTER_GAMES,
            "distinct_player_pairs": STARTER_GAMES,
            "distinct_events": 5,
        },
        "files": {
            name: {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "license_id": licenses[name],
            }
            for name, payload in file_payloads.items()
        },
    }
    result = {
        f"{STARTER_ROOT}/{name}": payload
        for name, payload in file_payloads.items()
    }
    result[f"{STARTER_ROOT}/manifest.json"] = json.dumps(manifest).encode("utf-8")
    return result


def _candidate_bytes(
    *,
    tamper: str | None = None,
    nvda_verified: bool = False,
    human_tested: bool | None = None,
    starter_files: dict[str, bytes] | None = None,
    compression: int = zipfile.ZIP_STORED,
) -> bytes:
    payload = {
        "AccessibleChess/AccessibleChess.exe": b"exe",
        "AccessibleChess/engines/stockfish/stockfish.exe": b"stockfish",
        **(starter_files or _starter_bundle_files()),
        "AccessibleChess/web/index.html": b"<!doctype html>",
    }
    manifest_payload: dict[str, object] = {
        "integration_sha": SHA,
        "nvda_verified": nvda_verified,
    }
    if human_tested is not None:
        manifest_payload["human_tested"] = human_tested
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
    return _zip_bytes(files, compression=compression)



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

    def test_outer_size_bound_fails_before_reading_bytes(self) -> None:
        oversized = Path(self.temp.name) / "oversized.zip"
        oversized.write_bytes(b"x" * 16)
        with patch("scripts.verify_w4_candidate_artifact.MAX_OUTER_BYTES", 8):
            with patch.object(Path, "read_bytes", side_effect=AssertionError("must not read")):
                with self.assertRaisesRegex(CandidateArtifactError, "outer artifact size"):
                    verify(oversized, SHA)

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

    def test_inner_total_uncompressed_bound_fails_before_member_readback(self) -> None:
        with patch(
            "scripts.verify_w4_candidate_artifact.MAX_INNER_UNCOMPRESSED_BYTES",
            32,
        ):
            with self.assertRaisesRegex(
                CandidateArtifactError,
                "total uncompressed byte limit",
            ):
                verify(self.path, SHA)

    def test_inner_compression_ratio_bound_fails_closed(self) -> None:
        self.path.write_bytes(
            _outer_bytes(candidate=_candidate_bytes(compression=zipfile.ZIP_DEFLATED))
        )
        with patch(
            "scripts.verify_w4_candidate_artifact.MAX_INNER_COMPRESSION_RATIO",
            1,
        ):
            with self.assertRaisesRegex(CandidateArtifactError, "compression-ratio limit"):
                verify(self.path, SHA)

    def test_lawful_starter_source_authority_is_verified_semantically(self) -> None:
        starter = _starter_bundle_files()
        manifest_path = f"{STARTER_ROOT}/manifest.json"
        manifest = json.loads(starter[manifest_path])
        manifest["starter_source"]["license_id"] = "LicenseRef-Unverified"
        starter[manifest_path] = json.dumps(manifest).encode("utf-8")
        self.path.write_bytes(
            _outer_bytes(candidate=_candidate_bytes(starter_files=starter))
        )
        with self.assertRaisesRegex(CandidateArtifactError, "source authority mismatch"):
            verify(self.path, SHA)

    def test_lawful_starter_file_metadata_is_bound_to_real_bytes(self) -> None:
        starter = _starter_bundle_files()
        manifest_path = f"{STARTER_ROOT}/manifest.json"
        manifest = json.loads(starter[manifest_path])
        manifest["files"]["starter_uk.pgn"]["sha256"] = "0" * 64
        starter[manifest_path] = json.dumps(manifest).encode("utf-8")
        self.path.write_bytes(
            _outer_bytes(candidate=_candidate_bytes(starter_files=starter))
        )
        with self.assertRaisesRegex(CandidateArtifactError, "starter file SHA-256 mismatch"):
            verify(self.path, SHA)

    def test_lawful_starter_database_claim_is_verified_against_sqlite(self) -> None:
        starter = _starter_bundle_files(database_games=STARTER_GAMES - 1)
        self.path.write_bytes(
            _outer_bytes(candidate=_candidate_bytes(starter_files=starter))
        )
        with self.assertRaisesRegex(CandidateArtifactError, "ACSDB semantic evidence mismatch"):
            verify(self.path, SHA)

    def test_lawful_starter_pgn_counts_are_verified_after_readback(self) -> None:
        starter = _starter_bundle_files()
        manifest_path = f"{STARTER_ROOT}/manifest.json"
        starter_name = f"{STARTER_ROOT}/starter_uk.pgn"
        starter[starter_name] = starter[starter_name].replace(
            b'[Event "Starter 239"]',
            b'[Site "Starter 239"]',
            1,
        )
        manifest = json.loads(starter[manifest_path])
        manifest["files"]["starter_uk.pgn"]["sha256"] = hashlib.sha256(
            starter[starter_name]
        ).hexdigest()
        manifest["files"]["starter_uk.pgn"]["bytes"] = len(starter[starter_name])
        manifest["starter_source"]["subset_sha256"] = hashlib.sha256(
            starter[starter_name]
        ).hexdigest()
        starter[manifest_path] = json.dumps(manifest).encode("utf-8")
        self.path.write_bytes(
            _outer_bytes(candidate=_candidate_bytes(starter_files=starter))
        )
        with self.assertRaisesRegex(CandidateArtifactError, "complete-record count mismatch"):
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
