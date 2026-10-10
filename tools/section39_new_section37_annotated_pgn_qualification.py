"""Section 39 continuous qualification of the newly added Section 37 real PGN.

Use the already cataloged Lichess CC0 original annotated four-game source.
No mock corpus, no new parser and no assumption that 2200+ online player
rating implies an over-the-board GM title. This also tests the same source
which Section 40 uses for its ready-to-open offline Library.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from acs.acsdb import AcsDatabase
from acs.gametree import parse_games
from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog, read_verified_source_snapshot
from acs.library_import_service import LibraryImportService
from acs.library_source_service import LibrarySourceCatalogService
from acs.pgn_roundtrip import parse_pgn_text
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.search_service import GameSearchService, GameSearchQuery
from tools.revised_section37_external_book_acquisition import ROOT, _exact_head as _source_head
from tools.section39_pgn_semantic_signature import _pgn_signature

SOURCE = "lichess_cc0_high_level_4_original_annotated_games"
REPORT = ROOT / "section39-new-section37-annotated-pgn-qualification.json"


def qualify_new_section37_original(root: Path = ROOT) -> dict:
    original = {x["id"]: x for x in load_catalog(root / "docs/corpus/revised_sections37_40_sources.json")}
    entry = original.get(SOURCE)
    if not entry or (
        entry.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
        or entry.get("format") != "pgn"
        or not entry.get("license", "").startswith("CC0")
        or entry.get("redistribution") != "permitted"
    ):
        raise LawfulCorpusError("new Section 37 original annotated PGN corpus missing or unlicensed")
    raw = read_verified_source_snapshot(root / entry["local_source"], entry)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != entry["sha256"] or len(raw) != entry["indexed_bytes"]:
        raise LawfulCorpusError("new Section 37 original annotated PGN source identity mismatch")
    txt = raw.decode("utf-8", errors="strict")
    if (
        txt.count('[Event "') != 4
        or txt.count("[%eval ") < 60
        or txt.count("(") < 30
    ):
        raise LawfulCorpusError("new genuine annotated game source truncated or stripped")
    manifest = json.loads((root / entry["source_manifest"]).read_text(encoding="utf-8"))
    if (
        manifest.get("game_count") != 4
        or manifest.get("original_game_pgn_source_sha256") != digest
        or manifest.get("not_gm_title_claim") is not True
        or manifest.get("player_rating_is_not_FIDE_ELO") is not True
    ):
        raise LawfulCorpusError("original high-level game manifest source authority differs")
    games = tuple(parse_pgn_text(txt, strict=False))
    if len(games) != 4 or not all(g.line.moves for g in games):
        raise LawfulCorpusError("genuine four-game PGN parser did not preserve all games")
    for i, game in enumerate(games):
        game.source_index = i
    original_sig = _pgn_signature(games)
    with tempfile.TemporaryDirectory(prefix="acs39-real-advanced-") as tmp:
        work = Path(tmp)
        exported = work / "four-original-annotated-games.pgn"
        save_pgn_atomic(exported, games)
        reopened = tuple(open_pgn(exported).games)
        export_equal = _pgn_signature(reopened) == original_sig
        dbfile = work / "annotated-original.acsdb"
        with AcsDatabase(dbfile) as db:
            result = LibraryImportService(db).import_games(
                games,
                source_name="Section37: original Lichess annotated source",
                source_format="pgn",
                source_sha256=digest,
            )
            if result.game_count != 4 or result.reused or result.warning_count:
                raise LawfulCorpusError("genuine annotated PGN source did not import fully")
            db.verify_integrity()
        with AcsDatabase(dbfile) as db:
            source = LibrarySourceCatalogService(db).get_source(result.source_id)
            if source is None or source.game_count != 4 or source.source_sha256 != digest:
                raise LawfulCorpusError("original annotated source lost durable library provenance")
            games_page = LibrarySourceCatalogService(db).source_games(result.source_id, limit=8)
            if (
                len(games_page.items) != 4
                or any(item.source_index != i for i, item in enumerate(games_page.items))
            ):
                raise LawfulCorpusError("source game index lost upon database restart")
            searched = GameSearchService(db).search(
                GameSearchQuery(source_id=result.source_id, limit=8)
            )
            if len(searched.items) != 4:
                raise LawfulCorpusError("original Section37 annotated chess games not searchable")
            stored = []
            for row in games_page.items:
                entry_game = db.get_game(row.game_id)
                if entry_game is None:
                    raise LawfulCorpusError("stored original source game missing")
                parsed = parse_games(str(entry_game["pgn_text"]))
                if len(parsed) != 1:
                    raise LawfulCorpusError("stored original source PGN invalid")
                stored.append(parsed[0])
            db_equal = _pgn_signature(tuple(stored)) == original_sig
            db.verify_integrity()
    # Distinguish an actual semantic mismatch from a fake green CI. Keep
    # counts and qualified subset, and fail actual format qualification if lost.
    result_data = {
        "schema": "accessible-chess-section39-new-section37-annotated-source-v1",
        "source_id": SOURCE,
        "original_sha256": digest,
        "original_bytes": len(raw),
        "format": "PGN",
        "original_game_count": 4,
        "original_eval_annotations_minimum": 60,
        "original_rav_parentheses_minimum": 30,
        "real_source_read": True,
        "mocked": False,
        "actual_importer": "acs.pgn_roundtrip -> acs.pgn_service -> acs.library_import_service -> acs.acsdb",
        "expected": "four original annotated games, full tags/moves/NAG/RAV/comments, export, SQLite restart, source browse/search",
        "actual": {
            "imported_games": 4,
            "search_result_games": 4,
            "source_indexes": [0, 1, 2, 3],
            "full_game_tree_equal_after_pgn_export": export_equal,
            "full_game_tree_equal_after_acsdb_restart": db_equal,
        },
        "qualification": "PASS" if export_equal and db_equal else "FAIL",
        "section39_terminal_done": False,
    }
    return result_data


def main() -> None:
    REPORT.unlink(missing_ok=True)
    head = _source_head()
    evidence = qualify_new_section37_original()
    evidence["source_commit_sha"] = head
    temp = REPORT.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2)+"\n",
                        encoding="utf-8")
        os.replace(temp, REPORT)
    finally:
        temp.unlink(missing_ok=True)
    if evidence["qualification"] != "PASS":
        raise LawfulCorpusError("four real annotated Section 37 games lost semantics in PGN or ACSDB")
    print(json.dumps({
        "source_commit_sha": head,
        "actual_source_id": evidence["source_id"],
        "original_game_count": evidence["original_game_count"],
        "semantic_verdict": evidence["qualification"],
        "section39_done": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
