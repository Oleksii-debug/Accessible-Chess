"""Offline qualification of a hash-pinned lawful real PGN corpus.

No network downloads or source writes. Corpus acquisition/licensing remains
explicit. Uses the production converter and canonical GameTree identity, not
an independent chess parser or an NVDA qualification claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acs.acsdb import AcsDatabase
from acs.game_identity import identity_for_game
from acs.import_contract import read_source_snapshot
from acs.library_export_service import LibraryExportRequest, LibraryExportService
from acs.library_import_service import LibraryImportService
from acs.pgn_conversion import convert_pgn, preview_conversion
from acs.pgn_document import PgnDocumentSession
from acs.pgn_roundtrip import MAX_PGN_SOURCE_BYTES, parse_pgn_bytes
from acs.pgn_service import open_pgn
from acs.search_service import GameSearchQuery, GameSearchService


def qualify(source: Path, expected_digest: str, expected_games: int) -> dict:
    source_fp, raw = read_source_snapshot(source, max_bytes=MAX_PGN_SOURCE_BYTES)
    if source_fp.sha256 != expected_digest:
        raise ValueError("corpus SHA-256 mismatch")
    original = parse_pgn_bytes(raw)
    if len(original) != expected_games:
        raise ValueError("corpus game count mismatch")
    identities = [identity_for_game(game).record_digest for game in original]
    text = raw.decode("utf-8-sig", errors="strict")
    transports = [
        ("utf-8", raw, "auto"),
        ("utf-16-le", b"\xff\xfe" + text.encode("utf-16-le"), "auto"),
        ("utf-16-be", b"\xfe\xff" + text.encode("utf-16-be"), "auto"),
    ]
    skipped = []
    try:
        transports.append(("windows-1251", text.encode("cp1251", errors="strict"), "windows-1251"))
    except UnicodeEncodeError:
        skipped.append("windows-1251: original Unicode is not representable")
    checked = []
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "Шахова колекція зі пробілами"
        root.mkdir()
        for name, payload, encoding in transports:
            legacy = root / (name + ".pgn")
            destination = root / (name + "-converted.pgn")
            legacy.write_bytes(payload)
            plan = preview_conversion(legacy, encoding=encoding)
            saved = convert_pgn(legacy, destination, reviewed_plan=plan)
            if legacy.read_bytes() != payload or saved.sha256 != plan.output_sha256:
                raise ValueError("source preservation or publication digest mismatch")
            opened = open_pgn(destination)
            if [identity_for_game(game).record_digest for game in opened.games] != identities:
                raise ValueError("real corpus record identity mismatch")
            session = PgnDocumentSession.open(destination)
            if session.workspace.game_count != expected_games:
                raise ValueError("PGN workspace reopening mismatch")
            checked.append({"encoding": name, "games": plan.summary.games, "output_sha256": saved.sha256})
        database_path = root / "Колекція.acsdb"
        database = AcsDatabase(database_path)
        try:
            opened = open_pgn(root / "utf-8-converted.pgn")
            imported = LibraryImportService(database).import_games(
                opened.games, source_name="lawful-real-corpus.pgn", source_format="pgn", source_sha256=opened.source.sha256,
            )
        finally:
            database.close()
        database = AcsDatabase(database_path)
        try:
            count = 0
            cursor = None
            while True:
                search = GameSearchService(database).search(GameSearchQuery(after_game_id=cursor, limit=200))
                count += len(search.items)
                if not search.has_more:
                    break
                if search.next_after_game_id is None or search.next_after_game_id == cursor:
                    raise ValueError("Library search cursor did not advance")
                cursor = search.next_after_game_id
            if count != expected_games:
                raise ValueError("Library search after restart count mismatch")
            output = root / "library-export.pgn"
            exported = LibraryExportService(database).export_to(output, LibraryExportRequest.filtered(GameSearchQuery()))
            if exported.game_count != expected_games:
                raise ValueError("filtered Library export count mismatch")
            if [identity_for_game(game).record_digest for game in open_pgn(output).games] != identities:
                raise ValueError("filtered Library export semantic mismatch")
            if database.conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite integrity failure")
        finally:
            database.close()
    after, _ = read_source_snapshot(source, max_bytes=MAX_PGN_SOURCE_BYTES)
    if after != source_fp:
        raise ValueError("real corpus source changed during qualification")
    return {"source_sha256": source_fp.sha256, "games": expected_games, "conversions": checked,
            "skipped_transports": skipped, "library_restart_search_export": "PASS", "sqlite_integrity": "ok",
            "source_unchanged": True, "independent_parser_oracle": False, "HUMAN_TESTED": False, "NVDA_VERIFIED": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--expect-source-sha256", required=True)
    parser.add_argument("--expected-games", type=int, required=True)
    args = parser.parse_args()
    if args.expected_games < 1:
        parser.error("expected-games must be positive")
    print(json.dumps(qualify(args.source, args.expect_source_sha256, args.expected_games), indent=2))


if __name__ == "__main__":
    main()
