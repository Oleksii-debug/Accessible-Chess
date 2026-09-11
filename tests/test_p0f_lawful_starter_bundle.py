from __future__ import annotations

import hashlib
import io
import json
import re

import pytest

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.starter_content import CONTENT_LICENSE_ID, build_starter_pgn
from tools.p0f_lawful_starter_bundle import (
    CORPUS_LICENSE_ID,
    CURATION_MIN_PLIES,
    MINIMUM_REAL_GAME_COUNT,
    _candidate_from_record,
    _curation_evidence,
    _iter_complete_game_records,
    _select_curated_candidates,
    _write_complete_game_subset,
    build_release_bundle_from_curated_pgn,
)


def _fixture_pgn_records(count: int) -> str:
    records = []
    for index in range(1, count + 1):
        records.append(
            "\n".join(
                (
                    f'[Event "Fixture {index:03d}"]',
                    '[Site "Offline"]',
                    '[Date "2026.09.11"]',
                    f'[Round "{index}"]',
                    f'[White "White {index:03d}"]',
                    f'[Black "Black {index:03d}"]',
                    '[Result "*"]',
                    "",
                    '{comment with an Event-like token [Event "not-a-header"]} 1. e4 e5 *',
                )
            )
        )
    return "\n\n".join(records) + "\n"


def _quality_curated_records(count: int) -> list[str]:
    records = [
        record
        for _index, record in _iter_complete_game_records(io.StringIO(build_starter_pgn(count)))
    ]
    results = ("1-0", "0-1", "1/2-1/2")
    curated: list[str] = []
    for index, record in enumerate(records, start=1):
        result = results[(index - 1) % len(results)]
        record = re.sub(
            r'^\[Result "[^"]*"\]$', f'[Result "{result}"]', record, flags=re.MULTILINE
        )
        record = re.sub(
            r'^(\[Black "[^"]+"\])$',
            rf'\1\n[WhiteElo "{1200 + (index % 700)}"]\n[BlackElo "{1250 + (index % 650)}"]',
            record,
            count=1,
            flags=re.MULTILINE,
        )
        record = re.sub(
            r'(?:1-0|0-1|1/2-1/2|\*)\s*$',
            result,
            record.rstrip(),
            count=1,
        )
        curated.append(record)
    return curated


def _curated_fixture(count: int) -> tuple[str, dict[str, object]]:
    records = _quality_curated_records(count)
    candidates = []
    for source_index, record in enumerate(records, start=1):
        candidate = _candidate_from_record(source_index, record)
        assert candidate is not None
        candidates.append(candidate)
    selected = _select_curated_candidates(candidates, count)
    text = "\n\n".join(candidate.record for candidate in selected) + "\n"
    return text, _curation_evidence(selected, scanned_records=len(records))


def test_complete_record_framer_keeps_exact_bounded_records(tmp_path):
    source = io.StringIO(_fixture_pgn_records(MINIMUM_REAL_GAME_COUNT + 5))
    destination = tmp_path / "subset.pgn"

    written = _write_complete_game_subset(source, destination, MINIMUM_REAL_GAME_COUNT)

    text = destination.read_text(encoding="utf-8")
    assert written == MINIMUM_REAL_GAME_COUNT
    assert text.count('[Event "Fixture ') == MINIMUM_REAL_GAME_COUNT
    assert "Fixture 200" in text
    assert "Fixture 201" not in text


def test_quality_gate_rejects_unfinished_unrated_or_too_short_games():
    unfinished = _fixture_pgn_records(1).strip()
    assert _candidate_from_record(1, unfinished) is None

    rated = "\n".join(
        (
            '[Event "Short"]',
            '[White "Alpha"]',
            '[Black "Beta"]',
            '[WhiteElo "1600"]',
            '[BlackElo "1700"]',
            '[Result "1-0"]',
            "",
            "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0",
        )
    )
    assert _candidate_from_record(1, rated) is None


