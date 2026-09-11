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
    CURATION_LENGTH_MINIMUMS,
    CURATION_MAX_SCANNED_GAMES,
    CURATION_MIN_OPENING_PREFIXES,
    CURATION_MIN_PLIES,
    CURATION_POLICY_ID,
    CURATION_RESULT_MINIMUMS,
    CURATION_VALID_RESULTS,
    MINIMUM_REAL_GAME_COUNT,
    _candidate_evidence,
    _iter_complete_game_records,
    _selected_aggregate_evidence,
    _select_representative_candidates,
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


def _finished_record(record: str, result: str = "1-0") -> str:
    record = re.sub(r'\[Result "[^"]*"\]', f'[Result "{result}"]', record, count=1)
    prefix, separator, _old_result = record.rstrip().rpartition(" ")
    assert separator
    return f"{prefix} {result}"


def _fake_curation_evidence(starter_pgn: str) -> dict[str, object]:
    records = list(_iter_complete_game_records(io.StringIO(starter_pgn)))
    results = ("1-0", "0-1", "1/2-1/2")
    bands = ("20-59", "60-99", "100+")
    selected: list[dict[str, object]] = []
    for index, record in enumerate(records, start=1):
        result = results[(index - 1) % len(results)]
        band = bands[(index - 1) % len(bands)]
        plies = {"20-59": 32, "60-99": 72, "100+": 112}[band]
        opening_id = (index - 1) % CURATION_MIN_OPENING_PREFIXES
        selected.append(
            {
                "source_index": index,
                "event": f"Fixture {index}",
                "white": f"White {index}",
                "black": f"Black {index}",
                "result": result,
                "plies": plies,
                "length_band": band,
                "opening_prefix": ["fixture", str(opening_id), "prefix", str(opening_id)],
                "record_sha256": hashlib.sha256(record.encode("utf-8")).hexdigest(),
            }
        )
    aggregate = _selected_aggregate_evidence(selected)
    return {
        "policy_id": CURATION_POLICY_ID,
        "parser": "acs.pgn_roundtrip.parse_pgn_text(strict=True)",
        "criteria": {
            "minimum_plies": CURATION_MIN_PLIES,
            "valid_results": sorted(CURATION_VALID_RESULTS),
            "required_metadata": ["Event", "White", "Black"],
            "result_minimums": CURATION_RESULT_MINIMUMS,
            "length_band_minimums": CURATION_LENGTH_MINIMUMS,
            "minimum_distinct_opening_prefixes": CURATION_MIN_OPENING_PREFIXES,
            "opening_prefix_plies": 4,
            "maximum_scanned_games": CURATION_MAX_SCANNED_GAMES,
        },
        "scanned_records": len(records),
        "eligible_records": len(records),
        "rejected_records": {},
        "selected_games": selected,
        **aggregate,
    }


def test_complete_record_framer_keeps_exact_bounded_records(tmp_path):
    source = io.StringIO(_fixture_pgn_records(MINIMUM_REAL_GAME_COUNT + 5))
    destination = tmp_path / "subset.pgn"

    written = _write_complete_game_subset(source, destination, MINIMUM_REAL_GAME_COUNT)

    text = destination.read_text(encoding="utf-8")
    assert written == MINIMUM_REAL_GAME_COUNT
    assert text.count('[Event "Fixture ') == MINIMUM_REAL_GAME_COUNT
    assert "Fixture 200" in text
    assert "Fixture 201" not in text


def test_quality_evidence_rejects_unfinished_and_accepts_strict_finished_game():
    record = next(_iter_complete_game_records(io.StringIO(build_starter_pgn(1))))

    evidence, reason = _candidate_evidence(record, 1)
    assert evidence is None
    assert reason == "invalid_or_unfinished_result"

    evidence, reason = _candidate_evidence(_finished_record(record), 1)
    assert reason is None
    assert evidence is not None
    assert evidence["result"] == "1-0"
    assert evidence["plies"] >= CURATION_MIN_PLIES
    assert len(evidence["opening_prefix"]) == 4
    assert len(evidence["record_sha256"]) == 64


