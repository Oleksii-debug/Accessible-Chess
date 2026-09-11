from __future__ import annotations

import hashlib
import io
import json

import pytest

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.starter_content import CONTENT_LICENSE_ID, build_starter_pgn
from tools.p0f_lawful_starter_bundle import (
    CORPUS_LICENSE_ID,
    MINIMUM_REAL_GAME_COUNT,
    build_release_bundle_from_curated_pgn,
    _write_complete_game_subset,
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
                    "{comment with an Event-like token [Event \"not-a-header\"]} 1. e4 e5 *",
                )
            )
        )
    return "\n\n".join(records) + "\n"


def test_complete_record_framer_keeps_exact_bounded_records(tmp_path):
    source = io.StringIO(_fixture_pgn_records(MINIMUM_REAL_GAME_COUNT + 5))
    destination = tmp_path / "subset.pgn"

    written = _write_complete_game_subset(source, destination, MINIMUM_REAL_GAME_COUNT)

    text = destination.read_text(encoding="utf-8")
    assert written == MINIMUM_REAL_GAME_COUNT
    assert text.count('[Event "Fixture ') == MINIMUM_REAL_GAME_COUNT
    assert "Fixture 200" in text
    assert "Fixture 201" not in text


def test_release_bundle_requires_binding_minimum_real_game_count(tmp_path):
    with pytest.raises(ValueError, match=">= 200"):
        build_release_bundle_from_curated_pgn(
            tmp_path,
            starter_pgn=build_starter_pgn(16),
            starter_count=16,
            source_subset_sha256="a" * 64,
            source_compressed_bytes=1,
            stress_count=32,
        )


def test_release_bundle_mixes_lawful_real_starter_with_project_stress(tmp_path):
    # This local fixture exercises the release builder without network. The real
    # pinned CC0 archive is qualified separately by the Actions real-corpus job.
    starter_count = MINIMUM_REAL_GAME_COUNT
    starter_pgn = build_starter_pgn(starter_count)
    subset_sha = hashlib.sha256(starter_pgn.encode("utf-8")).hexdigest()

    manifest = build_release_bundle_from_curated_pgn(
        tmp_path,
        starter_pgn=starter_pgn,
        starter_count=starter_count,
        source_subset_sha256=subset_sha,
        source_compressed_bytes=12345,
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


def test_release_bundle_rejects_record_count_mismatch(tmp_path):
    with pytest.raises(ValueError, match="complete-record count"):
        build_release_bundle_from_curated_pgn(
            tmp_path,
            starter_pgn=build_starter_pgn(MINIMUM_REAL_GAME_COUNT),
            starter_count=MINIMUM_REAL_GAME_COUNT + 1,
            source_subset_sha256="b" * 64,
            source_compressed_bytes=1,
            stress_count=MINIMUM_REAL_GAME_COUNT + 2,
        )
