from __future__ import annotations

"""Evidence-only real corpus oracle for the final-formats Books composition.

This script implements no chess, PGN, database, Book, engine or UI semantics.
It drives the exact existing owner boundaries after CI overlays them onto the
current V2 final-formats authority.
"""

import hashlib
import io
import json
from pathlib import Path
import random
import tempfile
from urllib.request import Request, urlopen

import zstandard

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_board_workflow import BookBoardMode, BookBoardWorkflow
from acs.book_game_content import BookGameSource
from acs.book_library_game_lookup import AcsdbBookGameLookup
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument, Game, Heading, ListBlock, Paragraph
from acs.bookreader import BookReader
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.gametree import serialize_game
from acs.library_import_service import LibraryImportService
from acs.pgn_roundtrip import parse_pgn_text
from acs.search_service import GameSearchQuery, GameSearchService


CORPUS_NAME = "lichess-standard-rated-2013-01"
CORPUS_URL = "https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst"
CORPUS_LICENSE = "CC0"
CORPUS_PUBLISHED_GAMES = 121_332
CORPUS_SHA256 = "aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635"
DOWNLOAD_LIMIT_BYTES = 32 * 1024 * 1024
DOWNLOAD_CHUNK = 1024 * 1024
SUBSET_GAMES = 128
SEARCH_LIMIT = 128
RANDOM_SEED = 20260831
SUMMARY_PATH = Path("v2-books-final-formats-composition-summary.json")


class _UnusedEngine:
    def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
        raise AssertionError("real composition oracle must not invoke engine analysis")

    def close(self) -> None:
        return None


def _scan_comment_state(line: str, inside_brace: bool) -> bool:
    for character in line:
        if inside_brace:
            if character == "}":
                inside_brace = False
            continue
        if character == ";":
            break
        if character == "{":
            inside_brace = True
    return inside_brace


def _write_complete_game_subset(source: io.TextIOBase, destination: Path, limit: int) -> int:
    current: list[str] = []
    inside_brace = False
    written = 0
    with destination.open("w", encoding="utf-8", newline="\n") as output:
        for line in source:
            if not inside_brace and line.startswith('[Event "') and current:
                record = "".join(current).strip()
                if record:
                    output.write(record)
                    output.write("\n\n")
                    written += 1
                    if written >= limit:
                        return written
                current = [line]
                inside_brace = _scan_comment_state(line, False)
                continue
            current.append(line)
            inside_brace = _scan_comment_state(line, inside_brace)
        if current and written < limit:
            record = "".join(current).strip()
            if record:
                output.write(record)
                output.write("\n")
                written += 1
    return written


