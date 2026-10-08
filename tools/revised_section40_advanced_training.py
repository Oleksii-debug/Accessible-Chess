"""Canonical Advanced Training content for Section 40, from pinned real CC0 puzzles.

Only BookDocument, existing chess rules and verified source provenance are used.
Lichess puzzle ratings are NOT FIDE ELO; a puzzle has an initial opponent move.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from acs.bookdocument import BookDocument, Exercise, Heading, Paragraph
from acs.chesscore import Board, parse_sq
from acs.lawful_corpus_registry import (
    LawfulCorpusError, load_catalog, read_verified_source_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "lichess_cc0_advanced_16_original_derived"
_BOOK_PATH = "books/advanced-lichess-16-middlegame-endgame.json"
_TRAINING_PATH = "training/advanced-lichess-16-middlegame-endgame.json"
_LICENSE_SHA = "a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499"


def _move(board: Board, uci: str) -> None:
    if (type(uci) is not str or len(uci) not in (4, 5)
        or not uci[:2].isascii() or not uci[2:4].isascii()):
        raise LawfulCorpusError("advanced puzzle move syntax invalid")
    start, end = parse_sq(uci[:2]), parse_sq(uci[2:4])
    promotion = uci[4].upper() if len(uci) == 5 else None
    matches = [m for m in board.legal_moves()
               if m.frm == start and m.to == end and m.promotion == promotion]
    if len(matches) != 1:
        raise LawfulCorpusError("advanced puzzle move illegal on canonical board")
    board.push(matches[0])


def build_advanced_training(*, root: Path = ROOT) -> tuple[dict[str, bytes], list[dict]]:
    entries = load_catalog(root / "docs/corpus/revised_sections37_40_sources.json")
    matching = [entry for entry in entries if entry.get("id") == SOURCE_ID]
    if len(matching) != 1:
        raise LawfulCorpusError("genuine advanced puzzle source missing")
    record = matching[0]
    if (record.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
        or not str(record.get("license", "")).startswith("CC0")
        or not str(record.get("redistribution", "")).startswith("permitted")
        or record.get("license_sha256") != _LICENSE_SHA):
        raise LawfulCorpusError("genuine advanced source provenance or rights unverified")
    read_verified_source_snapshot(
        root / record["license_source"],
        {"sha256": _LICENSE_SHA, "max_bytes": 1024 * 1024},
    )
    raw = read_verified_source_snapshot(root / record["local_source"], record)
    payload = json.loads(raw)
    if (type(payload) is not dict
        or payload.get("schema") != "accessible-chess-licensed-advanced-training-original-sample-v1"
        or payload.get("retained_count") != 16
        or payload.get("composed_endgame_studies") is not False
        or type(payload.get("puzzles")) is not list
        or len(payload["puzzles"]) != 16):
        raise LawfulCorpusError("genuine advanced puzzle subset invalid")
    tasks = []
    blocks = [
        Heading(text="Складні тактичні задачі Lichess: 2200+",
                level=1, block_id="advanced-lichess-16-title",
                source_anchor="advanced:heading"),
        Paragraph(text=(
            "16 справжніх задач із відкритого CC0-корпусу Lichess. "
            "Рейтинг 2200+ означає складність задачі на Lichess, а не FIDE Elo, "
            "спортивний розряд або гросмейстерське звання. "
            "Кожна позиція показана ПІСЛЯ першого ходу суперника. "
            "Підказку та відповідь відкривайте лише після власної спроби."
        ), block_id="advanced-lichess-16-intro", source_anchor="advanced:intro"),
    ]
    ids = set()
    for index, p in enumerate(payload["puzzles"], 1):
        if type(p) is not dict:
            raise LawfulCorpusError("advanced puzzle record invalid")
        ident, rating = p.get("puzzle_id"), p.get("rating")
        raw_moves = p.get("uci_moves_with_opponent_first")
        themes = p.get("themes")
        if (type(ident) is not str or len(ident) not in range(5, 9)
            or not ident.isalnum() or ident in ids
            or type(rating) is not int or not 2200 <= rating <= 5000
            or type(raw_moves) is not str or type(themes) is not list
            or not themes or not all(type(t) is str for t in themes)):
            raise LawfulCorpusError("advanced puzzle metadata failed qualification")
        ids.add(ident)
        moves = raw_moves.split()
        if not 2 <= len(moves) <= 128:
            raise LawfulCorpusError("advanced puzzle continuation invalid")
        board = Board(p["fen_before_opponent_move"])
        _move(board, moves[0])  # Actual solver position, not initial stale FEN
        solver_fen = board.fen()
        candidate = moves[1]
        for uci in moves[1:]:
            _move(board, uci)  # Validate the entire ORIGINAL solution tree
        task = {
            "puzzle_id": ident,
            "puzzle_rating_lichess_not_fide": rating,
            "themes": themes,
            "fen": solver_fen,
            "answer_uci": candidate,
            "full_solution_uci": moves[1:],
            "source_opponent_move_uci": moves[0],
            "source_game_url": p.get("game_url"),
            "source_id": SOURCE_ID,
        }
        tasks.append(task)
        blocks.append(Heading(
            text=f"Задача {index:02}: {', '.join(themes[:3])} — Lichess {rating}",
            level=2, block_id=f"advanced-puzzle-{ident}-heading",
            source_anchor=f"advanced:{ident}:heading",
        ))
        blocks.append(Exercise(
            fen=solver_fen,
            prompt=f"Знайдіть найкращий хід і розрахуйте варіант. Теми: {', '.join(themes)}.",
            answer_text=candidate,
            difficulty=f"Lichess puzzle {rating} (не FIDE)",
            block_id=f"advanced-puzzle-{ident}-exercise",
            source_anchor=f"advanced:{ident}:exercise",
        ))
    doc = BookDocument(
        title="16 складних тактичних задач: Lichess 2200+ (не FIDE Elo)",
        language="uk", author="Lichess original CC0 contributors",
        source_name=record.get("source_page", "Lichess CC0 historical source"),
        source_rights="CC0-1.0; real attributed source; Lichess ratings not FIDE",
        blocks=blocks,
    )
    doc_wire = json.dumps(doc.as_dict(), ensure_ascii=False,
                          sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    if BookDocument.from_dict(json.loads(doc_wire)).as_dict() != doc.as_dict():
        raise LawfulCorpusError("advanced canonical Books readback failed")
    training_wire = json.dumps({
        "schema_version": 1,
        "source_id": SOURCE_ID,
        "rating_system": "LICHESS_PUZZLE_RATING_NOT_FIDE",
        "composed_studies": False,
        "tasks": tasks,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    common = {
        "author": "Lichess CC0 original contributors",
        "language": "uk", "license": "CC0-1.0",
        "redistribution": "permitted; upstream source and rating notice preserved",
        "source_url": record.get("source_page"), "download_url": None,
        "repeat_download": "BUNDLED_OFFLINE",
    }
    rows = [
        dict(common, id="lichess_advanced_16_book", title=doc.title,
             genre="advanced tactics and positional calculation",
             format="BookDocument JSON", source_path=_BOOK_PATH,
             size_bytes=len(doc_wire), sha256=hashlib.sha256(doc_wire).hexdigest(),
             import_status="CANONICAL_BOOKDOCUMENT_ROUNDTRIP_PASS"),
        dict(common, id="lichess_advanced_16_training",
             title="16 genuine puzzle positions after opponent's move",
             genre="advanced Training puzzles",
             format="Training JSON", source_path=_TRAINING_PATH,
             size_bytes=len(training_wire), sha256=hashlib.sha256(training_wire).hexdigest(),
             import_status="CANONICAL_CHESS_POSITION_AND_COMPLETE_SOLUTION_PASS"),
    ]
    return {_BOOK_PATH: doc_wire, _TRAINING_PATH: training_wire}, rows
