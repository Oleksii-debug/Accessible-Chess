from __future__ import annotations

import pytest

from acs.acsdb import AcsDatabase
from acs.search_service import GameSearchQuery, GameSearchService


PGN = """[Event \"Kyiv Open\"]
[Site \"Kyiv UKR\"]
[Date \"2026.08.14\"]
[Round \"1\"]
[White \"Alpha\"]
[Black \"Beta\"]
[Result \"1-0\"]
[ECO \"C20\"]
[Opening \"King's Pawn Game\"]

1. e4 e5 2. Nf3 Nc6 1-0

[Event \"Lviv Open\"]
[Site \"Lviv UKR\"]
[Date \"2026.08.14\"]
[Round \"2\"]
[White \"Gamma\"]
[Black \"Alpha\"]
[Result \"1/2-1/2\"]
[ECO \"B12\"]
[Opening \"Caro-Kann Defense\"]

1. e4 c6 2. d4 d5 1/2-1/2

[Event \"Odesa Open\"]
[Site \"Odesa UKR\"]
[Date \"2026.08.14\"]
[Round \"3\"]
[White \"Delta\"]
[Black \"Epsilon\"]
[Result \"0-1\"]
[ECO \"B20\"]
[Opening \"Sicilian Defense\"]

1. e4 c5 2. Nf3 d6 0-1
"""


def seeded_database() -> AcsDatabase:
    db = AcsDatabase()
    db.import_pgn_text(PGN, source_name="tournament-2026.pgn")
    return db


def test_search_returns_neutral_dtos_with_source_provenance() -> None:
    db = seeded_database()
    try:
        page = GameSearchService(db).search(GameSearchQuery(player=" alpha "))
        assert [item.white for item in page.items] == ["Alpha", "Gamma"]
        assert [item.black for item in page.items] == ["Beta", "Alpha"]
        assert all(item.source_name == "tournament-2026.pgn" for item in page.items)
        assert all(item.source_format == "pgn" for item in page.items)
        assert all(item.source_id > 0 for item in page.items)
    finally:
        db.close()


def test_search_combines_filters_without_exposing_sql() -> None:
    db = seeded_database()
    try:
        page = GameSearchService(db).search(
            GameSearchQuery(event="lviv", eco="B", result="1/2-1/2", source_name="tournament")
        )
        assert len(page.items) == 1
        item = page.items[0]
        assert item.event == "Lviv Open"
        assert item.eco == "B12"
        assert item.opening == "Caro-Kann Defense"
    finally:
        db.close()


def test_keyset_paging_is_stable_and_has_no_duplicate_game_ids() -> None:
    db = seeded_database()
    try:
        service = GameSearchService(db)
        first = service.search(GameSearchQuery(limit=2))
        assert len(first.items) == 2
        assert first.has_more is True
        assert first.next_after_game_id == first.items[-1].game_id

        second = service.search(
            GameSearchQuery(limit=2, after_game_id=first.next_after_game_id)
        )
        assert len(second.items) == 1
        assert second.has_more is False
        assert second.next_after_game_id is None
        assert {item.game_id for item in first.items}.isdisjoint(
            {item.game_id for item in second.items}
        )
    finally:
        db.close()


def test_query_validation_rejects_unsafe_or_ambiguous_bounds() -> None:
    with pytest.raises(ValueError, match="between 1 and 200"):
        GameSearchQuery(limit=0).normalized()
    with pytest.raises(ValueError, match="positive integer"):
        GameSearchQuery(source_id=0).normalized()
    with pytest.raises(ValueError, match="zero or a positive"):
        GameSearchQuery(after_game_id=-1).normalized()


def test_search_values_are_parameters_not_sql_fragments() -> None:
    db = seeded_database()
    try:
        page = GameSearchService(db).search(
            GameSearchQuery(player="Alpha' OR 1=1 --")
        )
        assert page.items == ()
        assert db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 3
    finally:
        db.close()
