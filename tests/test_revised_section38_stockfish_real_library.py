"""End-to-end import qualification using actual upstream Stockfish CC0 ZIP bytes.

The original archives are checked against the pinned source catalog before their
contents reach the existing canonical PGN/FEN services. The evidence is limited
to these real fixtures; it is NOT ChessBase/EPUB/PDF/DOCX qualification.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.lawful_corpus_registry import (
    LawfulCorpusError, load_catalog, read_verified_zip_member, verified_local_source,
)
from acs.library_import_service import LibraryImportService
from acs.library_source_service import LibrarySourceCatalogService
from acs.pgn_roundtrip import parse_pgn_text
from acs.position_editor import PositionState


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_PGN_ID = "stockfish_2moves_v2_pgn_zip"
ORIGINAL_FEN_ID = "stockfish_startpos_epd_zip"


def _original_member(source_id: str) -> tuple[dict, bytes]:
    record = next(item for item in load_catalog() if item["id"] == source_id)
    if (
        record["acquisition"] != "VENDORED_SOURCE_VERIFIED"
        or not record["license"].startswith("CC0")
        or not record["redistribution"].startswith("permitted")
    ):
        raise LawfulCorpusError("source lacks qualified original-byte test provenance")
    source = ROOT / record["local_source"]
    license_file = ROOT / record["license_source"]
    verified_local_source(source, record)
    verified_local_source(
        license_file,
        {"sha256": record["license_sha256"], "max_bytes": 1024 * 1024},
    )
    member = read_verified_zip_member(
        source, record,
        expected_member=record["zip_member"],
        max_unpacked_bytes=record["max_unpacked_bytes"],
    )
    if not member or len(member) > record["max_unpacked_bytes"]:
        raise LawfulCorpusError("verified original archive member is empty or oversized")
    return record, member


class OriginalStockfishCanonicalIntegrationTests(unittest.TestCase):
    def test_real_original_pgn_archive_to_persistent_library_and_restart(self):
        record, source = _original_member(ORIGINAL_PGN_ID)
        self.assertEqual(record["format"], "pgn.zip")
        self.assertEqual(record["indexed_bytes"], 57325)
        try:
            original_text = source.decode("utf-8-sig", errors="strict")
        except UnicodeError as exc:
            self.fail(f"official source is not UTF-8 PGN: {exc}")
        parsed = parse_pgn_text(original_text, strict=False)
        self.assertGreater(
            len(parsed), 0,
            "a real PGN archive must not silently produce an empty Library source",
        )
        # Do not mislabel these opening-book fragments as historical completed games.
        sample = parsed[: min(len(parsed), 32)]
        self.assertTrue(any(game.line.moves for game in sample))
        for index, game in enumerate(sample):
            game.source_index = index
        source_hash = hashlib.sha256(source).hexdigest()
        with tempfile.TemporaryDirectory(prefix="accessible-chess-official-pgn-") as temp:
            path = Path(temp) / "real-stockfish-pgn.acsdb"
            with AcsDatabase(path) as db:
                result = LibraryImportService(db).import_games(
                    sample,
                    source_name="official-stockfish/books:2moves_v2.pgn",
                    source_format="pgn",
                    source_sha256=source_hash,
                )
                self.assertFalse(result.reused)
                self.assertEqual(result.game_count, len(sample))
                db.verify_integrity()

            with AcsDatabase(path) as db:
                service = LibrarySourceCatalogService(db)
                summary = service.get_source(result.source_id)
                self.assertIsNotNone(summary)
                self.assertEqual(summary.game_count, len(sample))
                self.assertEqual(summary.source_sha256, source_hash)
                page = service.source_games(result.source_id, limit=32)
                self.assertEqual(len(page.items), len(sample))
                self.assertEqual(
                    tuple(item.source_index for item in page.items),
                    tuple(range(len(sample))),
                )
                again = LibraryImportService(db).import_games(
                    sample,
                    source_name="same original material after process restart",
                    source_format="pgn",
                    source_sha256=source_hash,
                )
                self.assertTrue(again.reused)
                self.assertEqual(again.source_id, result.source_id)
                db.verify_integrity()

    def test_official_start_position_uses_canonical_fen_not_fake_epd(self):
        record, content = _original_member(ORIGINAL_FEN_ID)
        self.assertEqual(record["format"], "epd.zip")
        lines = content.decode("utf-8-sig", errors="strict").splitlines()
        self.assertGreater(len(lines), 0)
        first = lines[0].strip()
        # Upstream names it .epd, but the actual fixture contains six-field FEN.
        self.assertEqual(len(first.split()), 6)
        state = PositionState.from_fen(first)
        self.assertEqual(state.to_fen(), first)
        self.assertFalse(state.validate_playable())

    def test_invalid_member_and_altered_bytes_fail_before_publication(self):
        record, content = _original_member(ORIGINAL_PGN_ID)
        path = ROOT / record["local_source"]
        with self.assertRaises(LawfulCorpusError):
            read_verified_zip_member(
                path, record, expected_member="../other.pgn",
            )
        with tempfile.TemporaryDirectory() as temp:
            changed = Path(temp) / "not-upstream.zip"
            original = path.read_bytes()
            changed.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
            with self.assertRaises(LawfulCorpusError):
                read_verified_zip_member(
                    changed, record, expected_member=record["zip_member"],
                    max_unpacked_bytes=record["max_unpacked_bytes"],
                )
            with AcsDatabase(Path(temp) / "no-accidental-publication.acsdb") as db:
                self.assertEqual(
                    LibrarySourceCatalogService(db).list_sources().items,
                    (),
                )


if __name__ == "__main__":
    unittest.main()
