from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sqlite3
import stat
from unittest.mock import patch
import tempfile
import unittest
import zipfile

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.gametree import serialize_game
from acs.pgn_roundtrip import parse_pgn_text
from scripts.verify_w4_candidate_artifact import (
    CandidateArtifactError,
    MAX_CANDIDATE_METADATA_BYTES,
    verify,
)


SHA = "f" * 40
WORKFLOW_SHA = "a" * 40
WINFORMS_CONFIG = b'<?xml version="1.0" encoding="utf-8"?>\n<configuration />\n'
WINFORMS_CONFIG_SHA256 = hashlib.sha256(WINFORMS_CONFIG).hexdigest()
STARTER_ROOT = "AccessibleChess/release-content/w2-starter"
STARTER_GAMES = 240
STRESS_GAMES = 1200


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _pe_fixture(marker: bytes) -> bytes:
    payload = bytearray(128 + len(marker))
    payload[:2] = b"MZ"
    payload[60:64] = (64).to_bytes(4, "little")
    payload[64:68] = b"PE\x00\x00"
    payload[68:68 + len(marker)] = marker
    return bytes(payload)


_OPENING_PREFIXES = (
    ("e4", "e5", "Nf3", "Nc6"),
    ("d4", "d5", "c4", "e6"),
    ("c4", "e5", "Nc3", "Nf6"),
    ("Nf3", "d5", "g3", "c5"),
    ("b3", "e5", "Bb2", "Nc6"),
    ("g3", "d5", "Bg2", "e5"),
    ("f4", "d5", "Nf3", "Nf6"),
    ("a3", "e5", "b4", "d5"),
    ("h3", "d5", "g4", "e5"),
    ("e3", "d5", "b3", "e5"),
    ("d3", "e5", "Nd2", "Nf6"),
    ("c3", "d5", "Qc2", "e5"),
)


def _result_for_index(index: int) -> str:
    return "0-1" if index < 20 else ("1/2-1/2" if index < 28 else "1-0")


def _plies_for_index(index: int) -> int:
    return 40 if index < 20 else (80 if index < 40 else 120)


def _opening_for_index(index: int) -> tuple[str, ...]:
    return _OPENING_PREFIXES[index % len(_OPENING_PREFIXES)]


def _pgn_record(prefix: str, index: int) -> str:
    result = _result_for_index(index)
    plies = _plies_for_index(index)
    moves = list(_opening_for_index(index))
    filler = ("a3", "a6", "h3", "h6")
    while len(moves) < plies:
        moves.append(filler[(len(moves) - 4) % len(filler)])
    movetext: list[str] = []
    for ply in range(0, len(moves), 2):
        move_number = (ply // 2) + 1
        movetext.append(f"{move_number}. {moves[ply]} {moves[ply + 1]}")
    return (
        f'[Event "{prefix} {index}"]\n'
        f'[White "White {index}"]\n'
        f'[Black "Black {index}"]\n'
        f'[Result "{result}"]\n\n'
        + " ".join(movetext)
        + f" {result}"
    )


def _pgn_fixture(prefix: str, count: int) -> bytes:
    return ("\n\n".join(_pgn_record(prefix, index) for index in range(count)) + "\n\n").encode(
        "utf-8"
    )


def _database_fixture_bytes(
    game_count: int = STARTER_GAMES,
    *,
    schema_version: int = ACSDB_SCHEMA_VERSION,
    first_white: str | None = None,
    first_pgn_text: str | None = None,
    first_source_index: int | None = None,
    source_sha256: str = "0" * 64,
) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "starter-fixture.acsdb"
        with AcsDatabase(path) as database:
            with database.conn:
                source = database.conn.execute(
                    "INSERT INTO sources(source_name, source_format, sha256, imported_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        "accessible-chess-starter-uk.pgn",
                        "pgn",
                        source_sha256,
                        "2026-09-11T00:00:00+00:00",
                    ),
                )
                source_id = int(source.lastrowid)
                for index in range(game_count):
                    database.conn.execute(
                        "INSERT INTO games("
                        "source_id, source_index, import_status, warnings_json, "
                        "event, site, game_date, round, white, black, result, "
                        "eco, opening, start_fen, pgn_text"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            source_id,
                            (
                                first_source_index
                                if index == 0 and first_source_index is not None
                                else index
                            ),
                            "full",
                            "[]",
                            f"Starter {index}",
                            None,
                            None,
                            None,
                            (
                                first_white
                                if index == 0 and first_white is not None
                                else f"White {index}"
                            ),
                            f"Black {index}",
                            _result_for_index(index),
                            None,
                            None,
                            None,
                            (
                                first_pgn_text
                                if index == 0 and first_pgn_text is not None
                                else serialize_game(
                                    parse_pgn_text(_pgn_record("Starter", index), strict=True)[0]
                                )
                            ),
                        ),
                    )
            database.verify_integrity()

        if schema_version != ACSDB_SCHEMA_VERSION:
            connection = sqlite3.connect(path)
            try:
                connection.execute(f"PRAGMA user_version = {schema_version}")
                connection.commit()
            finally:
                connection.close()
        return path.read_bytes()