def test_curated_fixture_meets_quality_and_representativeness_gate():
    text, evidence = _curated_fixture(MINIMUM_REAL_GAME_COUNT)

    assert evidence["selected_games"] == MINIMUM_REAL_GAME_COUNT
    assert evidence["policy_version"] == 1
    assert evidence["distinct_opening_prefixes"] >= 16
    assert set(evidence["result_counts"]) == {"1-0", "0-1", "1/2-1/2"}
    assert min(evidence["result_counts"].values()) >= MINIMUM_REAL_GAME_COUNT // 20
    assert len(evidence["games"]) == MINIMUM_REAL_GAME_COUNT
    assert min(game["plies"] for game in evidence["games"]) >= CURATION_MIN_PLIES
    assert len(list(_iter_complete_game_records(io.StringIO(text)))) == MINIMUM_REAL_GAME_COUNT


def test_release_bundle_requires_binding_minimum_real_game_count(tmp_path):
    with pytest.raises(ValueError, match=">= 200"):
        build_release_bundle_from_curated_pgn(
            tmp_path,
            starter_pgn=build_starter_pgn(16),
            starter_count=16,
            source_subset_sha256="a" * 64,
            source_compressed_bytes=1,
            curation={},
            stress_count=32,
        )


def test_release_bundle_mixes_curated_lawful_starter_with_project_stress(tmp_path):
    starter_count = MINIMUM_REAL_GAME_COUNT
    starter_pgn, curation = _curated_fixture(starter_count)
    subset_sha = hashlib.sha256(starter_pgn.encode("utf-8")).hexdigest()

    manifest = build_release_bundle_from_curated_pgn(
        tmp_path,
        starter_pgn=starter_pgn,
        starter_count=starter_count,
        source_subset_sha256=subset_sha,
        source_compressed_bytes=12345,
        curation=curation,
        stress_count=starter_count + 16,
    )

    assert manifest["schema_version"] == 3
    assert manifest["bundle_kind"] == "lawful-curated-real-game-starter"
    assert manifest["runtime_network_required"] is False
    assert manifest["counts"] == {
        "starter_games": starter_count,
        "stress_games": starter_count + 16,
    }
    assert manifest["starter_source"]["license_id"] == CORPUS_LICENSE_ID
    assert manifest["starter_source"]["selected_games"] == starter_count
    assert manifest["starter_source"]["subset_sha256"] == subset_sha
    assert manifest["starter_source"]["selection"] == (
        "deterministic quality-and-representativeness curation v1"
    )
    assert manifest["curation"] == curation
    assert manifest["files"]["starter_uk.pgn"]["license_id"] == CORPUS_LICENSE_ID
    assert manifest["files"]["sample_library.acsdb"]["license_id"] == CORPUS_LICENSE_ID
    assert manifest["files"]["stress_uk.pgn"]["license_id"] == CONTENT_LICENSE_ID

    on_disk = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest
    assert set(manifest["files"]) == {
        "starter_uk.pgn",
        "stress_uk.pgn",
        "sample_library.acsdb",
    }
    for name, metadata in manifest["files"].items():
        payload = (tmp_path / name).read_bytes()
        assert len(payload) == metadata["bytes"]
        assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]

    with AcsDatabase(tmp_path / "sample_library.acsdb") as database:
        assert database.verify_integrity() == ACSDB_SCHEMA_VERSION
        total, distinct = database.conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT pgn_text) FROM games"
        ).fetchone()
        assert total == distinct == starter_count


def test_release_bundle_rejects_tampered_per_game_curation_evidence(tmp_path):
    starter_pgn, curation = _curated_fixture(MINIMUM_REAL_GAME_COUNT)
    curation["games"][0]["record_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="curation evidence mismatch"):
        build_release_bundle_from_curated_pgn(
            tmp_path,
            starter_pgn=starter_pgn,
            starter_count=MINIMUM_REAL_GAME_COUNT,
            source_subset_sha256=hashlib.sha256(starter_pgn.encode()).hexdigest(),
            source_compressed_bytes=1,
            curation=curation,
            stress_count=MINIMUM_REAL_GAME_COUNT + 16,
        )
