from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import tempfile

from acs.acsdb import AcsDatabase
from acs.cbv_extractor import ExternalCbvExtractorConfig
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig, decode_chessbase_external
from acs.chessbase_library_import import ChessBaseLibraryImportService
from acs.chesscore import Board
from acs.game_identity import same_game_record, same_game_tree
from acs.gametree import PgnGame, parse_games
from acs.gametree_legality import validate_game_legality
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.search_service import GameSearchQuery, GameSearchService

LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
TWIC_EXPECTED_GAMES = 6117
_REQUIRED_PROMOTIONS = ("Q", "R", "B", "N")


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


def _decoder_config() -> ExternalChessBaseDecoderConfig:
    bridge = Path(_env("LIBCBH_BRIDGE"))
    return ExternalChessBaseDecoderConfig(
        bridge,
        expected_backend_commit=LIBCBH_COMMIT,
        timeout_seconds=180,
        library_directory=bridge.parent,
    )


def _cbv_config() -> ExternalCbvExtractorConfig:
    return ExternalCbvExtractorConfig(
        Path(_env("UNCBV_BINARY")),
        expected_backend_sha256=_env("UNCBV_BINARY_SHA256"),
        timeout_seconds=300,
        max_source_bytes=64 * 1024 * 1024,
        max_extracted_bytes=256 * 1024 * 1024,
    )


def _read_games(path: Path) -> tuple[PgnGame, ...]:
    return tuple(parse_games(path.read_text(encoding="utf-8-sig")))


def _game_events(game: PgnGame) -> Counter[str]:
    report = validate_game_legality(game)
    if not report.complete:
        details = [f"{issue.code.value}:{issue.san or ''}" for issue in report.issues]
        raise AssertionError(f"canonical legality rejected oracle/stored game: {details[:8]}")

    events: Counter[str] = Counter()
    for projection in report.moves:
        board = Board(projection.fen_before)
        move = board.parse_move(projection.san_source)
        canonical = board.san(move)
        if board.push(move) != canonical:
            raise AssertionError("canonical Board SAN changed during the same move commit")
        if board.fen() != projection.fen_after:
            raise AssertionError("canonical Board replay diverged from legality projection")

        capture = move.en_passant or Board(projection.fen_before).board[move.to] is not None
        if move.promotion:
            events[f"promotion_{move.promotion}"] += 1
            if capture:
                events["promotion_capture"] += 1
            if canonical.endswith("+"):
                events["promotion_check"] += 1
            if canonical.endswith("#"):
                events["promotion_mate"] += 1
        if move.en_passant:
            events["en_passant"] += 1
        if move.castle:
            events["castling"] += 1
        if canonical.endswith("+"):
            events["check"] += 1
        if canonical.endswith("#"):
            events["mate"] += 1
    return events


def _coverage(games: tuple[PgnGame, ...]) -> tuple[Counter[str], dict[str, int], int]:
    counts: Counter[str] = Counter()
    first_index: dict[str, int] = {}
    max_mainline_plies = 0
    for index, game in enumerate(games):
        max_mainline_plies = max(max_mainline_plies, len(game.line.moves))
        game_counts = _game_events(game)
        counts.update(game_counts)
        for key, value in game_counts.items():
            if value and key not in first_index:
                first_index[key] = index
    return counts, first_index, max_mainline_plies


def _selected_indices(first_index: dict[str, int], game_count: int) -> tuple[int, ...]:
    selected = {0, game_count - 1}
    selected.update(first_index.values())
    return tuple(sorted(index for index in selected if 0 <= index < game_count))


def _rows_for_source(database: AcsDatabase, source_id: int):
    return database.conn.execute(
        "SELECT id, source_index, pgn_text FROM games WHERE source_id=? ORDER BY source_index",
        (source_id,),
    ).fetchall()


