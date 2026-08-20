import sqlite3
import tempfile
import unittest
from pathlib import Path

from acs.acsdb import (
    ACSDB_SCHEMA_VERSION,
    AcsDatabase,
    AcsImportValidationError,
    AcsMigrationCode,
    AcsMigrationError,
)
from acs.gametree_navigation import VariationStep


def game_pgn(
    index: int,
    *,
    event: str = "Bulk",
    annotator: str = "Coach",
    white: str | None = None,
    black: str | None = None,
) -> str:
    white_name = white or f"White {index}"
    black_name = black or f"Black {index}"
    return f'''[Event "{event}"]
[Site "Kyiv"]
[Date "2026.08.{(index % 28) + 1:02d}"]
[Round "{index + 1}"]
[White "{white_name}"]
[Black "{black_name}"]
[Annotator "{annotator}"]
[ECO "C20"]
[Opening "King Pawn Game"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 *
'''


def create_v2_database(path: Path, *, pgn_text: str | None = None) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
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
    if pgn_text is not None:
        connection.execute(
            """
            INSERT INTO sources(
                id, source_name, source_format, sha256, imported_at
            ) VALUES(1,'legacy.pgn','pgn','abc','2026-01-01')
            """
        )
        connection.execute(
            """
            INSERT INTO games(
                id, source_id, source_index, import_status, warnings_json,
                event, site, game_date, round, white, black, result, eco,
                opening, start_fen, pgn_text
            ) VALUES(
                1, 1, 0, 'full', '[]', 'Legacy Event', 'Kyiv',
                '2026.08.10', '10', 'White 9', 'Black 9', '*', 'C20',
                'King Pawn Game', NULL, ?
            )
            """,
            (pgn_text,),
        )
    connection.commit()
    connection.close()


