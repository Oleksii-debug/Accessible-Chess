import os
import sqlite3
import tempfile
import unittest

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.duplicate_detection import detect_pgn_duplicates
from acs.gametree_navigation import VariationStep


def game_pgn(index: int, *, event: str = "Bulk", annotator: str = "Coach") -> str:
    return f'''[Event "{event}"]
[Site "Kyiv"]
[Date "2026.08.{(index % 28) + 1:02d}"]
[Round "{index + 1}"]
[White "White {index}"]
[Black "Black {index}"]
[Annotator "{annotator}"]
[ECO "C20"]
[Opening "King Pawn Game"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 *
'''


class AcsDatabaseV3VerticalTests(unittest.TestCase):
    def test_schema_v3_normalizes_catalog_provenance_and_semantic_identity(self):
        with AcsDatabase() as db:
            report = db.import_pgn_text(
                game_pgn(0, event="Candidates", annotator="Human Annotator"),
                "catalog.pgn",
                provenance_id="provenance:test:catalog",
            )
            self.assertEqual(db.schema_version, ACSDB_SCHEMA_VERSION)
            self.assertGreaterEqual(ACSDB_SCHEMA_VERSION, 3)
            source = db.get_source(report.source_id)
            self.assertEqual(source["provenance_id"], "provenance:test:catalog")

            row = db.get_game(report.game_ids[0])
            self.assertEqual(row["identity_schema_version"], 1)
            self.assertEqual(len(row["tree_digest"]), 64)
            self.assertEqual(len(row["record_digest"]), 64)

            counts = db.catalog_counts()
            self.assertEqual(counts["players"], 2)
            self.assertEqual(counts["events"], 1)
            self.assertEqual(counts["annotators"], 1)
            self.assertEqual(counts["openings"], 1)

            self.assertEqual(len(db.search_games(player="white 0")), 1)
            self.assertEqual(len(db.search_games(event="candidate")), 1)
            self.assertEqual(len(db.search_games(annotator="human")), 1)
            self.assertEqual(len(db.search_games(eco="c2", opening="pawn")), 1)
            self.assertEqual(
                len(db.search_games(provenance_id="provenance:test:catalog")), 1
            )
            self.assertEqual(
                len(db.search_games(record_digest=row["record_digest"])), 1
            )

    def test_duplicate_policies_use_indexed_source_and_record_identity(self):
        text = game_pgn(1)
        with AcsDatabase() as db:
            first = db.import_pgn_text(text, "first.pgn")
            source_count = db.catalog_counts()["sources"]
            game_count = db.catalog_counts()["games"]

            exact = db.import_pgn_text(
                text, "second-name.pgn", duplicate_policy="skip_exact_source"
            )
            self.assertEqual(exact.skipped, 1)
            self.assertEqual(exact.duplicate, 1)
            self.assertEqual(exact.source_id, first.source_id)
            self.assertEqual(db.catalog_counts()["sources"], source_count)
            self.assertEqual(db.catalog_counts()["games"], game_count)
            self.assertEqual(
                db.get_import_attempt(exact.attempt_id)["status"], "duplicate"
            )

            reformatted = text.replace("1. e4 e5 2. Nf3 Nc6 *", "1.e4 e5 2.Nf3 Nc6 *")
            semantic = db.import_pgn_text(
                reformatted, "semantic.pgn", duplicate_policy="skip_record"
            )
            self.assertEqual(semantic.skipped, 1)
            self.assertEqual(semantic.game_ids, [])
            self.assertEqual(db.catalog_counts()["games"], game_count)

            evidence = detect_pgn_duplicates(db, reformatted)
            self.assertTrue(evidence.has_semantic_duplicates)
            self.assertTrue(any(match.kind == "record" for match in evidence.matches))

    def test_atomic_multi_source_batch_rolls_back_all_product_rows_on_storage_failure(self):
        with AcsDatabase() as db:
            db.conn.execute(
                '''
                CREATE TRIGGER fail_boom_game
                BEFORE INSERT ON games
                WHEN NEW.event = 'Boom'
                BEGIN
                    SELECT RAISE(ABORT, 'synthetic bulk failure');
                END;
                '''
            )
            sources = [
                ("one.pgn", game_pgn(1, event="Fine")),
                ("two.pgn", game_pgn(2, event="Boom")),
                ("three.pgn", game_pgn(3, event="Fine")),
            ]
            with self.assertRaises(Exception):
                db.import_pgn_batch(sources, atomic=True)

            self.assertEqual(db.catalog_counts()["sources"], 0)
            self.assertEqual(db.catalog_counts()["games"], 0)
            attempts = db.list_import_attempts(limit=10)
            self.assertEqual(len(attempts), 3)
            self.assertTrue(all(row["status"] == "failed" for row in attempts))
            self.assertTrue(
                all("synthetic bulk failure" in (row["error_message"] or "") for row in attempts)
            )

    def test_exact_gametree_and_recursive_variation_retrieval(self):
        text = '''[Event "Branches"]
[Result "*"]

1. e4 (1. d4 d5 (1... Nf6 2. c4)) e5 2. Nf3 *
'''
        with AcsDatabase() as db:
            report = db.import_pgn_text(text, "branches.pgn")
            game_id = report.game_ids[0]
            root = db.get_game_tree(game_id)
            self.assertEqual(root.line.moves[0].san, "e4")
            first = db.get_variation(game_id, (VariationStep(0, 0),))
            self.assertEqual([move.san for move in first.moves[:2]], ["d4", "d5"])
            nested = db.get_variation(
                game_id,
                (VariationStep(0, 0), VariationStep(1, 0)),
            )
            self.assertEqual([move.san for move in nested.moves], ["Nf6", "c4"])

    def test_position_index_and_semantic_search_return_exact_provenance(self):
        with AcsDatabase() as db:
            report = db.import_pgn_text(
                game_pgn(5), "position.pgn", provenance_id="position-source"
            )
            fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"
            db.record_positions(report.game_ids[0], [(2, fen)])
            changed_counters = (
                "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/"
                "RNBQKBNR w KQkq e6 44 99"
            )
            matches = db.search_position(changed_counters)
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["matched_ply"], 2)
            self.assertEqual(matches[0]["provenance_id"], "position-source")
            self.assertEqual(len(matches[0]["record_digest"]), 64)

    def test_recovery_copy_folds_wal_and_reopens_with_catalog_intact(self):
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        backup = path + ".recovered"
        try:
            with AcsDatabase(path) as db:
                batch = [(f"{i}.pgn", game_pgn(i)) for i in range(20)]
                report = db.import_pgn_batch(batch)
                self.assertEqual(report.game_count, 20)
                self.assertTrue(db.integrity_report()["ok"])
                db.recover_copy(backup)

            with AcsDatabase(backup) as recovered:
                self.assertTrue(recovered.integrity_report()["ok"])
                self.assertEqual(recovered.catalog_counts()["games"], 20)
                self.assertEqual(recovered.catalog_counts()["players"], 40)
                self.assertEqual(len(recovered.search_games(opening="King Pawn")), 20)
        finally:
            for candidate in (path, backup, path + "-wal", path + "-shm"):
                if os.path.exists(candidate):
                    os.unlink(candidate)

    def test_large_600_game_bulk_import_builds_complete_indexed_catalog(self):
        text = "\n".join(
            game_pgn(i, event="Large Corpus", annotator="Bulk Coach")
            for i in range(600)
        )
        with AcsDatabase() as db:
            report = db.import_pgn_text(text, "large-600.pgn")
            self.assertEqual(len(report.game_ids), 600)
            counts = db.catalog_counts()
            self.assertEqual(counts["games"], 600)
            self.assertEqual(counts["players"], 1200)
            self.assertEqual(counts["events"], 1)
            self.assertEqual(counts["annotators"], 1)
            self.assertEqual(counts["openings"], 1)

            page1 = db.search_games(event="large corpus", limit=250, offset=0)
            page2 = db.search_games(event="large corpus", limit=250, offset=250)
            page3 = db.search_games(event="large corpus", limit=250, offset=500)
            self.assertEqual(len(page1), 250)
            self.assertEqual(len(page2), 250)
            self.assertEqual(len(page3), 100)
            ids = {row["id"] for row in page1 + page2 + page3}
            self.assertEqual(len(ids), 600)

            sample = db.get_game(report.game_ids[317])
            by_digest = db.search_games(record_digest=sample["record_digest"])
            self.assertEqual([row["id"] for row in by_digest], [report.game_ids[317]])

            indexes = {
                row[1]
                for row in db.conn.execute("PRAGMA index_list(game_catalog)").fetchall()
            }
            self.assertIn("idx_catalog_record_digest", indexes)
            self.assertIn("idx_catalog_tree_digest", indexes)

    def test_v2_database_migrates_existing_game_into_catalog(self):
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            conn = sqlite3.connect(path)
            conn.executescript(
                '''
                PRAGMA foreign_keys = ON;
                CREATE TABLE sources (
                    id INTEGER PRIMARY KEY,
                    source_name TEXT NOT NULL,
                    source_format TEXT NOT NULL,
                    sha256 TEXT,
                    imported_at TEXT NOT NULL
                );
                CREATE TABLE games (
                    id INTEGER PRIMARY KEY,
                    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    source_index INTEGER NOT NULL,
                    import_status TEXT NOT NULL CHECK(import_status IN ('full','partial','damaged','warning')),
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    event TEXT, site TEXT, game_date TEXT, round TEXT, white TEXT, black TEXT,
                    result TEXT, eco TEXT, opening TEXT, start_fen TEXT, pgn_text TEXT NOT NULL,
                    UNIQUE(source_id, source_index)
                );
                CREATE TABLE positions (
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    ply INTEGER NOT NULL,
                    fen TEXT NOT NULL,
                    position_key TEXT NOT NULL,
                    PRIMARY KEY(game_id, ply)
                );
                CREATE TABLE import_attempts (
                    id INTEGER PRIMARY KEY,
                    source_name TEXT NOT NULL,
                    source_format TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL CHECK(status IN ('pending','full','warning','damaged','failed')),
                    source_id INTEGER,
                    game_count INTEGER NOT NULL DEFAULT 0,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT
                );
                PRAGMA user_version = 2;
                '''
            )
            pgn = game_pgn(9, event="Legacy Event", annotator="Legacy Annotator")
            conn.execute(
                "INSERT INTO sources(id,source_name,source_format,sha256,imported_at) VALUES(1,'legacy.pgn','pgn','abc','2026-01-01')"
            )
            conn.execute(
                '''
                INSERT INTO games(
                    id,source_id,source_index,import_status,warnings_json,event,site,game_date,
                    round,white,black,result,eco,opening,start_fen,pgn_text
                ) VALUES(1,1,0,'full','[]','Legacy Event','Kyiv','2026.08.10','10',
                         'White 9','Black 9','*','C20','King Pawn Game',NULL,?)
                ''',
                (pgn,),
            )
            conn.commit()
            conn.close()

            with AcsDatabase(path) as migrated:
                self.assertEqual(migrated.schema_version, ACSDB_SCHEMA_VERSION)
                source = migrated.get_source(1)
                self.assertTrue(source["provenance_id"].startswith("legacy-1-"))
                row = migrated.get_game(1)
                self.assertEqual(len(row["record_digest"]), 64)
                self.assertEqual(len(migrated.search_games(annotator="legacy")), 1)
                self.assertEqual(migrated.catalog_counts()["players"], 2)
        finally:
            for candidate in (path, path + "-wal", path + "-shm"):
                if os.path.exists(candidate):
                    os.unlink(candidate)


if __name__ == "__main__":
    unittest.main()