def _verify_selected_roundtrip(
    database: AcsDatabase,
    source_id: int,
    reference: tuple[PgnGame, ...],
    indices: tuple[int, ...],
    export_path: Path,
) -> None:
    rows = _rows_for_source(database, source_id)
    if len(rows) != len(reference):
        raise AssertionError(f"Library game count mismatch: {len(rows)} != {len(reference)}")
    if [int(row["source_index"]) for row in rows] != list(range(len(reference))):
        raise AssertionError("Library source_index sequence is not contiguous")

    selected: list[PgnGame] = []
    for index in indices:
        stored = parse_games(str(rows[index]["pgn_text"]))[0]
        if not same_game_tree(stored, reference[index]):
            raise AssertionError(f"stored GameTree mismatch at source_index={index}")
        if _game_events(stored) != _game_events(reference[index]):
            raise AssertionError(f"stored rare-move semantics mismatch at source_index={index}")
        selected.append(stored)

    save_pgn_atomic(export_path, tuple(selected))
    reopened = tuple(open_pgn(export_path).games)
    if len(reopened) != len(selected):
        raise AssertionError("PGN export/reopen count mismatch")
    for before, after in zip(selected, reopened):
        if not same_game_record(before, after):
            raise AssertionError("PGN export/reopen changed a selected canonical game record")
        if _game_events(before) != _game_events(after):
            raise AssertionError("PGN export/reopen changed rare-move semantics")


def _require_combined_coverage(cbh: Counter[str], cbv: Counter[str]) -> None:
    combined = cbh + cbv
    missing: list[str] = []
    for piece in _REQUIRED_PROMOTIONS:
        if combined[f"promotion_{piece}"] < 1:
            missing.append(f"promotion_{piece}")
    for key in (
        "promotion_capture",
        "en_passant",
        "castling",
        "check",
        "mate",
    ):
        if combined[key] < 1:
            missing.append(key)
    if combined["promotion_check"] + combined["promotion_mate"] < 1:
        missing.append("promotion_check_or_mate")
    if missing:
        raise AssertionError(
            "lawful real CBH/CBV corpora do not cover required standard semantics: "
            + ", ".join(missing)
            + "; combined_counts="
            + json.dumps(dict(sorted(combined.items())), sort_keys=True)
        )


