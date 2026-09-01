import os
import sqlite3
import tempfile
import unittest

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.pgn_roundtrip import (
    MAX_PGN_TAG_VALUE_CHARS,
    PgnRoundTripError,
    PgnRoundTripErrorCode,
)


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
                self.assertEqual(reopened.conn.execute('SELECT COUNT(*) FROM sources').fetchone()[0], 1)
        finally:
            os.unlink(path)

    def test_v1_database_migrates_forward_without_losing_existing_rows(self):
        fd, path = tempfile.mkstemp(suffix='.acsdb')
        os.close(fd)
        try:
            conn = sqlite3.connect(path)
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
            ''')
            conn.commit()
            conn.close()
            with AcsDatabase(path) as migrated:
                self.assertEqual(migrated.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(migrated.get_source(1)['source_name'], 'legacy.pgn')
                columns = {row[1] for row in migrated.conn.execute('PRAGMA table_info(import_attempts)')}
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
            with self.assertRaisesRegex(RuntimeError, 'newer than supported'):
                AcsDatabase(path)
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
        source = self.db.get_source(report.source_id)
        self.assertEqual(source['source_name'], 'sample.pgn')
        self.assertEqual(len(source['sha256']), 64)
        attempt = self.db.get_import_attempt(report.attempt_id)
        self.assertEqual(attempt['status'], 'warning')
        self.assertEqual(attempt['source_id'], report.source_id)
        self.assertEqual(attempt['game_count'], 2)
        self.assertEqual(attempt['warning_count'], 1)
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

    def test_game_search_keyset_paging_is_stable_when_new_rows_are_inserted(self):
        text = '''[Event "One"]
[White "A"]
[Black "B"]
[Result "*"]

1. e4 *

[Event "Two"]
[White "C"]
[Black "D"]
[Result "*"]

1. d4 *

[Event "Three"]
[White "E"]
[Black "F"]
[Result "*"]

1. c4 *
'''
        report = self.db.import_pgn_text(text, 'page-source.pgn')
        first_page = self.db.search_games(limit=2)
        self.assertEqual([row['id'] for row in first_page], report.game_ids[:2])

        later = self.db.import_pgn_text('[Event "Later"]\n[Result "*"]\n\n1. Nf3 *', 'later.pgn')
        second_page = self.db.search_games(after_id=first_page[-1]['id'], limit=2)

        self.assertEqual(second_page[0]['id'], report.game_ids[2])
        self.assertEqual(second_page[1]['id'], later.game_ids[0])
        self.assertTrue(set(row['id'] for row in first_page).isdisjoint(row['id'] for row in second_page))

    def test_game_search_keyset_paging_preserves_filters(self):
        self.db.import_pgn_text('''[Event "Keep"]
[White "Alpha"]
[Result "*"]

1. e4 *

[Event "Skip"]
[White "Beta"]
[Result "*"]

1. d4 *

[Event "Keep"]
[White "Gamma"]
[Result "*"]

