from __future__ import annotations

import hashlib
import json

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.starter_content import (
    CONTENT_LICENSE_ID,
    INSTRUCTIONAL_SEEDS,
    STARTER_GAME_COUNT,
    STARTER_MAX_PLIES,
    STRESS_GAME_COUNT,
    _generate_instructional_game,
    build_sample_library,
    build_starter_bundle,
    build_starter_pgn,
    build_stress_pgn,
)


def _game_count(text: str) -> int:
    return text.count('[Event "')


def test_acceptance_volume_defaults_are_substantial():
    assert STARTER_GAME_COUNT >= 200
    assert STRESS_GAME_COUNT > STARTER_GAME_COUNT
    assert len(INSTRUCTIONAL_SEEDS) >= 12


def test_starter_pgn_is_deterministic_project_authored_and_instructional():
    first = build_starter_pgn(8)
    second = build_starter_pgn(8)

    assert first == second
    assert _game_count(first) == 8
    assert "project-authored synthetic corpus" in first
    assert '[Opening "' in first
    assert '[Theme "' in first
    assert '[LearningGoal "' in first
    assert "Навчальна тема:" in first
    assert "Мета:" in first
    assert "http://" not in first
    assert "https://" not in first


def test_default_starter_games_have_distinct_curated_legal_sequences():
    games = [
        _generate_instructional_game(index, max_plies=STARTER_MAX_PLIES)
        for index in range(1, STARTER_GAME_COUNT + 1)
    ]
    assert len({game.movetext for game in games}) == STARTER_GAME_COUNT
    assert len({game.opening for game in games}) == len(INSTRUCTIONAL_SEEDS)
    assert all(game.theme_uk and game.learning_goal_uk for game in games)


def test_stress_pgn_is_larger_and_deterministic():
    first = build_stress_pgn(16)
    second = build_stress_pgn(16)

    assert first == second
    assert _game_count(first) == 16
    assert len(first.encode("utf-8")) > len(build_starter_pgn(8).encode("utf-8"))


def test_stress_pgn_routes_through_canonical_import_and_search(tmp_path):
    stress = build_stress_pgn(96)
    with AcsDatabase(tmp_path / "stress.acsdb") as database:
        report = database.import_pgn_text(stress, source_name="stress_uk.pgn")
        assert report.total == 96
        assert report.damaged == 0
        assert len(report.game_ids) == 96
        assert database.verify_integrity() == ACSDB_SCHEMA_VERSION
        total, distinct = database.conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT pgn_text) FROM games"
        ).fetchone()
        assert total == distinct == 96
        assert database.search_games(event="Accessible Chess", limit=25)
        assert database.search_games(player="Учень", limit=25)


def test_sample_library_uses_canonical_import_and_is_searchable(tmp_path):
    database_path = tmp_path / "sample_library.acsdb"
    build_sample_library(database_path, starter_pgn=build_starter_pgn(32))

    with AcsDatabase(database_path) as database:
        assert database.verify_integrity() == ACSDB_SCHEMA_VERSION
        total, distinct = database.conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT pgn_text) FROM games"
        ).fetchone()
        assert total == distinct == 32
        rows = database.search_games(player="Учень", limit=25)
        assert len(rows) == 25
        assert all("Учень" in f"{row['white']} {row['black']}" for row in rows)
        assert len(database.search_games(opening="Game", limit=100)) >= 1
        assert database.search_games(event="Accessible Chess", limit=100)


def test_bundle_manifest_hashes_and_licenses_every_payload(tmp_path):
    manifest = build_starter_bundle(tmp_path, starter_count=32, stress_count=64)

    assert manifest["provenance"]["kind"] == "project-authored-synthetic"
    assert manifest["provenance"]["third_party_corpus"] is False
    assert manifest["provenance"]["network_required"] is False
    assert manifest["license"]["id"] == CONTENT_LICENSE_ID
    assert manifest["license"]["type"] == "project-owned-redistribution-grant"
    assert manifest["license"]["third_party_rights_asserted"] is False
    assert manifest["counts"]["starter_games"] == 32
    assert manifest["counts"]["stress_games"] == 64
    assert manifest["instructional_catalog"]["curated_seed_count"] == len(INSTRUCTIONAL_SEEDS)

    on_disk = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest
    assert set(manifest["license"]["applies_to"]) == set(manifest["files"])
    for name, expected in manifest["files"].items():
        payload = (tmp_path / name).read_bytes()
        assert len(payload) == expected["bytes"]
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"]
        assert expected["license_id"] == CONTENT_LICENSE_ID
