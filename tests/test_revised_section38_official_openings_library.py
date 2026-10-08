"""Genuine upstream Lichess ECO opening lines -> canonical Library readback.

ECO source rows are real CC0 opening sequences but NOT complete historical
games. PGN wrappers are derivative test input, not evidence that PGN game files
or ChessBase have been downloaded or fully supported. No new parser/database.
"""
from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.lawful_corpus_registry import (
    LawfulCorpusError, load_catalog, verified_local_source,
)
from acs.library_import_service import LibraryImportService
from acs.library_source_service import LibrarySourceCatalogService
from acs.pgn_roundtrip import parse_pgn_text


ROOT = Path(__file__).resolve().parents[1]


def _genuine_opening_examples():
    records = {source["id"]: source for source in load_catalog()}
    examples = []
    for family in "abcde":
        record = records[f"lichess_openings_original_eco_{family}_tsv"]
        if record["license"] != "CC0" or record["redistribution"] != "permitted":
            raise LawfulCorpusError("opening source rights are not qualified")
        path = ROOT / record["local_source"]
        raw = path.read_bytes()
        verified_local_source(path, record)
        rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter="\t")
        if tuple(rows.fieldnames or ()) != ("eco", "name", "pgn"):
            raise AssertionError("official ECO table schema changed")
        selected = []
        for row in rows:
            if len(selected) == 2:
                break
            if not row["eco"].startswith(family.upper()) or not row["pgn"].startswith("1. "):
                raise AssertionError("official ECO row is malformed")
            selected.append(row)
        if len(selected) != 2:
            raise AssertionError("official ECO source has fewer than two examples")
        for row in selected:
            # The *moves* are verbatim official upstream content; only the
            # provenance Event and Result envelope is made for this QA route.
            pgn = (
                '[Event "Lichess official ECO opening study"]\n'
                '[Result "*"]\n\n'
                + row["pgn"] + ' *\n'
            )
            examples.append(pgn)
    return tuple(examples)


class RealECOToLibraryTests(unittest.TestCase):
    def test_official_cc0_opening_moves_survive_library_restart(self):
        fragments = _genuine_opening_examples()
        self.assertEqual(len(fragments), 10)
        derived_source = "\n\n".join(fragments)
        source_sha = hashlib.sha256(derived_source.encode("utf-8")).hexdigest()
        games = parse_pgn_text(derived_source, strict=False)
        self.assertEqual(len(games), 10)
        for index, game in enumerate(games):
            game.source_index = index

        with tempfile.TemporaryDirectory(prefix="accessible-chess-eco-qa-") as temp:
            filename = Path(temp) / "genuine-openings.acsdb"
            with AcsDatabase(filename) as database:
                first = LibraryImportService(database).import_games(
                    games,
                    source_name="Lichess official ECO 10-row derived QA subset",
                    source_format="pgn",
                    source_sha256=source_sha,
                )
                self.assertEqual(first.game_count, len(games))
                self.assertFalse(first.reused)
                source = LibrarySourceCatalogService(database).get_source(first.source_id)
                self.assertIsNotNone(source)
                self.assertEqual(source.game_count, 10)
                self.assertEqual(source.source_sha256, source_sha)
                database.verify_integrity()

            with AcsDatabase(filename) as database:
                catalogue = LibrarySourceCatalogService(database)
                source = catalogue.get_source(first.source_id)
                self.assertIsNotNone(source)
                self.assertEqual(source.game_count, 10)
                page = catalogue.source_games(first.source_id, limit=20)
                self.assertEqual(len(page.items), 10)
                self.assertFalse(page.has_more)
                repeated = LibraryImportService(database).import_games(
                    games,
                    source_name="Lichess ECO QA renamed without changing bytes",
                    source_format="PGN",
                    source_sha256=source_sha.upper(),
                )
                self.assertTrue(repeated.reused)
                self.assertEqual(repeated.source_id, first.source_id)
                database.verify_integrity()

    def test_changed_upstream_source_refused_before_library_publication(self):
        record = next(
            row for row in load_catalog()
            if row["id"] == "lichess_openings_original_eco_a_tsv"
        )
        source = (ROOT / record["local_source"]).read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            changed = Path(temp) / "a.tsv"
            changed.write_bytes(source[:-1] + bytes([source[-1] ^ 1]))
            with self.assertRaises(LawfulCorpusError):
                verified_local_source(changed, record)
            # The rejected source is never passed to LibraryImportService.
            with AcsDatabase(Path(temp) / "unchanged.acsdb") as database:
                catalogue = LibrarySourceCatalogService(database)
                self.assertEqual(catalogue.list_sources().items, ())


if __name__ == "__main__":
    unittest.main()