def _download_verified(destination: Path) -> int:
    request = Request(
        CORPUS_URL,
        headers={"User-Agent": "Accessible-Chess-V2-Books-Final-Formats-QA/1"},
    )
    digest = hashlib.sha256()
    total = 0
    try:
        response = urlopen(request, timeout=60)
    except Exception as exc:
        raise RuntimeError(f"real CC0 corpus download failed: {type(exc).__name__}") from exc
    with response, destination.open("wb") as output:
        while True:
            chunk = response.read(DOWNLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > DOWNLOAD_LIMIT_BYTES:
                raise RuntimeError("real CC0 corpus exceeds QA download bound")
            digest.update(chunk)
            output.write(chunk)
    actual = digest.hexdigest()
    if actual != CORPUS_SHA256:
        raise AssertionError(f"real CC0 corpus digest mismatch: {actual}")
    return total


def _make_subset(compressed: Path, subset: Path) -> int:
    with compressed.open("rb") as source:
        reader = zstandard.ZstdDecompressor().stream_reader(source)
        with reader, io.TextIOWrapper(
            reader,
            encoding="utf-8",
            errors="strict",
            newline="",
        ) as text:
            return _write_complete_game_subset(text, subset, SUBSET_GAMES)


def _integrity(database: AcsDatabase) -> dict[str, object]:
    quick_row = database.conn.execute("PRAGMA quick_check").fetchone()
    quick = str(quick_row[0]) if quick_row is not None else "missing"
    foreign_key_issue = database.conn.execute("PRAGMA foreign_key_check").fetchone()
    if quick.lower() != "ok":
        raise AssertionError(f"ACSDB quick_check failed: {quick}")
    if foreign_key_issue is not None:
        raise AssertionError("ACSDB foreign-key integrity failed")
    return {
        "quick_check": quick,
        "foreign_key_check": "PASS",
        "schema_version": database.schema_version,
    }


def _select_real_game(page, games):
    candidates = [item for item in page.items if len(games[item.source_index].line.moves) >= 4]
    if not candidates:
        raise AssertionError("real corpus supplied no four-ply game in bounded Search page")
    rng = random.Random(RANDOM_SEED)
    return candidates[rng.randrange(len(candidates))]


def _make_document(game_id: int) -> BookDocument:
    return BookDocument(
        title="Accessible Chess real referenced-game reading proof",
        author="Accessible Chess QA",
        language="en",
        source_name=f"{CORPUS_NAME}-bounded-reference",
        source_uri=CORPUS_URL,
        source_rights=CORPUS_LICENSE,
        blocks=[
            Heading(text="Real Library game", level=1, block_id="heading-real-game"),
            Paragraph(
                text="This semantic BookDocument references a lawful real Library game.",
                block_id="paragraph-provenance",
            ),
            ListBlock(
                items=[
                    "Open through the canonical Book-to-Board workflow",
                    "Return to the exact semantic reading location",
                    "Restore that location after close and reopen",
                ],
                block_id="list-acceptance",
            ),
            Game(game_id=game_id, title="Real referenced game", block_id="game-real-reference"),
        ],
    )


def _workflow(reader: BookReader, database: AcsDatabase):
    analysis = AnalysisService(lambda: _UnusedEngine())
    assisted = EngineAssistedWorkflowService(analysis)
    workflow = BookBoardWorkflow(
        reader,
        assisted,
        game_lookup=AcsdbBookGameLookup(database),
    )
    return workflow, analysis


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="accessible-chess-v2-books-final-") as temporary:
        root = Path(temporary)
        compressed = root / "lichess.pgn.zst"
        subset = root / "lichess-first-128.pgn"
        database_path = root / "library.acsdb"
        progress_path = root / "book-progress.json"

        compressed_bytes = _download_verified(compressed)
        segmented = _make_subset(compressed, subset)
        if segmented != SUBSET_GAMES:
            raise AssertionError(f"expected {SUBSET_GAMES} complete games, got {segmented}")

        subset_bytes = subset.read_bytes()
        subset_sha256 = hashlib.sha256(subset_bytes).hexdigest()
        games = tuple(parse_pgn_text(subset_bytes.decode("utf-8"), strict=False))
        if len(games) != SUBSET_GAMES:
            raise AssertionError(f"canonical D06 ingress returned {len(games)} games")
        if [game.source_index for game in games] != list(range(SUBSET_GAMES)):
            raise AssertionError("canonical D06 source_index order drifted")

        database = AcsDatabase(database_path)
        try:
            imported = LibraryImportService(database).import_games(
                games,
                source_name=f"{CORPUS_NAME}-first-{SUBSET_GAMES}.pgn",
                source_format="pgn",
                source_sha256=subset_sha256,
            )
            if imported.game_count != SUBSET_GAMES:
                raise AssertionError(f"Library imported {imported.game_count} games")
            integrity_before = _integrity(database)
            page = GameSearchService(database).search(
                GameSearchQuery(source_id=imported.source_id, limit=SEARCH_LIMIT)
            )
            if len(page.items) != SUBSET_GAMES:
                raise AssertionError("public Search did not expose all bounded real games")
            item = _select_real_game(page, games)
            reference = games[item.source_index]
            reference_digest = hashlib.sha256(
                serialize_game(reference).encode("utf-8")
            ).hexdigest()

            document = _make_document(item.game_id)
            if len(document.lists()) != 1 or document.source_rights != CORPUS_LICENSE:
                raise AssertionError("semantic Book core provenance/list composition failed")
            reader = BookReader(document)
            reader.go_to(3)
            origin = reader.location()
            changes_before = database.conn.total_changes
            workflow, analysis = _workflow(reader, database)
            try:
                opened = workflow.open_current()
                if opened.mode is not BookBoardMode.GAME:
                    raise AssertionError("real referenced Book game did not open in GAME mode")
                if opened.source is not BookGameSource.REFERENCE or opened.game_id != item.game_id:
                    raise AssertionError("real referenced Book game lost Library identity")
                if reader.location() != origin:
                    raise AssertionError("Book open moved the semantic reading cursor")
                if database.conn.total_changes != changes_before:
                    raise AssertionError("Book open mutated ACSDB")

                opened_game = workflow.game_snapshot()
                opened_digest = hashlib.sha256(
                    serialize_game(opened_game).encode("utf-8")
                ).hexdigest()
                if opened_digest != reference_digest:
                    raise AssertionError("Book->Board changed canonical GameTree identity")
                start_fen = workflow.board_snapshot().fen()
                first = workflow.next_move()
                second = workflow.next_move()
                if first.current_fen == start_fen or second.current_fen == first.current_fen:
                    raise AssertionError("canonical Book game navigation did not advance Board state")
                restored = workflow.return_to_book()
                if restored != origin or reader.location() != origin:
                    raise AssertionError("Book->Board did not return to exact semantic origin")
                if database.conn.total_changes != changes_before:
                    raise AssertionError("Book navigation/return mutated ACSDB")
            finally:
                analysis.close()

            store = BookProgressStore(progress_path)
            store.save("real-cc0-book", reader)
            document_payload = document.as_dict()
            selected_game_id = item.game_id
            selected_source_index = item.source_index
            search_ids_before = tuple(entry.game_id for entry in page.items)
        finally:
            database.close()

        reopened_database = AcsDatabase(database_path)
        try:
            integrity_after = _integrity(reopened_database)
            reopened_page = GameSearchService(reopened_database).search(
                GameSearchQuery(source_id=imported.source_id, limit=SEARCH_LIMIT)
            )
            if tuple(entry.game_id for entry in reopened_page.items) != search_ids_before:
                raise AssertionError("reopened public Search changed stable real game IDs")

            reopened_document = BookDocument.from_dict(document_payload)
            reopened_reader = BookProgressStore(progress_path).restore(
                "real-cc0-book", reopened_document
            )
            if reopened_reader.location() != origin:
                raise AssertionError("BookProgress close/reopen changed semantic reading location")
            if reopened_document.blocks[origin.index].game_id != selected_game_id:
                raise AssertionError("reopened BookDocument changed referenced Library game ID")

            changes_before_reopen = reopened_database.conn.total_changes
            workflow, analysis = _workflow(reopened_reader, reopened_database)
            try:
                reopened = workflow.open_current()
                reopened_digest = hashlib.sha256(
                    serialize_game(workflow.game_snapshot()).encode("utf-8")
                ).hexdigest()
                if reopened_digest != reference_digest:
                    raise AssertionError("reopened Book reference changed canonical GameTree identity")
                if reopened.source is not BookGameSource.REFERENCE:
                    raise AssertionError("reopened Book game lost REFERENCE source semantics")
                workflow.return_to_book()
            finally:
                analysis.close()
            if reopened_database.conn.total_changes != changes_before_reopen:
                raise AssertionError("reopened Book workflow mutated ACSDB")
        finally:
            reopened_database.close()

        summary = {
            "status": "PASS",
            "claim": "V2 final-formats Books owner composition with real lawful referenced game",
            "product_mutation": False,
            "new_format_support_claimed": False,
            "corpus": {
                "name": CORPUS_NAME,
                "url": CORPUS_URL,
                "license": CORPUS_LICENSE,
                "published_games": CORPUS_PUBLISHED_GAMES,
                "compressed_sha256": CORPUS_SHA256,
                "compressed_bytes": compressed_bytes,
                "subset_games": SUBSET_GAMES,
                "subset_sha256": subset_sha256,
            },
            "journey": {
                "canonical_ingress": "PASS",
                "library_import": "PASS",
                "public_search": "PASS",
                "semantic_book_core": "PASS",
                "book_reference_lookup": "PASS",
                "canonical_gametree_identity": "PASS",
                "book_to_board_navigation": "PASS",
                "exact_return": "PASS",
                "book_progress_close_reopen": "PASS",
                "library_close_reopen": "PASS",
                "read_only_library": "PASS",
                "selected_game_id": selected_game_id,
                "selected_source_index": selected_source_index,
                "canonical_game_sha256": reference_digest,
            },
            "integrity_before_close": integrity_before,
            "integrity_after_reopen": integrity_after,
            "support_boundary": {
                "html_xhtml_ingestion": "NOT_TESTED_HERE_PR391_OWNER",
                "engine_analysis": "NOT_REAL_ENGINE_TESTED_HERE",
                "windows_nvda": False,
                "export": "N/A for Book referenced-game reading seam",
            },
        }
        SUMMARY_PATH.write_text(
            json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print("V2_BOOKS_FINAL_FORMATS=" + json.dumps(summary, sort_keys=True, ensure_ascii=False))
        print("V2 BOOKS FINAL FORMATS REAL COMPOSITION PASS")


if __name__ == "__main__":
    main()
