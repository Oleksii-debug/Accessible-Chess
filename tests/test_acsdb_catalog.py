from __future__ import annotations

import os
import tempfile
import unittest

from acs.acsdb_catalog import AcsCatalogDatabase


def pgn(i: int, *, annotator: str = "Coach") -> str:
    return f'''[Event "Bulk Event {i % 7}"]
[Site "Kyiv"]
[Date "2026.08.16"]
[Round "{i + 1}"]
[White "Player {i % 23}"]
[Black "Player {(i + 1) % 23}"]
[Result "1-0"]
[ECO "C20"]
[Opening "King Pawn"]
[Annotator "{annotator}"]

1. e4 e5 2. Nf3 Nc6 {{note {i}}} (2... Nf6 $1 {{branch {i}}}) 3. Bb5 a6 1-0
'''


class CatalogTests(unittest.TestCase):
    def test_bulk_import_normalized_entities_search_and_exact_tree(self):
        text = "\n".join(pgn(i) for i in range(250))
        db = AcsCatalogDatabase()
        try:
            out = db.import_collection_atomic(text, source_name="bulk250.pgn")
            self.assertEqual(out.inserted, 250)
            self.assertEqual(out.duplicates, 0)
            self.assertEqual(db.integrity_report()["indexed_games"], 250)
            rows = db.search_catalog(player="player 3", opening="king pawn", text="branch", limit=500)
            self.assertGreater(len(rows), 0)
            tree = db.retrieve_game_tree(rows[0]["id"])
            self.assertEqual(tree.tags["Opening"], "King Pawn")
            self.assertIn("branch", tree.movetext.lower())
        finally:
            db.close()

    def test_duplicate_detection_is_canonical_and_cross_source(self):
        db = AcsCatalogDatabase()
        try:
            first = db.import_collection_atomic(pgn(1), source_name="one.pgn")
            second = db.import_collection_atomic(pgn(1), source_name="copy.pgn")
            self.assertEqual(first.inserted, 1)
            self.assertEqual(second.inserted, 0)
            self.assertEqual(second.duplicates, 1)
            self.assertEqual(second.duplicate_game_ids, first.inserted_game_ids)
        finally:
            db.close()

    def test_reject_duplicate_rolls_back_source(self):
        db = AcsCatalogDatabase()
        try:
            db.import_collection_atomic(pgn(2), source_name="base.pgn")
            before = db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            with self.assertRaises(ValueError):
                db.import_collection_atomic(pgn(2), source_name="reject.pgn", reject_duplicates=True)
            after = db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            self.assertEqual(before, after)
        finally:
            db.close()

    def test_persistent_reopen_and_catalog_migration_idempotence(self):
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            with AcsCatalogDatabase(path) as db:
                out = db.import_collection_atomic("\n".join(pgn(i) for i in range(30)))
                ids = list(out.inserted_game_ids)
                self.assertEqual(db.integrity_report()["quick_check"], "ok")
            with AcsCatalogDatabase(path) as db:
                self.assertEqual(db.integrity_report()["catalog_schema_version"], 1)
                self.assertEqual(db.integrity_report()["indexed_games"], 30)
                self.assertEqual(db.retrieve_game_tree(ids[-1]).tags["Event"], "Bulk Event 1")
        finally:
            os.unlink(path)

    def test_future_catalog_schema_fails_closed(self):
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            with AcsCatalogDatabase(path) as db:
                db.conn.execute("UPDATE catalog_meta SET value='999' WHERE key='schema_version'")
                db.conn.commit()
            with self.assertRaises(RuntimeError):
                AcsCatalogDatabase(path)
        finally:
            os.unlink(path)

    def test_source_filters_pagination_and_annotator(self):
        db = AcsCatalogDatabase()
        try:
            a = db.import_collection_atomic("\n".join(pgn(i, annotator="Alpha") for i in range(40)), source_name="a.pgn")
            db.import_collection_atomic("\n".join(pgn(i + 100, annotator="Beta") for i in range(40)), source_name="b.pgn")
            page1 = db.search_catalog(annotator="alpha", source_id=a.source_id, limit=10)
            page2 = db.search_catalog(annotator="alpha", source_id=a.source_id, limit=10, offset=10)
            self.assertEqual(len(page1), 10)
            self.assertEqual(len(page2), 10)
            self.assertTrue(set(r["id"] for r in page1).isdisjoint(r["id"] for r in page2))
        finally:
            db.close()

    def test_large_thousand_game_import_search_and_integrity(self):
        text = "\n".join(pgn(i) for i in range(1000))
        db = AcsCatalogDatabase()
        try:
            out = db.import_collection_atomic(text, source_name="thousand.pgn")
            self.assertEqual(out.inserted, 1000)
            self.assertEqual(db.integrity_report()["games"], 1000)
            self.assertEqual(db.integrity_report()["foreign_key_errors"], [])
            hits = db.search_catalog(event="bulk event 3", text="note", limit=5000)
            self.assertGreater(len(hits), 100)
            fingerprints = [r["fingerprint"] for r in hits[:20]]
            self.assertEqual(len(db.duplicate_groups(fingerprints)), 20)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