def _selected_game_fixture(index: int) -> dict[str, object]:
    result = _result_for_index(index)
    plies = _plies_for_index(index)
    return {
        "source_index": index + 1,
        "event": f"Starter {index}",
        "white": f"White {index}",
        "black": f"Black {index}",
        "result": result,
        "plies": plies,
        "length_band": "20-59" if plies < 60 else ("60-99" if plies < 100 else "100+"),
        "opening_prefix": list(_opening_for_index(index)),
        "record_sha256": hashlib.sha256(
            _pgn_record("Starter", index).encode("utf-8")
        ).hexdigest(),
    }


def _starter_bundle_files(
    *,
    database_games: int = STARTER_GAMES,
    database_schema: int = 6,
    database_first_white: str | None = None,
    database_first_pgn_text: str | None = None,
    database_first_source_index: int | None = None,
    database_source_sha256: str | None = None,
) -> dict[str, bytes]:
    starter = _pgn_fixture("Starter", STARTER_GAMES)
    stress = _pgn_fixture("Stress", STRESS_GAMES)
    starter_sha256 = hashlib.sha256(starter).hexdigest()
    database = _database_fixture_bytes(
        database_games,
        schema_version=database_schema,
        first_white=database_first_white,
        first_pgn_text=database_first_pgn_text,
        first_source_index=database_first_source_index,
        source_sha256=database_source_sha256 or starter_sha256,
    )
    selected = [_selected_game_fixture(index) for index in range(STARTER_GAMES)]
    result_counts: dict[str, int] = {}
    length_counts: dict[str, int] = {}
    openings: set[tuple[str, ...]] = set()
    for item in selected:
        result = str(item["result"])
        band = str(item["length_band"])
        result_counts[result] = result_counts.get(result, 0) + 1
        length_counts[band] = length_counts.get(band, 0) + 1
        openings.add(tuple(item["opening_prefix"]))

    payloads = {
        "starter_uk.pgn": starter,
        "stress_uk.pgn": stress,
        "sample_library.acsdb": database,
    }
    license_ids = {
        "starter_uk.pgn": "CC0-1.0",
        "stress_uk.pgn": "LicenseRef-Accessible-Chess-Starter-Content-1.0",
        "sample_library.acsdb": "CC0-1.0",
    }
    manifest = {
        "schema_version": 3,
        "bundle_kind": "lawful-curated-real-game-starter",
        "runtime_network_required": False,
        "starter_source": {
            "name": "lichess-standard-rated-2013-01",
            "url": "https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst",
            "license_id": "CC0-1.0",
            "published_games": 121_332,
            "compressed_sha256": "aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635",
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
                "scanned_records": 300,
                "eligible_records": 260,
                "rejected_records": {"too_short": 40},
                "selected_games": selected,
                "selected_result_counts": dict(sorted(result_counts.items())),
                "selected_length_band_counts": dict(sorted(length_counts.items())),
                "distinct_opening_prefixes": len(openings),
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
                "terms_uk": "Fixture redistribution terms retained for W4 semantic readback.",
            },
        },
        "counts": {"starter_games": STARTER_GAMES, "stress_games": STRESS_GAMES},
        "sample_library": {
            "games": STARTER_GAMES,
            "distinct_games": STARTER_GAMES,
            "distinct_player_pairs": STARTER_GAMES,
            "distinct_events": STARTER_GAMES if database_games == STARTER_GAMES else database_games,
        },
        "files": {
            name: {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "license_id": license_ids[name],
            }
            for name, payload in payloads.items()
        },
    }
    result = {f"{STARTER_ROOT}/{name}": payload for name, payload in payloads.items()}
    result[f"{STARTER_ROOT}/manifest.json"] = json.dumps(manifest).encode("utf-8")
    return result