1. c4 *
''', 'filters.pgn')
        first = self.db.search_games(event='keep', limit=1)
        second = self.db.search_games(event='keep', after_id=first[-1]['id'], limit=5)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]['event'], 'Keep')
        self.assertGreater(second[0]['id'], first[0]['id'])

    def test_import_attempt_keyset_paging_is_stable_under_new_attempts(self):
        first = self.db.import_pgn_text('[Event "A"]\n[Result "*"]\n\n1. e4 *', 'a.pgn')
        second = self.db.import_pgn_text('[Event "B"]\n[Result "*"]\n\n1. d4 *', 'b.pgn')
        third = self.db.import_pgn_text('[Event "C"]\n[Result "*"]\n\n1. c4 *', 'c.pgn')

        newest_page = self.db.list_import_attempts(limit=2)
        self.assertEqual([row['id'] for row in newest_page], [third.attempt_id, second.attempt_id])

        later = self.db.import_pgn_text('[Event "D"]\n[Result "*"]\n\n1. Nf3 *', 'd.pgn')
        older_page = self.db.list_import_attempts(before_id=newest_page[-1]['id'], limit=2)

        self.assertEqual([row['id'] for row in older_page], [first.attempt_id])
        self.assertNotIn(later.attempt_id, [row['id'] for row in older_page])

    def test_keyset_cursor_and_limit_validation_rejects_ambiguous_values(self):
        with self.assertRaises(TypeError):
            self.db.search_games(after_id=True)
        with self.assertRaises(ValueError):
            self.db.search_games(after_id=-1)
        with self.assertRaises(TypeError):
            self.db.list_import_attempts(limit=False)
        with self.assertRaises(ValueError):
            self.db.list_import_attempts(before_id=-1)

    def test_exact_position_reference_ignores_move_counters_only(self):
        report = self.db.import_pgn_text('[Event "P"]\n[Result "*"]\n\n1. e4 *', 'position.pgn')
        game_id = report.game_ids[0]
        fen = 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2'
        self.db.record_position(game_id, 2, fen)
        same = 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 17 99'
        self.assertEqual(self.db.search_position(same)[0]['matched_ply'], 2)

    def test_blank_import_is_reported_as_damaged_not_silent_success(self):
        report = self.db.import_pgn_text('', 'empty.pgn')
        self.assertEqual(report.damaged, 1)
        self.assertEqual(self.db.get_import_attempt(report.attempt_id)['status'], 'damaged')

    def test_import_uses_canonical_pgn_bounds_before_publication(self):
        oversized = 'X' * (MAX_PGN_TAG_VALUE_CHARS + 1)
        text = f'[Event "{oversized}"]\n[Result "*"]\n\n*\n'

        with self.assertRaises(PgnRoundTripError) as raised:
            self.db.import_pgn_text(text, 'oversized-event.pgn')

        self.assertEqual(raised.exception.code, PgnRoundTripErrorCode.TAG_SIZE_LIMIT)
        self.assertEqual(self.db.conn.execute('SELECT COUNT(*) FROM sources').fetchone()[0], 0)
        self.assertEqual(self.db.conn.execute('SELECT COUNT(*) FROM games').fetchone()[0], 0)
        failures = self.db.list_import_attempts(status='failed')
        self.assertEqual(len(failures), 1)
        self.assertIsNone(failures[0]['source_id'])
        self.assertEqual(failures[0]['error_message'], 'PgnRoundTripError: import failed')

    def test_multi_game_import_is_atomic_on_storage_failure_and_failure_is_reported(self):
        text = '''[Event "First"]
[Result "*"]

1. e4 *

[Event "Second"]
[Result "*"]

1. d4 *
'''
        self.db.conn.execute('''
            CREATE TRIGGER fail_second_game
            BEFORE INSERT ON games
            WHEN NEW.source_index = 1
            BEGIN
                SELECT RAISE(ABORT, 'synthetic second-game failure');
            END;
        ''')
        with self.assertRaises(Exception):
            self.db.import_pgn_text(text, 'atomic.pgn')
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM sources WHERE source_name='atomic.pgn'").fetchone()[0], 0)
        self.assertEqual(self.db.conn.execute('SELECT COUNT(*) FROM games').fetchone()[0], 0)
        failures = self.db.list_import_attempts(status='failed')
        self.assertEqual(len(failures), 1)
        self.assertIsNone(failures[0]['source_id'])
        self.assertEqual(failures[0]['error_message'], 'IntegrityError: import failed')
        self.assertNotIn('synthetic second-game failure', failures[0]['error_message'])

    def test_position_batch_is_atomic_if_one_row_is_invalid(self):
        report = self.db.import_pgn_text('[Result "*"]\n\n1. e4 *', 'positions.pgn')
        valid = '8/8/8/8/8/8/8/8 w - - 0 1'
        with self.assertRaises(ValueError):
            self.db.record_positions(report.game_ids[0], [(0, valid), (1, 'not a fen')])
        self.assertEqual(self.db.conn.execute('SELECT COUNT(*) FROM positions').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
