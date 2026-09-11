from __future__ import annotations

import hashlib
import json

from acs.acsdb import AcsDatabase
from acs.starter_content import (
    STARTER_GAME_COUNT,
    STRESS_GAME_COUNT,
    build_sample_library,
    build_starter_bundle,
    build_starter_pgn,
    build_stress_pgn,
)


def _game_count(text: str) -> int:
    return text.count('[Event "')


def test_starter_pgn_is_deterministic_project_authored_and_large_enough():
    first = build_starter_pgn()
    second = build_starter_pgn()

    assert first == second
    assert _game_count(first) == STARTER_GAME_COUNT
    assert STARTER_GAME_COUNT >= 200
    assert "project-authored synthetic corpus" in first
    assert "Синтетична навчальна партія" in first
    assert "http://" not in first
    assert "https://" not in first


def test_stress_pgn_is_larger_and_deterministic():
    first = build_stress_pgn()
    second = build_stress_pgn()

    assert first == second
    assert _game_count(first) == STRESS_GAME_COUNT
    assert STRESS_GAME_COUNT > STARTER_GAME_COUNT
    assert len(first.encode("utf-8")) > len(build_starter_pgn().encode("utf-8"))


def test_sample_library_uses_canonical_import_and_is_searchable(tmp_path):
    database_path = tmp_path / "sample_library.acsdb"
    build_sample_library(database_path)

    with AcsDatabase(database_path) as database:
        assert database.verify_integrity() >= 1
        rows = database.search_games(player="Учень", limit=25)
        assert len(rows) == 25
        assert all("Учень" in f"{row['white']} {row['black']}" for row in rows)

        event_rows = database.search_games(event="Accessible Chess", limit=100)
        assert event_rows


def test_bundle_manifest_hashes_every_payload_and_records_provenance(tmp_path):
    manifest = build_starter_bundle(tmp_path)

    assert manifest["provenance"]["kind"] == "project-authored-synthetic"
    assert manifest["provenance"]["third_party_corpus"] is False
    assert manifest["provenance"]["network_required"] is False
    assert manifest["counts"]["starter_games"] == STARTER_GAME_COUNT
    assert manifest["counts"]["stress_games"] == STRESS_GAME_COUNT

    on_disk = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest
    for name, expected in manifest["files"].items():
        payload = (tmp_path / name).read_bytes()
        assert len(payload) == expected["bytes"]
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"]
