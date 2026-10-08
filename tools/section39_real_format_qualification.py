"""Section 39: source-bound qualification of the one canonical format implementation.

All source bytes come from the established Section 37 corpus registry.  This
tool does not create another parser, chess authority, or product importer.
A PASS is a performed readback, not a claim of full-format acceptance.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from acs.acsdb import AcsDatabase
from acs.book_text_import import import_text_book
from acs.gametree import CanonicalPgnGameFramer, parse_games
from acs.lawful_corpus_registry import (
    LawfulCorpusError, load_catalog, read_verified_source_snapshot,
    read_verified_zip_member,
)
from acs.library_import_service import LibraryImportService
from acs.library_source_service import LibrarySourceCatalogService
from acs.pgn_roundtrip import parse_pgn_text
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.position_editor import PositionState
from tools.revised_sections37_38_offline_manifest import ROOT, _source_head, build_manifest


FORMATS = (
    "FEN", "SAN", "EPD", "PGN", "ACSDB", "EPUB", "HTML", "TXT",
    "Markdown", "DOCX", "PDF", "CBH", "CBV", "CBF", "2CBH", "CBONE",
)
PGN_ID = "stockfish_2moves_v2_pgn_zip"
FEN_ID = "stockfish_startpos_epd_zip"
TXT_ID = "gitenberg_capablanca_33870_original_txt"
REPORT_NAME = "section39-real-format-qualification.json"
STATUS = frozenset({"PASS", "PARTIAL", "BLOCKED", "FAIL", "UNSUPPORTED"})

# These are candidates for qualification, not claims of format support.
SOURCE_IDS = {
    "FEN": (FEN_ID, "original_epd2doc_opening_fen"),
    "SAN": (PGN_ID,),
    "EPD": ("stockfish_frc_openings_epd_zip", "original_epd2doc_7men_human_epd"),
    "PGN": (PGN_ID, "lichess_standard_rated_2013_01"),
    "ACSDB": (PGN_ID,),
    "EPUB": ("capablanca_chess_fundamentals_epub3",),
    "HTML": ("gutenberg_chess_strategy_lasker",),
    "TXT": (TXT_ID, "gutenberg_blue_book_chess_staunton"),
    "Markdown": ("original_gpl_chastity_chess_chapters_markdown",),
    "DOCX": (),
    "PDF": ("cc0_capablanca_open_pdf_original_source",),
    "CBH": ("libcbh_gpl_original_annotation_cbh_family",),
    "CBV": ("chessbase_official_free_rossolimo_cbv_sample",),
    "CBF": ("chessbase_official_cbf_cbi_format_external_gap",),
    "2CBH": ("chessbase_official_2cbh_format_external_gap",),
    "CBONE": ("chessbase_official_cbone_format_external_gap",),
}


def _sample_real_pgn(records: dict) -> tuple[tuple, str]:
    item = records[PGN_ID]
    path = ROOT / item["local_source"]
    # One read of the pinned archive, no source path swap or unbounded extract.
    raw = read_verified_zip_member(
        path, item, expected_member=item["zip_member"],
        max_unpacked_bytes=item["max_unpacked_bytes"],
    )
    framer = CanonicalPgnGameFramer(max_frame_bytes=256 * 1024)
    frames: list[str] = []
    for line in raw.decode("utf-8-sig", errors="strict").splitlines():
        completed = framer.feed_line(line)
        if completed is not None:
            frames.append(completed.text)
            if len(frames) == 24:
                break
    if len(frames) != 24:
        raise LawfulCorpusError("original PGN lacks 24 complete frames")
    pgn_text = "\n".join(frames)
    games = parse_pgn_text(pgn_text, strict=False)
    if len(games) != 24 or not all(game.line.moves for game in games):
        raise LawfulCorpusError("canonical PGN sample parser lost real games")
    for index, game in enumerate(games):
        game.source_index = index
    return tuple(games), pgn_text


def _pgn_signature(games: tuple) -> tuple:
    """Compare full representable GameTree structure, not only top-level SAN.

    Annotations, language-visible comments, NAG and recursive sibling RAV
    must survive every PGN -> export -> PGN/ACSDB reimport pathway.  Move
    numbering is intentionally omitted as surface notation, not move meaning.
    """
    def comments(values):
        return tuple((c.text, c.style.value) for c in values)

    def line_semantics(line):
        return (
            comments(line.leading_comments),
            tuple(
                (
                    move.san,
                    tuple(move.nags),
                    comments(move.comments_before),
                    comments(move.comments_after),
                    tuple(line_semantics(child) for child in move.variations),
                )
                for move in line.moves
            ),
            comments(line.trailing_comments),
            line.result,
        )

    return tuple(
        (tuple(sorted(game.tags.items())), line_semantics(game.line))
        for game in games
    )


def _genuine_readbacks(records: dict) -> dict:
    outcomes: dict[str, dict] = {}

    fen_item = records[FEN_ID]
    raw_fen = read_verified_zip_member(
        ROOT / fen_item["local_source"], fen_item,
        expected_member=fen_item["zip_member"],
        max_unpacked_bytes=fen_item["max_unpacked_bytes"],
    )
    fen = raw_fen.decode("utf-8-sig", errors="strict").splitlines()[0].strip()
    if len(fen.split()) != 6 or PositionState.from_fen(fen).to_fen() != fen:
        raise LawfulCorpusError("actual original six-field FEN failed canonical readback")
    if PositionState.from_fen(PositionState.from_fen(fen).to_fen()).to_fen() != fen:
        raise LawfulCorpusError("canonical FEN reimport failed")
    outcomes["FEN"] = {
        "source_id": FEN_ID, "importer": "acs.position_editor.PositionState",
        "read": "PASS", "write": "PASS", "roundtrip": "PASS",
        "real_source_read": True, "positions": 1, "semantic_loss": 0,
        "scope": "one original six-field FEN inside upstream EPD-named ZIP",
    }

    original_games, pgn_text = _sample_real_pgn(records)
    signature = _pgn_signature(original_games)
    with tempfile.TemporaryDirectory(prefix="accessible-chess-section39-") as temporary:
        root = Path(temporary)
        output = root / "verified-pgn-roundtrip.pgn"
        save_pgn_atomic(output, original_games)
        reopened = tuple(open_pgn(output).games)
        if _pgn_signature(reopened) != signature:
            raise LawfulCorpusError("real original PGN lost tags, moves or result")
        # A restart must open the actual committed ACSDB bytes, not the
        # still-live SQLite connection from its import transaction.
        database_path = root / "real-pgn-derived.acsdb"
        derivative_digest = hashlib.sha256(pgn_text.encode("utf-8")).hexdigest()
        with AcsDatabase(database_path) as db:
            result = LibraryImportService(db).import_games(
                original_games,
                source_name="section39:original-stockfish:24-frames",
                source_format="pgn",
                source_sha256=derivative_digest,
            )
            if result.game_count != 24 or result.warning_count:
                raise LawfulCorpusError("canonical ACSDB real-game import was partial")
            db.verify_integrity()
        with AcsDatabase(database_path) as db:
            catalog = LibrarySourceCatalogService(db)
            source = catalog.get_source(result.source_id)
            if source is None or source.game_count != 24 or source.source_sha256 != derivative_digest:
                raise LawfulCorpusError("ACSDB source metadata lost after restart")
            rows = catalog.source_games(result.source_id, limit=24).items
            if len(rows) != 24:
                raise LawfulCorpusError("ACSDB lost original source game index")
            stored = []
            for row in rows:
                saved = db.get_game(row.game_id)
                if saved is None:
                    raise LawfulCorpusError("ACSDB game vanished after restart")
                games = parse_games(str(saved["pgn_text"]))
                if len(games) != 1:
                    raise LawfulCorpusError("stored PGN cannot be reopened")
                stored.extend(games)
            if _pgn_signature(tuple(stored)) != signature:
                raise LawfulCorpusError("ACSDB reimport lost PGN semantic moves/tags")
            db.verify_integrity()
    outcomes["PGN"] = {
        "source_id": PGN_ID, "importer": "acs.pgn_roundtrip / acs.pgn_service",
        "read": "PASS", "write": "PASS", "roundtrip": "PASS",
        "real_source_read": True, "games": 24, "semantic_loss": 0,
        "scope": "first 24 complete genuine upstream opening games, not full annotated PGN coverage",
    }
    outcomes["ACSDB"] = {
        "source_id": PGN_ID, "importer": "acs.library_import_service / acs.acsdb",
        "read": "PASS", "write": "PASS", "roundtrip": "PARTIAL",
        "real_source_read": False, "games": 24, "semantic_loss": 0,
        "scope": "newly generated database derived from 24 original PGN games; no independent external ACSDB",
    }

    item = records[TXT_ID]
    raw_book = read_verified_source_snapshot(ROOT / item["local_source"], item)
    book = import_text_book(
        raw_book, source_name="gitenberg_capablanca_33870.txt",
        source_format="txt", title="Chess Fundamentals",
        author="José Raúl Capablanca", language="en",
    )
    if book.source_sha256 != hashlib.sha256(raw_book).hexdigest() or not book.document.blocks:
        raise LawfulCorpusError("actual original chess book semantic readback failed")
    outcomes["TXT"] = {
        "source_id": TXT_ID, "importer": "acs.book_text_import.import_text_book",
        "read": "PASS", "write": "BLOCKED", "roundtrip": "BLOCKED",
        "real_source_read": True, "semantic_blocks": len(book.document.blocks),
        "scope": "genuine original book; no lossless TXT export demonstrated",
    }
    # SAN strings are exercised inside original PGN games, not an independent
    # externally sourced SAN document. Do not promote this to a full PASS.
    outcomes["SAN"] = {
        "source_id": PGN_ID, "importer": "acs.pgn_roundtrip.parse_pgn_text",
        "read": "PARTIAL", "write": "PARTIAL", "roundtrip": "PARTIAL",
        "real_source_read": False, "moves": sum(len(g.line.moves) for g in original_games),
        "scope": "embedded SAN only; no independent SAN-file qualification",
    }
    return outcomes


def build_report() -> dict:
    source_manifest = build_manifest()
    catalog = load_catalog()
    records = {item["id"]: item for item in catalog}
    receipt_by_id = {r["source_id"]: r for r in source_manifest["sources"]}
    readbacks = _genuine_readbacks(records)
    rows = []
    for name in FORMATS:
        candidates = SOURCE_IDS[name]
        if any(s not in records for s in candidates):
            raise LawfulCorpusError("format matrix references a missing original source")
        readback = readbacks.get(name)
        row = {
            "format": name, "source_ids": list(candidates),
            "qualification": "BLOCKED",
            "read": "BLOCKED", "write": "BLOCKED", "roundtrip": "BLOCKED",
            "actual_importer": None, "source_kind": "NO_EXECUTED_REAL_FILE_READBACK",
            "expected": "genuine format-specific file and end-to-end semantic comparison",
            "actual": "not executed for this format",
            "coverage": "NO_PROOF",
        }
        if readback:
            row.update({
                "qualification": (
                    "PASS" if name in {"FEN", "PGN"} else "PARTIAL"
                ),
                "read": readback["read"], "write": readback["write"],
                "roundtrip": readback["roundtrip"],
                "actual_importer": readback["importer"],
                "qualified_source_id": readback["source_id"],
                "source_kind": (
                    "PINNED_GENUINE_UPSTREAM_BYTES"
                    if readback["real_source_read"]
                    else "DERIVED_FROM_PINNED_UPSTREAM_PGN"
                ),
                "actual": {k: v for k, v in readback.items()
                           if k not in {"read", "write", "roundtrip", "importer", "source_id"}},
                "coverage": "EXECUTED_BOUNDED_SLICE",
            })
        rows.append(row)
    if len(rows) != 16 or {r["format"] for r in rows} != set(FORMATS):
        raise LawfulCorpusError("required sixteen-format matrix incomplete")
    for row in rows:
        if row["qualification"] not in STATUS:
            raise LawfulCorpusError("invalid capability verdict")
        if row["qualification"] == "PASS" and row["source_kind"] != "PINNED_GENUINE_UPSTREAM_BYTES":
            raise LawfulCorpusError("real-file PASS cannot arise from synthetic data")
    receipts = []
    for item in catalog:
        current = receipt_by_id[item["id"]]
        # A candidate source ID does not prove this particular source was
        # opened. Only the exact original ID used by the executed readback,
        # with the separately pinned observed original bytes, may be PASS.
        qualified = next(
            (r for r in rows
             if r["qualification"] == "PASS"
             and isinstance(r["actual"], dict)
             and r.get("qualified_source_id") == item["id"]
             and current["actual_sha256"] is not None
             and current["actual_sha256"] == item.get("sha256")
             and current["actual_bytes"] == item.get("indexed_bytes")), None
        )
        receipts.append({
            "source_id": item["id"], "source_format": item["format"],
            "expected_sha256": item.get("sha256"),
            "actual_sha256": current["actual_sha256"],
            "expected_bytes": item.get("indexed_bytes"),
            "actual_bytes": current["actual_bytes"],
            "acquisition": item["acquisition"],
            "status": (
                "PASS" if qualified else
                "PARTIAL" if current["actual_sha256"] is not None else "BLOCKED"
            ),
            "actual_importer": qualified["actual_importer"] if qualified else None,
            "note": (
                "performed bounded format readback"
                if qualified else "verified byte inventory only, or no executed readback"
            ),
        })
    return {
        "schema": "accessible-chess-section39-real-format-qualification-v1",
        "section": 39,
        "terminal_done": False,
        "format_count": len(rows),
        "sources_count": len(receipts),
        "full_matrix_completed": False,
        "manual_nvda_verified": False,
        "windows_packaged_verified": False,
        "format_rows": rows,
        "source_receipts": receipts,
        "evidence": {
            "genuine_source_bytes": True,
            "mocked_or_derived_receipts_separated": True,
            "ci_run_id": os.environ.get("GITHUB_RUN_ID"),
            "ci_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "ci_completion": "NOT_ATTESTED_BY_THIS_REPORT",
            "required_follow_up": [
                "Sections 37-38 full real-source integration and exact CI closure",
                "all supported importers and formats tested using actual third-party original files",
                "annotations/RAV/NAG/Chess960 and encoding/size/recovery matrices",
                "loss metrics, Windows packaged keyboard and accessibility checks",
            ],
        },
    }


def main() -> None:
    destination = ROOT / REPORT_NAME
    destination.unlink(missing_ok=True)  # failed rerun must not leave stale PASS evidence
    head = _source_head()
    report = build_report()
    report["source_commit_sha"] = head
    temporary = destination.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({
        "source_commit_sha": head, "format_count": report["format_count"],
        "qualified_real_format_slices": sum(r["qualification"] == "PASS"
                                             for r in report["format_rows"]),
        "section39_done": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