class AcsDatabaseV3Tests(unittest.TestCase):
    def test_schema_v3_catalog_provenance_identity_and_literal_search(self):
        with AcsDatabase() as database:
            report = database.import_pgn_text(
                game_pgn(
                    0,
                    event="Candidates%_!",
                    annotator="Human%_!",
                ),
                "catalog.pgn",
                provenance_id="provenance:test:catalog",
            )
            self.assertEqual(database.schema_version, ACSDB_SCHEMA_VERSION)
            self.assertEqual(ACSDB_SCHEMA_VERSION, 4)
            source = database.get_source(report.source_id)
            self.assertEqual(source["provenance_id"], "provenance:test:catalog")

            row = database.get_game(report.game_ids[0])
            self.assertEqual(row["identity_schema_version"], 1)
            self.assertEqual(len(row["tree_digest"]), 64)
            self.assertEqual(len(row["record_digest"]), 64)
            self.assertEqual(
                row["catalog_id"], f"game:v1:{row['record_digest']}"
            )

            counts = database.catalog_counts()
            self.assertEqual(counts["players"], 2)
            self.assertEqual(counts["events"], 1)
            self.assertEqual(counts["annotators"], 1)
            self.assertEqual(counts["openings"], 1)
            self.assertEqual(counts["game_catalog"], 1)

            self.assertEqual(len(database.search_games(player="white 0")), 1)
            self.assertEqual(len(database.search_games(event="%_!")), 1)
            self.assertEqual(len(database.search_games(annotator="%_!")), 1)
            self.assertEqual(len(database.search_games(eco="c2", opening="pawn")), 1)
            self.assertEqual(
                len(database.search_games(provenance_id="provenance:test:catalog")),
                1,
            )
            self.assertEqual(
                len(database.search_games(record_digest=row["record_digest"])),
                1,
            )

    def test_catalog_and_default_provenance_ids_are_deterministic(self):
        first_text = game_pgn(1, white="  Alice  ", black="Bob")
        second_text = game_pgn(2, white="alice", black="Carol")

        snapshots = []
        for ordered in (
            (("one.pgn", first_text), ("two.pgn", second_text)),
            (("two.pgn", second_text), ("one.pgn", first_text)),
        ):
            with AcsDatabase() as database:
                reports = {
                    name: database.import_pgn_text(text, name)
                    for name, text in ordered
                }
                entity_ids = {
                    (row["name"].casefold(), row["catalog_id"])
                    for row in database.conn.execute(
                        "SELECT name, catalog_id FROM players"
                    )
                }
                provenance = {
                    name: database.get_source(report.source_id)["provenance_id"]
                    for name, report in reports.items()
                }
                snapshots.append((entity_ids, provenance))

        self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(len([item for item in snapshots[0][0] if item[0] == "alice"]), 1)

    def test_duplicate_policies_use_validated_indexed_identities(self):
        text = game_pgn(1)
        with AcsDatabase() as database:
            first = database.import_pgn_text(text, "first.pgn")
            before = database.catalog_counts()

            exact = database.import_pgn_text(
                text,
                "second-name.pgn",
                duplicate_policy="skip_exact_source",
            )
            self.assertEqual((exact.skipped, exact.duplicate), (1, 1))
            self.assertEqual(exact.source_id, first.source_id)
            self.assertEqual(database.catalog_counts()["sources"], before["sources"])
            self.assertEqual(database.catalog_counts()["games"], before["games"])
            self.assertEqual(
                database.get_import_attempt(exact.attempt_id)["status"],
                "duplicate",
            )

            reformatted = text.replace(
                "1. e4 e5 2. Nf3 Nc6 *", "1.e4 e5 2.Nf3 Nc6 *"
            )
            semantic = database.import_pgn_text(
                reformatted,
                "semantic.pgn",
                duplicate_policy="skip_record",
            )
            self.assertEqual((semantic.skipped, semantic.duplicate), (1, 1))
            self.assertEqual(semantic.game_ids, [])

            # The digest index narrows candidates, but externally stale catalog
            # data cannot authorize false coalescing without revalidating PGN.
            database.conn.execute(
                "UPDATE games SET pgn_text=? WHERE id=?",
                (text.replace("1. e4 e5", "1. d4 d5"), first.game_ids[0]),
            )
            database.conn.commit()
            stale_index = database.import_pgn_text(
                text,
                "stale-index.pgn",
                duplicate_policy="skip_record",
            )
            self.assertEqual(stale_index.skipped, 0)
            self.assertEqual(len(stale_index.game_ids), 1)

            sources_before_illegal = database.catalog_counts()["sources"]
            with self.assertRaises(AcsImportValidationError):
                database.import_pgn_text(
                    '[Event "Illegal"]\n[Result "*"]\n\n1. e4 e5 2. Bh6 *',
                    "illegal.pgn",
                    duplicate_policy="skip_record",
                )
            self.assertEqual(
                database.catalog_counts()["sources"], sources_before_illegal
            )
            self.assertEqual(database.list_import_attempts(limit=1)[0]["status"], "failed")

    def test_atomic_batch_rolls_back_product_rows_and_preserves_failure_evidence(self):
        with AcsDatabase() as database:
            database.conn.execute(
                '''
                CREATE TRIGGER fail_boom_game
                BEFORE INSERT ON games
                WHEN NEW.event = 'Boom'
                BEGIN
                    SELECT RAISE(ABORT, 'synthetic bulk failure');
                END;
                '''
            )
            report = database.import_pgn_batch(
                [
                    ("one.pgn", game_pgn(1, event="Fine")),
                    ("two.pgn", game_pgn(2, event="Boom")),
                    ("three.pgn", game_pgn(3, event="Fine")),
                ],
                atomic=True,
            )
            self.assertEqual(report.reports, [])
            self.assertEqual(len(report.failures), 3)
            self.assertEqual(database.catalog_counts()["sources"], 0)
            self.assertEqual(database.catalog_counts()["games"], 0)
            attempts = database.list_import_attempts(limit=10)
            self.assertEqual(len(attempts), 3)
            self.assertTrue(all(row["status"] == "failed" for row in attempts))
            self.assertTrue(
                all(
                    "synthetic bulk failure" in (row["error_message"] or "")
                    for row in attempts
                )
            )

    def test_atomic_batch_validates_every_game_before_any_product_write(self):
        with AcsDatabase() as database:
            report = database.import_pgn_batch(
                [
                    ("clean.pgn", game_pgn(1)),
                    (
                        "illegal.pgn",
                        '[Event "Illegal"]\n[Result "*"]\n\n1. e4 e5 2. Bh6 *',
                    ),
                ]
            )
            self.assertEqual(len(report.failures), 2)
            self.assertEqual(database.catalog_counts()["sources"], 0)
            self.assertEqual(database.catalog_counts()["games"], 0)
            self.assertTrue(
                all(
                    row["status"] == "failed"
                    for row in database.list_import_attempts()
                )
            )

    def test_exact_gametree_recursive_variation_and_position_retrieval(self):
        text = '''[Event "Branches"]
[Result "*"]

1. e4 (1. d4 d5 (1... Nf6 2. c4)) e5 2. Nf3 *
'''
        with AcsDatabase() as database:
            report = database.import_pgn_text(
                text,
                "branches.pgn",
                provenance_id="branch-source",
            )
            game_id = report.game_ids[0]
            root = database.get_game_tree(game_id)
            self.assertEqual(root.line.moves[0].san, "e4")
            first = database.get_variation(game_id, (VariationStep(0, 0),))
            self.assertEqual([move.san for move in first.moves[:2]], ["d4", "d5"])
            nested = database.get_variation(
                game_id,
                (VariationStep(0, 0), VariationStep(1, 0)),
            )
            self.assertEqual([move.san for move in nested.moves], ["Nf6", "c4"])

            fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"
            database.record_positions(game_id, [(2, fen)])
            changed_counters = fen.rsplit(" ", 2)[0] + " 44 99"
            matches = database.search_position(changed_counters)
            self.assertEqual(matches[0]["matched_ply"], 2)
            self.assertEqual(matches[0]["provenance_id"], "branch-source")
            self.assertEqual(len(matches[0]["record_digest"]), 64)

    def test_validated_recovery_copy_folds_database_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.acsdb"
            recovered = Path(directory) / "recovered.acsdb"
            with AcsDatabase(source) as database:
                report = database.import_pgn_batch(
                    [(f"{index}.pgn", game_pgn(index)) for index in range(20)]
                )
                self.assertEqual(report.game_count, 20)
                database.recover_copy(recovered)
                self.assertEqual(database.last_recovery.destination_path, recovered)
                with self.assertRaises(FileExistsError):
                    database.backup_to(recovered)

            validation = AcsDatabase.validate_database(recovered)
            self.assertTrue(validation["ok"])
            self.assertEqual(validation["schema_version"], 4)
            with AcsDatabase(recovered) as database:
                self.assertEqual(database.catalog_counts()["games"], 20)
                self.assertEqual(database.catalog_counts()["players"], 40)
                self.assertEqual(len(database.search_games(opening="King Pawn")), 20)

    def test_large_600_game_import_builds_complete_paged_catalog(self):
        text = "\n".join(
            game_pgn(index, event="Large Corpus", annotator="Bulk Coach")
            for index in range(600)
        )
        with AcsDatabase() as database:
            report = database.import_pgn_text(text, "large-600.pgn")
            self.assertEqual(len(report.game_ids), 600)
            counts = database.catalog_counts()
            self.assertEqual(counts["games"], 600)
            self.assertEqual(counts["game_catalog"], 600)
            self.assertEqual(counts["players"], 1200)
            self.assertEqual(counts["events"], 1)
            self.assertEqual(counts["annotators"], 1)
            self.assertEqual(counts["openings"], 1)

            pages = [
                database.search_games(event="large corpus", limit=250, offset=offset)
                for offset in (0, 250, 500)
            ]
            self.assertEqual([len(page) for page in pages], [250, 250, 100])
            self.assertEqual(
                len({row["id"] for page in pages for row in page}),
                600,
            )
            sample = database.get_game(report.game_ids[317])
            by_digest = database.search_games(record_digest=sample["record_digest"])
            self.assertEqual([row["id"] for row in by_digest], [report.game_ids[317]])

    def test_v2_migration_backs_up_first_and_records_successful_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.acsdb"
            pgn = game_pgn(9, event="Legacy Event", annotator="Legacy Annotator")
            create_v2_database(path, pgn_text=pgn)

            with AcsDatabase(path) as database:
                evidence = database.last_migration
                self.assertIsNotNone(evidence)
                self.assertEqual((evidence.from_version, evidence.to_version), (2, 4))
                self.assertTrue(evidence.backup_path.exists())
                backup_report = AcsDatabase.validate_database(evidence.backup_path)
                self.assertEqual(backup_report["schema_version"], 2)
                self.assertTrue(backup_report["ok"])

                source = database.get_source(1)
                self.assertTrue(source["provenance_id"].startswith("source:v1:"))
                row = database.get_game(1)
                self.assertEqual(len(row["record_digest"]), 64)
                self.assertEqual(len(database.search_games(annotator="legacy")), 1)
                event = database.list_migration_events()[0]
                self.assertEqual((event["from_version"], event["to_version"]), (2, 4))
                self.assertEqual(event["backup_name"], evidence.backup_path.name)

    def test_injected_migration_failure_rolls_back_and_keeps_verified_backup(self):
        class FailingV3Database(AcsDatabase):
            def _migrate_to_v3(self) -> None:
                super()._migrate_to_v3()
                raise RuntimeError("synthetic migration failure")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.acsdb"
            create_v2_database(path, pgn_text=game_pgn(9))
            with self.assertRaises(AcsMigrationError) as blocked:
                FailingV3Database(path)

            error = blocked.exception
            self.assertEqual(error.code, AcsMigrationCode.MIGRATION_FAILED)
            self.assertTrue(error.rolled_back)
            self.assertTrue(error.recovery_verified)
            self.assertTrue(error.backup_path.exists())
            self.assertEqual(
                AcsDatabase.validate_database(error.backup_path)["schema_version"],
                2,
            )

            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(sources)")
                }
                self.assertNotIn("provenance_id", columns)
                self.assertEqual(
                    connection.execute("SELECT source_name FROM sources").fetchone()[0],
                    "legacy.pgn",
                )
            finally:
                connection.close()

    def test_invalid_legacy_row_is_preserved_and_quarantined_from_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "damaged.acsdb"
            create_v2_database(path, pgn_text="not a PGN game")

            with AcsDatabase(path) as database:
                self.assertEqual(database.catalog_counts()["games"], 1)
                self.assertEqual(database.catalog_counts()["game_catalog"], 0)
                self.assertEqual(database.catalog_counts()["catalog_issues"], 1)
                self.assertEqual(database.last_migration.catalog_issue_count, 1)
                issue = database.list_catalog_issues()[0]
                self.assertEqual(issue["game_id"], 1)
                self.assertTrue(issue["code"])
                self.assertTrue(issue["detail"])
                self.assertTrue(database.integrity_report()["ok"])

    def test_new_v3_boundaries_reject_scalar_coercion_before_sql(self):
        with AcsDatabase() as database:
            report = database.import_pgn_text(game_pgn(1), "one.pgn")
            for value in (True, 1.0, "1"):
                with self.subTest(value=value):
                    with self.assertRaises(TypeError):
                        database.get_game_tree(value)
                    with self.assertRaises(TypeError):
                        database.search_games(offset=value)
                    with self.assertRaises(TypeError):
                        database.list_migration_events(limit=value)
            for value in (1, 1.0, "true"):
                with self.subTest(atomic=value):
                    with self.assertRaises(TypeError):
                        database.import_pgn_batch([], atomic=value)
            with self.assertRaises(ValueError):
                database.search_games(record_digest="not-a-digest")
            with self.assertRaises(TypeError):
                database.search_games(annotator=True)
            with self.assertRaises(TypeError):
                database.import_pgn_batch([["bad.pgn", game_pgn(2)]])
            self.assertIsNotNone(database.get_game_tree(report.game_ids[0]))


if __name__ == "__main__":
    unittest.main()
