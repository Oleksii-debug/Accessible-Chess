"""Actual Section37 historical Réti composed-study PGN qualification.

Unlike Lichess puzzle ratings, this is a 1921 authored study. Exercise the
original historical FEN and exact executable SAN continuation, both original
UK/EN comments, PGN annotation publication, Library indexing, search and
crash-safe SQLite reimport using the existing canonical product services.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from acs.acsdb import AcsDatabase
from acs.chesscore import Board
from acs.gametree import parse_games
from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog, read_verified_source_snapshot
from acs.library_import_service import LibraryImportService
from acs.library_source_service import LibrarySourceCatalogService
from acs.pgn_roundtrip import parse_pgn_text
from acs.pgn_service import save_pgn_atomic, open_pgn
from acs.search_service import GameSearchQuery, GameSearchService
from tools.section39_pgn_semantic_signature import _pgn_signature
from tools.revised_section37_external_book_acquisition import ROOT, _exact_head as _source_head

SOURCE_ID = "historical_reti_1921_original_bilingual_study_pgn"
REPORT = ROOT / "section39-historic-reti-study-bilingual-source-readback.json"
ORIGINAL_FEN = "7K/8/k1P5/7p/8/8/8/8 w - - 0 1"


def qualify_original_reti_study() -> dict:
    records = {item["id"]: item for item in load_catalog()}
    source = records.get(SOURCE_ID)
    if source is None or (
        source.get("format") != "pgn"
        or source.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
        or source.get("public_release") != "INCLUDED_OWN_TEXT_HISTORICAL_COMPOSITION"
        or not str(source.get("redistribution", "")).startswith("permitted")
        or source.get("original_year") != 1921
    ):
        raise LawfulCorpusError("original composed-study source not proven and authorized")
    raw = read_verified_source_snapshot(ROOT / source["local_source"], source)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != source["sha256"] or len(raw) != source["indexed_bytes"]:
        raise LawfulCorpusError("historical composed-study source bytes changed")
    text = raw.decode("utf-8", errors="strict")
    if "UK:" not in text or "EN:" not in text or "Реті" not in text:
        raise LawfulCorpusError("original authored English/Ukrainian study annotations missing")
    games = parse_pgn_text(text, strict=False)
    if len(games) != 1 or games[0].tags.get("SetUp") != "1":
        raise LawfulCorpusError("authentic Réti FEN/SetUp GameTree not imported")
    game = games[0]
    if (
        game.tags.get("FEN") != ORIGINAL_FEN
        or game.tags.get("Result") != "1/2-1/2"
        or len(game.line.moves) != 11
    ):
        raise LawfulCorpusError("historical Réti source original objective/FEN/moves changed")
    board = Board(ORIGINAL_FEN)
    positions = [board.fen()]
    for move in game.line.moves:
        played = board.push_text(move.san)
        if not played:
            raise LawfulCorpusError("historical authored endgame SAN fails canonical chess rules")
        positions.append(board.fen())
    if len(positions) != 12 or positions[0] != ORIGINAL_FEN:
        raise LawfulCorpusError("historical composed-study move replay incomplete")
    start = _pgn_signature(tuple(games))
    with tempfile.TemporaryDirectory(prefix="acs39-reti-study-") as temporary:
        root = Path(temporary)
        path = root / "historical-reti-study.pgn"
        save_pgn_atomic(path, games)
        reimported = tuple(open_pgn(path).games)
        pgn_equal = _pgn_signature(reimported) == start
        dbpath = root / "real-historical-studies.acsdb"
        game.source_index = 0
        with AcsDatabase(dbpath) as db:
            imported = LibraryImportService(db).import_games(
                games, source_name="Richard Reti original 1921 study",
                source_format="pgn", source_sha256=digest,
            )
            if imported.game_count != 1 or imported.reused or imported.warning_count:
                raise LawfulCorpusError("canonical chess Library could not import historical study")
            db.verify_integrity()
        with AcsDatabase(dbpath) as db:
            source_record = LibrarySourceCatalogService(db).get_source(imported.source_id)
            game_rows = LibrarySourceCatalogService(db).source_games(imported.source_id, limit=10).items
            search = GameSearchService(db).search(GameSearchQuery(source_id=imported.source_id, limit=10))
            if (
                source_record is None or source_record.game_count != 1
                or source_record.source_sha256 != digest
                or len(game_rows) != 1 or len(search.items) != 1
            ):
                raise LawfulCorpusError("historical original endgame study did not survive Library search/restart")
            saved = db.get_game(game_rows[0].game_id)
            if saved is None:
                raise LawfulCorpusError("stored historical composed study missing")
            parsed = parse_games(str(saved["pgn_text"]))
            db_equal = _pgn_signature(tuple(parsed)) == start
            replay = LibraryImportService(db).import_games(
                games, source_name="idempotent 1921 historical study",
                source_format="PGN", source_sha256=digest.upper(),
            )
            if not replay.reused:
                raise LawfulCorpusError("historical study repeated import is not idempotent")
            db.verify_integrity()
    return {
        "schema": "acs-section39-historical-reti-original-study-v1",
        "source_id": SOURCE_ID,
        "source_sha256": digest, "source_bytes": len(raw),
        "actual_importer": "acs.pgn_roundtrip, acs.chesscore.Board, acs.library_import_service, acs.acsdb",
        "historical_composer": "Richard Reti", "historical_composition_year": 1921,
        "bilingual_english_ukrainian": True,
        "real_source_read": True, "mocked": False,
        "original_fen": ORIGINAL_FEN, "canonical_replayed_san_plies": len(positions)-1,
        "expected": "Original legal 1921 study FEN, 11 SAN plies, bilingual comments, annotated PGN export, source search, restart and idempotence",
        "actual": {
            "full_game_tree_pgn_reimport_equal": pgn_equal,
            "full_game_tree_acsdb_restart_equal": db_equal,
            "source_search_count": 1, "original_annotation_languages": ["uk", "en"],
        },
        "qualification": "PASS" if pgn_equal and db_equal else "FAIL",
        "section39_terminal_done": False,
    }


def main() -> None:
    REPORT.unlink(missing_ok=True)
    head = _source_head()
    result = qualify_original_reti_study()
    result["source_commit_sha"] = head
    temp = REPORT.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8")
        os.replace(temp, REPORT)
    finally:
        temp.unlink(missing_ok=True)
    if result["qualification"] != "PASS":
        raise LawfulCorpusError("real Réti study annotation/variation semantic PGN or Library restart lost structure")
    print(json.dumps({
        "source_commit_sha": head,
        "historical_original_study_plies": result["canonical_replayed_san_plies"],
        "semantic_verdict": result["qualification"],
        "section39_done": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
