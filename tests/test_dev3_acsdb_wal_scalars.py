import os
import tempfile
import unittest

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.import_history_service import ImportHistoryQuery, ImportHistoryService
from acs.search_service import GameSearchQuery, GameSearchService


class Dev3AcsdbWalScalarTests(unittest.TestCase):
    def test_schema_v3_has_composite_exact_position_index(self):
        self.assertGreaterEqual(ACSDB_SCHEMA_VERSION, 3)
        with AcsDatabase(':memory:') as db:
            indexes = {
                row['name']
                for row in db.conn.execute("PRAGMA index_list('positions')").fetchall()
            }
            self.assertIn('idx_positions_key_game_ply', indexes)
            columns = [
                row['name']
                for row in db.conn.execute(
                    "PRAGMA index_info('idx_positions_key_game_ply')"
                ).fetchall()
            ]
            self.assertEqual(columns, ['position_key', 'game_id', 'ply'])

    def test_v2_database_migrates_to_v3_without_losing_rows(self):
        fd, path = tempfile.mkstemp(suffix='.acsdb')
        os.close(fd)
        try:
            conn = __import__('sqlite3').connect(path)
            conn.executescript('''
                CREATE TABLE sources (
                    id INTEGER PRIMARY KEY,
                    source_name TEXT NOT NULL,
                    source_format TEXT NOT NULL,
                    sha256 TEXT,
                    imported_at TEXT NOT NULL
                );
                CREATE TABLE games (
                    id INTEGER PRIMARY KEY,
                    source_id INTEGER NOT NULL,
                    source_index INTEGER NOT NULL,
                    import_status TEXT NOT NULL,
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    event TEXT, site TEXT, game_date TEXT, round TEXT,
                    white TEXT, black TEXT, result TEXT, eco TEXT, opening TEXT,
                    start_fen TEXT, pgn_text TEXT NOT NULL
                );
                CREATE TABLE positions (
                    game_id INTEGER NOT NULL,
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
                    status TEXT NOT NULL,
                    source_id INTEGER,
                    game_count INTEGER NOT NULL DEFAULT 0,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT
                );
                INSERT INTO sources(id, source_name, source_format, imported_at)
                VALUES(1, 'legacy.pgn', 'pgn', '2026-01-01T00:00:00+00:00');
                INSERT INTO games(id, source_id, source_index, import_status, pgn_text)
                VALUES(1, 1, 0, 'full', '[Result "*"]\n\n*');
                INSERT INTO positions(game_id, ply, fen, position_key)
                VALUES(1, 0, '8/8/8/8/8/8/8/8 w - - 0 1', '8/8/8/8/8/8/8/8 w - -');
                PRAGMA user_version = 2;
            ''')
            conn.commit()
            conn.close()

            with AcsDatabase(path) as migrated:
                self.assertEqual(migrated.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(migrated.get_source(1)['source_name'], 'legacy.pgn')
                self.assertEqual(
                    migrated.search_position('8/8/8/8/8/8/8/8 w - - 4 9')[0]['id'],
                    1,
                )
        finally:
            for candidate in (path, path + '-wal', path + '-shm'):
                if os.path.exists(candidate):
                    os.unlink(candidate)

    def test_file_database_uses_wal_and_reader_does_not_block_import_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'library.acsdb')
            with AcsDatabase(path) as reader, AcsDatabase(path) as writer:
                self.assertEqual(
                    reader.conn.execute('PRAGMA journal_mode').fetchone()[0].lower(),
                    'wal',
                )
                self.assertEqual(
                    writer.conn.execute('PRAGMA journal_mode').fetchone()[0].lower(),
                    'wal',
                )
                self.assertEqual(reader.conn.execute('PRAGMA busy_timeout').fetchone()[0], 5000)

                reader.import_pgn_text('[Event "Before"]\n[Result "*"]\n\n1. e4 *', 'before.pgn')
                reader.conn.execute('BEGIN')
                self.assertEqual(reader.conn.execute('SELECT COUNT(*) FROM games').fetchone()[0], 1)

                writer.import_pgn_text('[Event "During"]\n[Result "*"]\n\n1. d4 *', 'during.pgn')
                self.assertEqual(reader.conn.execute('SELECT COUNT(*) FROM games').fetchone()[0], 1)

                reader.conn.commit()
                self.assertEqual(reader.conn.execute('SELECT COUNT(*) FROM games').fetchone()[0], 2)

    def test_acsdb_query_scalars_do_not_coerce_strings_floats_or_booleans(self):
        with AcsDatabase(':memory:') as db:
            fen = '8/8/8/8/8/8/8/8 w - - 0 1'
            bad_values = ('2', 1.5, True)
            for bad in bad_values:
                with self.subTest(value=bad, api='search_games_limit'):
                    with self.assertRaises(TypeError):
                        db.search_games(limit=bad)
                with self.subTest(value=bad, api='search_games_cursor'):
                    with self.assertRaises(TypeError):
                        db.search_games(after_id=bad)
                with self.subTest(value=bad, api='attempt_limit'):
                    with self.assertRaises(TypeError):
                        db.list_import_attempts(limit=bad)
                with self.subTest(value=bad, api='position_cursor'):
                    with self.assertRaises(TypeError):
                        db.search_position(fen, after_game_id=bad, after_ply=0)

            with self.assertRaises(ValueError):
                db.search_games(after_id=1 << 63)
            with self.assertRaises(ValueError):
                db.search_position(fen, after_game_id=1, after_ply=1 << 63)

    def test_application_search_and_import_history_reject_scalar_coercion(self):
        with AcsDatabase(':memory:') as db:
            search = GameSearchService(db)
            history = ImportHistoryService(db)

            for query in (
                GameSearchQuery(limit='2'),
                GameSearchQuery(limit=1.5),
                GameSearchQuery(after_game_id='1'),
                GameSearchQuery(source_id=True),
            ):
                with self.subTest(search_query=query):
                    with self.assertRaises(TypeError):
                        search.search(query)

            with self.assertRaises(TypeError):
                search.search(GameSearchQuery(player=b'Alpha'))

            for query in (
                ImportHistoryQuery(limit='2'),
                ImportHistoryQuery(limit=1.5),
                ImportHistoryQuery(after_attempt_id='1'),
                ImportHistoryQuery(after_attempt_id=True),
            ):
                with self.subTest(history_query=query):
                    with self.assertRaises(TypeError):
                        history.search(query)

            with self.assertRaises(TypeError):
                history.search(ImportHistoryQuery(source_format=42))
            with self.assertRaises(TypeError):
                history.get(True)

    def test_large_game_set_pages_deterministically_without_duplicates(self):
        game_count = 1200
        text = '\n\n'.join(
            f'[Event "Bulk {index}"]\n[White "Player {index % 20}"]\n'
            f'[Black "Opponent {index % 17}"]\n[Result "*"]\n\n1. e4 *'
            for index in range(game_count)
        )
        with AcsDatabase(':memory:') as db:
            report = db.import_pgn_text(text, 'bulk-1200.pgn')
            self.assertEqual(report.total, game_count)

            seen = []
            after_id = None
            while True:
                page = db.search_games(after_id=after_id, limit=137)
                if not page:
                    break
                ids = [row['id'] for row in page]
                self.assertEqual(ids, sorted(ids))
                self.assertTrue(set(seen).isdisjoint(ids))
                seen.extend(ids)
                after_id = ids[-1]

            self.assertEqual(seen, report.game_ids)
            self.assertEqual(len(seen), game_count)


if __name__ == '__main__':
    unittest.main()