def main() -> int:
    promotions_dir = Path(_env("LIBCBH_PROMOTIONS_DIR"))
    cbh_source = promotions_dir / "ManyPromotions.cbh"
    cbh_oracle_path = promotions_dir / "Promotions.pgn"
    cbv_source = Path(_env("UNCBV_FIXTURE"))
    cbv_oracle_path = Path(_env("TWIC_PGN_FIXTURE"))
    for path in (cbh_source, cbh_oracle_path, cbv_source, cbv_oracle_path):
        if not path.is_file():
            raise AssertionError(f"required real corpus file is missing: {path.name}")

    cbh_reference = _read_games(cbh_oracle_path)
    cbh_decoded = decode_chessbase_external(cbh_source, _decoder_config())
    if cbh_decoded.warnings:
        raise AssertionError(f"real CBH decoder warnings: {cbh_decoded.warnings}")
    if len(cbh_decoded.games) != len(cbh_reference):
        raise AssertionError("real CBH decoded/reference game count mismatch")
    for index, (actual, expected) in enumerate(zip(cbh_decoded.games, cbh_reference)):
        if not same_game_tree(actual, expected):
            raise AssertionError(f"real CBH GameTree mismatch at source_index={index}")
        if _game_events(actual) != _game_events(expected):
            raise AssertionError(f"real CBH rare-move semantics mismatch at source_index={index}")

    cbh_counts, cbh_first, cbh_max_plies = _coverage(cbh_reference)
    cbv_reference = tuple(open_pgn(cbv_oracle_path).games)
    if len(cbv_reference) != TWIC_EXPECTED_GAMES:
        raise AssertionError(f"TWIC oracle count mismatch: {len(cbv_reference)} != {TWIC_EXPECTED_GAMES}")
    cbv_counts, cbv_first, cbv_max_plies = _coverage(cbv_reference)
    _require_combined_coverage(cbh_counts, cbv_counts)
    if max(cbh_max_plies, cbv_max_plies) < 250:
        raise AssertionError("real corpus lacks the required long-game stress coverage")

    with tempfile.TemporaryDirectory(prefix="accessible-chess-rare-moves-") as temporary:
        root = Path(temporary)
        database_path = root / "rare-moves.acsdb"
        database = AcsDatabase(database_path)
        try:
            service = ChessBaseLibraryImportService(database, _decoder_config(), _cbv_config())
            cbh_report = service.import_database(cbh_source)
            if cbh_report.decoded_game_count != len(cbh_reference) or cbh_report.imported_game_count != len(cbh_reference):
                raise AssertionError("CBH Library publication count mismatch")
            cbv_report = service.import_database(cbv_source)
            if cbv_report.decoded_game_count != TWIC_EXPECTED_GAMES or cbv_report.imported_game_count != TWIC_EXPECTED_GAMES:
                raise AssertionError("CBV Library publication count mismatch")
            if cbh_report.warning_count or cbv_report.warning_count:
                raise AssertionError("real rare-move corpus import emitted warnings")

            cbh_indices = _selected_indices(cbh_first, len(cbh_reference))
            cbv_indices = _selected_indices(cbv_first, len(cbv_reference))
            _verify_selected_roundtrip(
                database,
                cbh_report.library_result.source_id,
                cbh_reference,
                cbh_indices,
                root / "cbh-selected.pgn",
            )
            _verify_selected_roundtrip(
                database,
                cbv_report.library_result.source_id,
                cbv_reference,
                cbv_indices,
                root / "cbv-selected.pgn",
            )

            probe_index = cbv_first.get("castling", 0)
            probe_game = cbv_reference[probe_index]
            probe_player = probe_game.tags.get("White") or probe_game.tags.get("Black") or ""
            if not probe_player.strip():
                raise AssertionError("selected real CBV game lacks a searchable player")
            page = GameSearchService(database).search(
                GameSearchQuery(player=probe_player, source_id=cbv_report.library_result.source_id, limit=100)
            )
            if not any(item.source_index == probe_index for item in page.items):
                raise AssertionError("Library Search did not return the selected rare-move CBV game")

            quick_check = str(database.conn.execute("PRAGMA quick_check").fetchone()[0])
            if quick_check.lower() != "ok":
                raise AssertionError(f"ACSDB quick_check failed: {quick_check}")
            cbh_source_sha256 = cbh_report.source_sha256
            cbv_source_sha256 = cbv_report.source_sha256
            cbh_source_id = cbh_report.library_result.source_id
            cbv_source_id = cbv_report.library_result.source_id
        finally:
            database.close()

        reopened = AcsDatabase(database_path)
        try:
            if str(reopened.conn.execute("PRAGMA quick_check").fetchone()[0]).lower() != "ok":
                raise AssertionError("reopened ACSDB quick_check failed")
            expected_total = len(cbh_reference) + len(cbv_reference)
            actual_total = int(reopened.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
            if actual_total != expected_total:
                raise AssertionError(f"reopened ACSDB count mismatch: {actual_total} != {expected_total}")
        finally:
            reopened.close()

    summary = {
        "authority_sha": os.environ.get("V2_AUTHORITY_SHA"),
        "libcbh_commit": LIBCBH_COMMIT,
        "cbh_corpus": "rolandlo/libcbh gtest/ManyPromotions",
        "cbh_games": len(cbh_reference),
        "cbh_source_sha256": cbh_source_sha256,
        "cbh_counts": dict(sorted(cbh_counts.items())),
        "cbh_first_indices": dict(sorted(cbh_first.items())),
        "cbh_max_mainline_plies": cbh_max_plies,
        "cbh_source_id": cbh_source_id,
        "cbv_corpus": "TWIC 1134 via pinned antoyo/uncbv fixture",
        "cbv_games": len(cbv_reference),
        "cbv_source_sha256": cbv_source_sha256,
        "cbv_counts": dict(sorted(cbv_counts.items())),
        "cbv_first_indices": dict(sorted(cbv_first.items())),
        "cbv_max_mainline_plies": cbv_max_plies,
        "cbv_source_id": cbv_source_id,
        "combined_counts": dict(sorted((cbh_counts + cbv_counts).items())),
        "canonical_board_revalidation": "PASS",
        "library_persistence": "PASS",
        "library_search": "PASS",
        "pgn_export_reopen": "PASS",
        "acsdb_reopen": "PASS",
        "chess960_rules_added": False,
    }
    Path("real-cbh-rare-moves-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("CBH_RARE_MOVES_EVIDENCE=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