def test_representative_selector_makes_each_floor_mandatory():
    candidates = _fake_curation_evidence(build_starter_pgn(MINIMUM_REAL_GAME_COUNT))["selected_games"]
    assert isinstance(candidates, list)

    selected = _select_representative_candidates(candidates, MINIMUM_REAL_GAME_COUNT)
    aggregate = _selected_aggregate_evidence(selected)

    assert len(selected) == MINIMUM_REAL_GAME_COUNT
    for result, minimum in CURATION_RESULT_MINIMUMS.items():
        assert aggregate["selected_result_counts"][result] >= minimum
    for band, minimum in CURATION_LENGTH_MINIMUMS.items():
        assert aggregate["selected_length_band_counts"][band] >= minimum
    assert aggregate["distinct_opening_prefixes"] >= CURATION_MIN_OPENING_PREFIXES


def test_representative_selector_rejects_nonrepresentative_pool():
    candidates = _fake_curation_evidence(build_starter_pgn(MINIMUM_REAL_GAME_COUNT))["selected_games"]
    assert isinstance(candidates, list)
    for candidate in candidates:
        candidate["result"] = "1-0"

    with pytest.raises(RuntimeError, match="representative curation floors"):
        _select_representative_candidates(candidates, MINIMUM_REAL_GAME_COUNT)


def test_release_bundle_requires_binding_minimum_real_game_count(tmp_path):
    starter_pgn = build_starter_pgn(16)
    with pytest.raises(ValueError, match=">= 200"):
        build_release_bundle_from_curated_pgn(
            tmp_path,
            starter_pgn=starter_pgn,
            starter_count=16,
            source_subset_sha256="a" * 64,
            source_compressed_bytes=1,
            curation_evidence=_fake_curation_evidence(starter_pgn),
            stress_count=32,
        )


def test_release_bundle_binds_curation_evidence_to_exact_selected_bytes(tmp_path):
    starter_count = MINIMUM_REAL_GAME_COUNT
    starter_pgn = build_starter_pgn(starter_count)
    subset_sha = hashlib.sha256(starter_pgn.encode("utf-8")).hexdigest()
    curation = _fake_curation_evidence(starter_pgn)

    manifest = build_release_bundle_from_curated_pgn(
        tmp_path,
        starter_pgn=starter_pgn,
        starter_count=starter_count,
        source_subset_sha256=subset_sha,
        source_compressed_bytes=12345,
        curation_evidence=curation,
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
    assert manifest["starter_source"]["selection"] == CURATION_POLICY_ID
    assert manifest["starter_source"]["curation"] == curation
    assert manifest["starter_source"]["subset_sha256"] == subset_sha
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


def test_release_bundle_rejects_curation_evidence_for_different_bytes(tmp_path):
    starter_count = MINIMUM_REAL_GAME_COUNT
    starter_pgn = build_starter_pgn(starter_count)
    curation = _fake_curation_evidence(starter_pgn)
    curation["selected_games"][0]["record_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="does not match selected starter PGN records"):
        build_release_bundle_from_curated_pgn(
            tmp_path,
            starter_pgn=starter_pgn,
            starter_count=starter_count,
            source_subset_sha256="b" * 64,
            source_compressed_bytes=1,
            curation_evidence=curation,
            stress_count=starter_count + 2,
        )


def test_release_bundle_rejects_record_count_mismatch(tmp_path):
    starter_pgn = build_starter_pgn(MINIMUM_REAL_GAME_COUNT)
    with pytest.raises(ValueError, match="complete-record count"):
        build_release_bundle_from_curated_pgn(
            tmp_path,
            starter_pgn=starter_pgn,
            starter_count=MINIMUM_REAL_GAME_COUNT + 1,
            source_subset_sha256="b" * 64,
            source_compressed_bytes=1,
            curation_evidence=_fake_curation_evidence(starter_pgn),
            stress_count=MINIMUM_REAL_GAME_COUNT + 2,
        )