def _candidate_bytes(
    *,
    tamper: str | None = None,
    nvda_verified: bool = False,
    human_tested: bool = False,
    starter_files: dict[str, bytes] | None = None,
    app_executable: bytes | None = None,
    app_config: bytes | None = None,
    stockfish_executable: bytes | None = None,
) -> bytes:
    payload = {
        "AccessibleChess/AccessibleChess.exe": (
            _pe_fixture(b"app") if app_executable is None else app_executable
        ),
        "AccessibleChess/AccessibleChess.exe.config": (
            WINFORMS_CONFIG if app_config is None else app_config
        ),
        "AccessibleChess/engines/stockfish/stockfish.exe": (
            _pe_fixture(b"stockfish") if stockfish_executable is None else stockfish_executable
        ),
        **(starter_files or _starter_bundle_files()),
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
        "static_text_visible_rectangle": True,
        "native_copy_focus_verified": True,
        "foreground_product_verified": True,
        "manifest_product_sha_verified": True,
        "executable_checksum_verified": True,
        "textpattern_selection_supported": True,
        "textpattern_target_selected": True,
        "textpattern_selection_equality": "UIA exact range endpoints and case-sensitive text equality",
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


def _run_metadata(
    product_sha: str = SHA,
    workflow_sha: str = WORKFLOW_SHA,
    **overrides: object,
) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "product_sha": product_sha,
        "workflow_sha": workflow_sha,
        "winforms_accessibility_config_sha256": WINFORMS_CONFIG_SHA256,
        "pre_upload_product_freshness": True,
        "pre_upload_workflow_freshness": True,
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
    metadata_product_sha: str = SHA,
    metadata_workflow_sha: str = WORKFLOW_SHA,
    metadata_overrides: dict[str, object] | None = None,
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
            "p0-evidence/w4-run-metadata.json": json.dumps(
                _run_metadata(
                    metadata_product_sha,
                    metadata_workflow_sha,
                    **(metadata_overrides or {}),
                )
            ).encode(),
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
        verify(self.path, SHA, digest, WORKFLOW_SHA)

    def test_run_metadata_product_identity_is_required(self) -> None:
        self.path.write_bytes(_outer_bytes(metadata_product_sha="b" * 40))
        with self.assertRaisesRegex(CandidateArtifactError, "run metadata product_sha mismatch"):
            verify(self.path, SHA, expected_workflow_sha=WORKFLOW_SHA)

    def test_run_metadata_workflow_identity_is_required(self) -> None:
        self.path.write_bytes(_outer_bytes(metadata_workflow_sha="b" * 40))
        with self.assertRaisesRegex(CandidateArtifactError, "run metadata workflow_sha mismatch"):
            verify(self.path, SHA, expected_workflow_sha=WORKFLOW_SHA)

    def test_run_metadata_config_digest_must_be_lowercase_sha256(self) -> None:
        self.path.write_bytes(
            _outer_bytes(
                metadata_overrides={"winforms_accessibility_config_sha256": "not-a-digest"}
            )
        )
        with self.assertRaisesRegex(
            CandidateArtifactError,
            "winforms_accessibility_config_sha256 must be lowercase exact 64-hex",
        ):
            verify(self.path, SHA, expected_workflow_sha=WORKFLOW_SHA)

    def test_run_metadata_config_digest_must_match_packaged_config(self) -> None:
        self.path.write_bytes(
            _outer_bytes(
                metadata_overrides={"winforms_accessibility_config_sha256": "b" * 64}
            )
        )
        with self.assertRaisesRegex(
            CandidateArtifactError,
            "WinForms accessibility app-config SHA-256 mismatch",
        ):
            verify(self.path, SHA, expected_workflow_sha=WORKFLOW_SHA)

    def test_candidate_requires_winforms_accessibility_config(self) -> None:
        with zipfile.ZipFile(io.BytesIO(_candidate_bytes()), "r") as archive:
            files = {
                name: archive.read(name)
                for name in archive.namelist()
                if name != "AccessibleChess/AccessibleChess.exe.config"
            }
        self.path.write_bytes(_outer_bytes(candidate=_zip_bytes(files)))
        with self.assertRaisesRegex(CandidateArtifactError, "missing release-critical files"):
            verify(self.path, SHA, expected_workflow_sha=WORKFLOW_SHA)

    def test_self_consistent_config_tamper_still_fails_metadata_authority(self) -> None:
        with zipfile.ZipFile(io.BytesIO(_candidate_bytes()), "r") as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        files["AccessibleChess/AccessibleChess.exe.config"] = b"<configuration><tampered /></configuration>\n"
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
        with self.assertRaisesRegex(
            CandidateArtifactError,
            "WinForms accessibility app-config SHA-256 mismatch",
        ):
            verify(self.path, SHA, expected_workflow_sha=WORKFLOW_SHA)

    def test_run_metadata_requires_both_pre_upload_freshness_proofs(self) -> None:
        for key in ("pre_upload_product_freshness", "pre_upload_workflow_freshness"):
            with self.subTest(key=key):
                self.path.write_bytes(_outer_bytes(metadata_overrides={key: False}))
                with self.assertRaisesRegex(CandidateArtifactError, key):
                    verify(self.path, SHA, expected_workflow_sha=WORKFLOW_SHA)

    def test_run_metadata_rejects_acceptance_overclaims(self) -> None:
        for key in ("human_tested", "nvda_verified"):
            with self.subTest(key=key):
                self.path.write_bytes(_outer_bytes(metadata_overrides={key: True}))
                with self.assertRaisesRegex(CandidateArtifactError, key):
                    verify(self.path, SHA, expected_workflow_sha=WORKFLOW_SHA)

    def test_run_metadata_rejects_unknown_fields(self) -> None:
        self.path.write_bytes(_outer_bytes(metadata_overrides={"unexpected": "value"}))
        with self.assertRaisesRegex(CandidateArtifactError, "run metadata key mismatch"):
            verify(self.path, SHA, expected_workflow_sha=WORKFLOW_SHA)

    def test_prefixed_outer_digest_passes(self) -> None:
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        verify(self.path, SHA, f"sha256:{digest}")

    def test_outer_artifact_hashing_is_streamed_not_read_whole(self) -> None:
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with patch.object(Path, "read_bytes", side_effect=AssertionError("must stream outer artifact")):
            verify(self.path, SHA, digest)

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

    def test_app_config_size_bound_fails_before_config_read(self) -> None:
        oversized_config = b"x" * (MAX_CANDIDATE_METADATA_BYTES + 1)
        self.path.write_bytes(
            _outer_bytes(candidate=_candidate_bytes(app_config=oversized_config))
        )
        original_read = zipfile.ZipFile.read

        def guarded_read(archive, name, *args, **kwargs):
            normalized = str(name).replace("\\", "/")
            if normalized == "AccessibleChess/AccessibleChess.exe.config":
                raise AssertionError("oversized app-config must not be decompressed")
            return original_read(archive, name, *args, **kwargs)

        with patch.object(zipfile.ZipFile, "read", new=guarded_read):
            with self.assertRaisesRegex(
                CandidateArtifactError,
                "WinForms accessibility app-config size",
            ):
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

    def test_lawful_starter_source_authority_is_verified(self) -> None:
        starter = _starter_bundle_files()
        manifest_path = f"{STARTER_ROOT}/manifest.json"
        manifest = json.loads(starter[manifest_path])
        manifest["starter_source"]["license_id"] = "LicenseRef-Unverified"
        starter[manifest_path] = json.dumps(manifest).encode("utf-8")
        self.path.write_bytes(_outer_bytes(candidate=_candidate_bytes(starter_files=starter)))
        with self.assertRaisesRegex(CandidateArtifactError, "source authority mismatch"):
            verify(self.path, SHA)

    def test_lawful_starter_manifest_hash_is_bound_to_packaged_bytes(self) -> None:
        starter = _starter_bundle_files()
        manifest_path = f"{STARTER_ROOT}/manifest.json"
        manifest = json.loads(starter[manifest_path])
        manifest["files"]["starter_uk.pgn"]["sha256"] = "0" * 64
        starter[manifest_path] = json.dumps(manifest).encode("utf-8")
        self.path.write_bytes(_outer_bytes(candidate=_candidate_bytes(starter_files=starter)))
        with self.assertRaisesRegex(CandidateArtifactError, "starter file SHA-256 mismatch"):
            verify(self.path, SHA)

    def test_lawful_starter_selected_record_hashes_bind_to_packaged_pgn(self) -> None:
        starter = _starter_bundle_files()
        manifest_path = f"{STARTER_ROOT}/manifest.json"
        manifest = json.loads(starter[manifest_path])
        manifest["starter_source"]["curation"]["selected_games"][0]["record_sha256"] = "0" * 64
        starter[manifest_path] = json.dumps(manifest).encode("utf-8")
        self.path.write_bytes(_outer_bytes(candidate=_candidate_bytes(starter_files=starter)))
        with self.assertRaisesRegex(
            CandidateArtifactError,
            "selected record hashes do not match packaged starter PGN",
        ):
            verify(self.path, SHA)

    def test_lawful_starter_actual_record_count_is_verified(self) -> None:
        starter = _starter_bundle_files()
        manifest_path = f"{STARTER_ROOT}/manifest.json"
        starter_path = f"{STARTER_ROOT}/starter_uk.pgn"
        starter[starter_path] = starter[starter_path].replace(
            b'[Event "Starter 239"]',
            b'[Site "Starter 239"]',
            1,
        )
        manifest = json.loads(starter[manifest_path])
        digest = hashlib.sha256(starter[starter_path]).hexdigest()
        manifest["files"]["starter_uk.pgn"]["sha256"] = digest
        manifest["files"]["starter_uk.pgn"]["bytes"] = len(starter[starter_path])
        manifest["starter_source"]["subset_sha256"] = digest
        starter[manifest_path] = json.dumps(manifest).encode("utf-8")
        self.path.write_bytes(_outer_bytes(candidate=_candidate_bytes(starter_files=starter)))
        with self.assertRaisesRegex(CandidateArtifactError, "not exactly one game"):
            verify(self.path, SHA)

    def test_lawful_starter_manifest_semantics_bind_to_strict_packaged_pgn(self) -> None:
        starter = _starter_bundle_files()
        manifest_path = f"{STARTER_ROOT}/manifest.json"
        manifest = json.loads(starter[manifest_path])
        selected = manifest["starter_source"]["curation"]["selected_games"][0]
        selected["event"] = "Self-consistent but not packaged PGN"
        starter[manifest_path] = json.dumps(manifest).encode("utf-8")
        self.path.write_bytes(_outer_bytes(candidate=_candidate_bytes(starter_files=starter)))
        with self.assertRaisesRegex(
            CandidateArtifactError,
            "semantic evidence mismatch at packaged game 1",
        ):
            verify(self.path, SHA, expected_workflow_sha=WORKFLOW_SHA)

    def test_lawful_starter_database_pgn_text_binds_to_packaged_pgn(self) -> None:
        starter = _starter_bundle_files(database_first_pgn_text="1. a3 a6 1-0")
        self.path.write_bytes(_outer_bytes(candidate=_candidate_bytes(starter_files=starter)))
        with self.assertRaisesRegex(
            CandidateArtifactError,
            "ACSDB game metadata does not match curated starter evidence",
        ):
            verify(self.path, SHA, expected_workflow_sha=WORKFLOW_SHA)

    def test_lawful_starter_database_claim_is_verified_against_sqlite(self) -> None:
        starter = _starter_bundle_files(database_games=STARTER_GAMES - 1)
        self.path.write_bytes(_outer_bytes(candidate=_candidate_bytes(starter_files=starter)))
        with self.assertRaisesRegex(CandidateArtifactError, "ACSDB semantic evidence mismatch"):
            verify(self.path, SHA)

    def test_lawful_starter_database_source_indexes_are_zero_based_and_stable(self) -> None:
        starter = _starter_bundle_files(database_first_source_index=240)
        self.path.write_bytes(_outer_bytes(candidate=_candidate_bytes(starter_files=starter)))
        with self.assertRaisesRegex(
            CandidateArtifactError,
            "ACSDB game metadata does not match curated starter evidence",
        ):
            verify(self.path, SHA, expected_workflow_sha=WORKFLOW_SHA)

    def test_lawful_starter_database_source_provenance_binds_to_starter_pgn(self) -> None:
        starter = _starter_bundle_files(database_source_sha256="0" * 64)
        self.path.write_bytes(_outer_bytes(candidate=_candidate_bytes(starter_files=starter)))
        with self.assertRaisesRegex(
            CandidateArtifactError,
            "source provenance does not bind packaged starter PGN",
        ):
            verify(self.path, SHA)

    def test_lawful_starter_database_rows_bind_to_curated_game_metadata(self) -> None:
        starter = _starter_bundle_files(database_first_white="Unexpected White")
        self.path.write_bytes(_outer_bytes(candidate=_candidate_bytes(starter_files=starter)))
        with self.assertRaisesRegex(
            CandidateArtifactError,
            "ACSDB game metadata does not match curated starter evidence",
        ):
            verify(self.path, SHA)

    def test_lawful_starter_database_schema_is_verified(self) -> None:
        starter = _starter_bundle_files(database_schema=5)
        self.path.write_bytes(_outer_bytes(candidate=_candidate_bytes(starter_files=starter)))
        with self.assertRaisesRegex(CandidateArtifactError, "ACSDB schema version mismatch"):
            verify(self.path, SHA)

    def test_lawful_starter_curation_record_evidence_is_fail_closed(self) -> None:
        starter = _starter_bundle_files()
        manifest_path = f"{STARTER_ROOT}/manifest.json"
        manifest = json.loads(starter[manifest_path])
        manifest["starter_source"]["curation"]["selected_games"][0]["record_sha256"] = "bad"
        starter[manifest_path] = json.dumps(manifest).encode("utf-8")
        self.path.write_bytes(_outer_bytes(candidate=_candidate_bytes(starter_files=starter)))
        with self.assertRaisesRegex(CandidateArtifactError, "record SHA-256 is invalid"):
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
        with self.assertRaisesRegex(CandidateArtifactError, "outer artifact layout mismatch"):
            verify(self.path, SHA)

    def test_outer_candidate_path_must_be_exact_root_layout(self) -> None:
        self.path.write_bytes(
            _outer_bytes(
                candidate_name="nested/Accessible-Chess-V2-fffffff-NVDA-test-candidate.zip"
            )
        )
        with self.assertRaisesRegex(CandidateArtifactError, "outer artifact layout mismatch"):
            verify(self.path, SHA)

    def test_outer_candidate_filename_is_case_exact(self) -> None:
        self.path.write_bytes(
            _outer_bytes(candidate_name="accessible-chess-v2-fffffff-NVDA-test-candidate.zip")
        )
        with self.assertRaisesRegex(CandidateArtifactError, "outer artifact layout mismatch"):
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

    def test_strict_uia_evidence_requires_explicit_machine_only_false_flags(self) -> None:
        for key in ("human_tested", "nvda_verified"):
            with self.subTest(key=key):
                value = _strict_uia_evidence()
                del value[key]
                self.path.write_bytes(
                    _zip_bytes(
                        {
                            "Accessible-Chess-V2-fffffff-NVDA-test-candidate.zip": _candidate_bytes(),
                            "p0-evidence/packaged-v2-document-copy-summary.json": json.dumps(
                                _copy_evidence()
                            ).encode(),
                            "p0-evidence/packaged-p0g-hotkey-result-summary.json": json.dumps(
                                _p0g_evidence()
                            ).encode(),
                            "p0-evidence/packaged-uia-strict-summary.json": json.dumps(value).encode(),
                            "p0-evidence/w4-run-metadata.json": json.dumps(
                                _run_metadata()
                            ).encode(),
                        }
                    )
                )
                with self.assertRaisesRegex(CandidateArtifactError, key):
                    verify(
                        self.path,
                        SHA,
                        expected_workflow_sha=WORKFLOW_SHA,
                    )

    def test_strict_uia_evidence_rejects_human_or_nvda_overclaims(self) -> None:
        for key, value in (
            ("human_tested", True),
            ("nvda_verified", True),
            ("human_tested", "yes"),
            ("nvda_verified", 1),
        ):
            with self.subTest(key=key, value=value):
                self.path.write_bytes(_outer_bytes(uia_overrides={key: value}))
                with self.assertRaisesRegex(CandidateArtifactError, key):
                    verify(self.path, SHA)

    def test_copy_evidence_requires_visible_static_text_range(self) -> None:
        self.path.write_bytes(
            _outer_bytes(copy_overrides={"static_text_visible_rectangle": False})
        )
        with self.assertRaisesRegex(CandidateArtifactError, "static_text_visible_rectangle"):
            verify(self.path, SHA)

    def test_copy_evidence_requires_exact_textpattern_target_selection(self) -> None:
        self.path.write_bytes(
            _outer_bytes(copy_overrides={"textpattern_target_selected": False})
        )
        with self.assertRaisesRegex(CandidateArtifactError, "textpattern_target_selected"):
            verify(self.path, SHA)

    def test_copy_evidence_requires_exact_textpattern_selection_equality(self) -> None:
        self.path.write_bytes(
            _outer_bytes(copy_overrides={"textpattern_selection_equality": "text only"})
        )
        with self.assertRaisesRegex(CandidateArtifactError, "TextPattern selection equality"):
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
                "p0-evidence/w4-run-metadata.json": json.dumps(
                    _run_metadata()
                ).encode(),
            }
        )
        self.path.write_bytes(outer)
        with self.assertRaisesRegex(CandidateArtifactError, "outer artifact layout mismatch"):
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
                "p0-evidence/w4-run-metadata.json": json.dumps(
                    _run_metadata()
                ).encode(),
                "unexpected.bin": b"not part of canonical candidate artifact",
            }
        )
        self.path.write_bytes(outer)
        with self.assertRaisesRegex(CandidateArtifactError, "outer artifact layout mismatch"):
            verify(self.path, SHA)

    def test_candidate_payload_tamper_fails(self) -> None:
        self.path.write_bytes(
            _outer_bytes(candidate=_candidate_bytes(tamper="AccessibleChess/AccessibleChess.exe"))
        )
        with self.assertRaises(CandidateArtifactError):
            verify(self.path, SHA)

    def test_application_executable_requires_windows_mz_signature(self) -> None:
        self.path.write_bytes(
            _outer_bytes(candidate=_candidate_bytes(app_executable=b"XX" + b"\x00" * 78))
        )
        with self.assertRaisesRegex(CandidateArtifactError, "application executable.*MZ"):
            verify(self.path, SHA)

    def test_stockfish_executable_requires_windows_mz_signature(self) -> None:
        self.path.write_bytes(
            _outer_bytes(candidate=_candidate_bytes(stockfish_executable=b"XX" + b"\x00" * 78))
        )
        with self.assertRaisesRegex(CandidateArtifactError, "Stockfish executable.*MZ"):
            verify(self.path, SHA)

    def test_application_executable_requires_pe_signature(self) -> None:
        malformed = bytearray(_pe_fixture(b"app"))
        malformed[64:68] = b"NOPE"
        self.path.write_bytes(
            _outer_bytes(candidate=_candidate_bytes(app_executable=bytes(malformed)))
        )
        with self.assertRaisesRegex(CandidateArtifactError, "application executable.*PE"):
            verify(self.path, SHA)

    def test_stockfish_executable_rejects_out_of_bounds_pe_offset(self) -> None:
        malformed = bytearray(_pe_fixture(b"stockfish"))
        malformed[60:64] = (32 * 1024 * 1024).to_bytes(4, "little")
        self.path.write_bytes(
            _outer_bytes(candidate=_candidate_bytes(stockfish_executable=bytes(malformed)))
        )
        with self.assertRaisesRegex(CandidateArtifactError, "Stockfish executable.*PE header offset"):
            verify(self.path, SHA)

    def test_symbolic_link_zip_entry_fails_closed(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(
                "Accessible-Chess-V2-fffffff-NVDA-test-candidate.zip",
                _candidate_bytes(),
            )
            archive.writestr(
                "p0-evidence/packaged-v2-document-copy-summary.json",
                json.dumps(_copy_evidence()).encode(),
            )
            archive.writestr(
                "p0-evidence/packaged-p0g-hotkey-result-summary.json",
                json.dumps(_p0g_evidence()).encode(),
            )
            link = zipfile.ZipInfo("p0-evidence/packaged-uia-strict-summary.json")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, b"uia-target")
        self.path.write_bytes(buffer.getvalue())
        with self.assertRaisesRegex(CandidateArtifactError, "symbolic link entry"):
            verify(self.path, SHA)

    def test_special_file_zip_entry_fails_closed(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(
                "Accessible-Chess-V2-fffffff-NVDA-test-candidate.zip",
                _candidate_bytes(),
            )
            archive.writestr(
                "p0-evidence/packaged-v2-document-copy-summary.json",
                json.dumps(_copy_evidence()).encode(),
            )
            archive.writestr(
                "p0-evidence/packaged-p0g-hotkey-result-summary.json",
                json.dumps(_p0g_evidence()).encode(),
            )
            special = zipfile.ZipInfo("p0-evidence/packaged-uia-strict-summary.json")
            special.create_system = 3
            special.external_attr = (stat.S_IFIFO | 0o600) << 16
            archive.writestr(special, b"uia-target")
        self.path.write_bytes(buffer.getvalue())
        with self.assertRaisesRegex(CandidateArtifactError, "unsupported special file entry"):
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
        with self.assertRaisesRegex(CandidateArtifactError, "human_tested"):
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
                "p0-evidence/w4-run-metadata.json": json.dumps(
                    _run_metadata()
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
