import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase


class _TrackingConnection:
    def __init__(self, connection):
        self._connection = connection
        self.closed = False

    @property
    def row_factory(self):
        return self._connection.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._connection.row_factory = value

    def execute(self, *args, **kwargs):
        return self._connection.execute(*args, **kwargs)

    def close(self):
        self.closed = True
        self._connection.close()


class AcsDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = AcsDatabase(':memory:')

    def tearDown(self):
        self.db.close()

    def test_schema_version_is_explicit(self):
        self.assertEqual(self.db.schema_version, ACSDB_SCHEMA_VERSION)
        self.assertGreaterEqual(ACSDB_SCHEMA_VERSION, 2)

    def test_schema_version_persists_across_reopen(self):
        fd, path = tempfile.mkstemp(suffix='.acsdb')
        os.close(fd)
        try:
            with AcsDatabase(path) as first:
                self.assertEqual(first.schema_version, ACSDB_SCHEMA_VERSION)
                first.add_source('persist.pgn', 'pgn')
            with AcsDatabase(path) as reopened:
                self.assertEqual(reopened.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(len(reopened.search_games()), 0)
                source_count = reopened.conn.execute('SELECT COUNT(*) FROM sources').fetchone()[0]
                self.assertEqual(source_count, 1)
        finally:
            os.unlink(path)

    def test_v1_database_migrates_forward_without_losing_existing_rows(self):
        fd, path = tempfile.mkstemp(suffix='.acsdb')
        os.close(fd)
        try:
            conn = sqlite3.connect(path)
            conn.execute('PRAGMA foreign_keys = ON')
            conn.executescript(
                '''
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
                INSERT INTO sources(id, source_name, source_format, sha256, imported_at)
                VALUES(1, 'legacy.pgn', 'pgn', NULL, '2026-01-01T00:00:00+00:00');
                PRAGMA user_version = 1;
                '''
            )
            conn.commit()
            conn.close()

            with AcsDatabase(path) as migrated:
                self.assertEqual(migrated.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(migrated.get_source(1)['source_name'], 'legacy.pgn')
                columns = {
                    row[1] for row in migrated.conn.execute('PRAGMA table_info(import_attempts)')
                }
                self.assertIn('error_message', columns)
                self.assertIn('status', columns)
        finally:
            os.unlink(path)

    def test_newer_schema_is_rejected_without_rewriting_database(self):
        fd, path = tempfile.mkstemp(suffix='.acsdb')
        os.close(fd)
        future_version = ACSDB_SCHEMA_VERSION + 1
        try:
            conn = sqlite3.connect(path)
            conn.execute(f'PRAGMA user_version = {future_version}')
            conn.execute('CREATE TABLE future_marker(value TEXT NOT NULL)')
            conn.execute("INSERT INTO future_marker(value) VALUES('keep-me')")
            conn.commit()
            conn.close()

            original_connect = sqlite3.connect
            tracked = []

            def connect_with_tracking(*args, **kwargs):
                wrapper = _TrackingConnection(original_connect(*args, **kwargs))
                tracked.append(wrapper)
                return wrapper

            with mock.patch('acs.acsdb.sqlite3.connect', side_effect=connect_with_tracking):
                with self.assertRaisesRegex(RuntimeError, 'newer than supported'):
                    AcsDatabase(path)

            self.assertEqual(len(tracked), 1)
            self.assertTrue(tracked[0].closed, 'schema rejection must close SQLite handle')

            verify = sqlite3.connect(path)
            self.assertEqual(verify.execute('PRAGMA user_version').fetchone()[0], future_version)
            self.assertEqual(verify.execute('SELECT value FROM future_marker').fetchone()[0], 'keep-me')
            verify.close()
        finally:
            os.unlink(path)

    def test_import_report_and_provenance_are_explicit(self):
        text = '''[Event "Match"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]
[ECO "C20"]

1. e4 e5 1-0

[Event "Warning game"]
[White "Gamma"]
[Black "Delta"]
[Result "1-0"]

1. d4 0-1
'''
        report = self.db.import_pgn_text(text, 'sample.pgn')
        self.assertEqual(report.total, 2)
        self.assertEqual(report.full, 1)
        self.assertEqual(report.warning, 1)
        self.assertEqual(report.partial, 0)
        self.assertEqual(report.damaged, 0)
        self.assertIsNotNone(report.attempt_id)
        source = self.db.get_source(report.source_id)
        self.assertEqual(source['source_name'], 'sample.pgn')
        self.assertEqual(source['source_format'], 'pgn')
        self.assertEqual(len(source['sha256']), 64)
        warning_game = self.db.get_game(report.game_ids[1])
        self.assertEqual(warning_game['import_status'], 'warning')
        self.assertIn('differs', warning_game['warnings_json'])
        attempt = self.db.get_import_attempt(report.attempt_id)
        self.assertEqual(attempt['status'], 'warning')
        self.assertEqual(attempt['source_id'], report.source_id)
        self.assertEqual(attempt['game_count'], 2)
        self.assertEqual(attempt['warning_count'], 1)
        self.assertIsNotNone(attempt['finished_at'])
        self.assertIsNone(attempt['error_message'])

    def test_tag_search_is_case_insensitive_and_indexable(self):
        text = '''[Event "Candidates"]
[White "Carlsen, Magnus"]
[Black "Nepomniachtchi, Ian"]
[Result "1/2-1/2"]
[ECO "B30"]
[Opening "Sicilian Defense"]

1. e4 c5 1/2-1/2
'''
        self.db.import_pgn_text(text, 'players.pgn')
        self.assertEqual(len(self.db.search_games(player='carlsen')), 1)
        self.assertEqual(len(self.db.search_games(event='candidates', eco='B3')), 1)
        self.assertEqual(len(self.db.search_games(opening='sicilian')), 1)
        self.assertEqual(len(self.db.search_games(source_name='PLAYERS')), 1)
        self.assertEqual(len(self.db.search_games(result='1-0')), 0)

    def test_exact_position_reference_ignores_move_counters_only(self):
        report = self.db.import_pgn_text('[Event "P"]\n[Result "*"]\n\n1. e4 *', 'position.pgn')
        game_id = report.game_ids[0]
        fen = 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2'
        self.db.record_position(game_id, 2, fen)
        same_position_different_counters = 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 17 99'
        matches = self.db.search_position(same_position_different_counters)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['matched_ply'], 2)
        different_turn = 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e6 0 2'
        self.assertEqual(self.db.search_position(different_turn), [])

    def test_blank_import_is_reported_as_damaged_not_silent_success(self):
        report = self.db.import_pgn_text('', 'empty.pgn')
        self.assertEqual(report.total, 1)
        self.assertEqual(report.damaged, 1)
        self.assertEqual(report.game_ids, [])
        self.assertEqual(self.db.get_source(report.source_id)['source_name'], 'empty.pgn')
        attempt = self.db.get_import_attempt(report.attempt_id)
        self.assertEqual(attempt['status'], 'damaged')
        self.assertEqual(attempt['game_count'], 0)

    def test_invalid_status_is_rejected(self):
        from acs.gametree import parse_games
        game = parse_games('[Result "*"]\n\n1. e4 *')[0]
        source_id = self.db.add_source('x.pgn', 'pgn')
        with self.assertRaises(ValueError):
            self.db.store_game(game, source_id, import_status='magic')

    def test_multi_game_import_is_atomic_on_storage_failure_and_failure_is_reported(self):
        text = '''[Event "First"]
[Result "*"]

1. e4 *

[Event "Second"]
[Result "*"]

1. d4 *
'''
        self.db.conn.execute(
            '''
            CREATE TRIGGER fail_second_game
            BEFORE INSERT ON games
            WHEN NEW.source_index = 1
            BEGIN
                SELECT RAISE(ABORT, 'synthetic second-game failure');
            END;
            '''
        )
        with self.assertRaises(Exception):
            self.db.import_pgn_text(text, 'atomic.pgn')

        source_count = self.db.conn.execute(
            "SELECT COUNT(*) FROM sources WHERE source_name='atomic.pgn'"
        ).fetchone()[0]
        game_count = self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        self.assertEqual(source_count, 0)
        self.assertEqual(game_count, 0)
        failures = self.db.list_import_attempts(status='failed')
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]['source_name'], 'atomic.pgn')
        self.assertIsNone(failures[0]['source_id'])
        self.assertEqual(failures[0]['game_count'], 0)
        self.assertIn('synthetic second-game failure', failures[0]['error_message'])

    def test_import_attempts_can_be_found_by_digest(self):
        text = '[Event "Digest"]\n[Result "*"]\n\n1. e4 *'
        first = self.db.import_pgn_text(text, 'one.pgn')
        attempt = self.db.get_import_attempt(first.attempt_id)
        matches = self.db.list_import_attempts(sha256=attempt['sha256'])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['id'], first.attempt_id)

    def test_position_batch_is_atomic_if_one_row_is_invalid(self):
        report = self.db.import_pgn_text('[Result "*"]\n\n1. e4 *', 'positions.pgn')
        game_id = report.game_ids[0]
        valid = '8/8/8/8/8/8/8/8 w - - 0 1'
        with self.assertRaises(ValueError):
            self.db.record_positions(game_id, [(0, valid), (1, 'not a fen')])
        count = self.db.conn.execute(
            'SELECT COUNT(*) FROM positions WHERE game_id=?', (game_id,)
        ).fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == '__main__':
    unittest.main()
