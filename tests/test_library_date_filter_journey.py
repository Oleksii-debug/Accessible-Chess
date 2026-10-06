from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.full_product_ui_shell import UILanguage
from acs.library_export_service import LibraryExportRequest, LibraryExportService
from acs.library_export_workspace import build_library_export_webview
from acs.pgn_service import open_pgn
from acs.search_service import GameSearchQuery


class LibraryDateJourneyTests(unittest.TestCase):
    def setUp(self):
        self.db = AcsDatabase()
        self.addCleanup(self.db.close)
        for event, date in (('Earlier', '2025.01.01'), ('Selected', '2026.05.15'), ('Later', '2027.01.01'), ('Unknown', '2026.??.??')):
            self.db.import_pgn_text(f'[Event "{event}"]\n[Date "{date}"]\n[Result "*"]\n\n1. e4 e5 *\n', source_name=event+'.pgn')
        self.actions = []
        self.bridge = build_library_export_webview(self.db, lambda action, payload: self.actions.append((action, payload)), language=UILanguage.EN)

    def test_keyboard_search_export_preserves_exact_date_selection(self):
        result = self.bridge.dispatch('library.search', {'date_from': '2026.01.01', 'date_to': '2026.12.31'})
        self.assertEqual(result.kind, 'render')
        snapshot = result.payload['snapshot']
        self.assertEqual(len(snapshot['rows']), 1)
        self.assertIn('Selected', snapshot['rows'][0]['label'])
        filters = {f['id']: f for f in snapshot['filters']}
        self.assertEqual(filters['date_from']['value'], '2026.01.01')
        self.assertIn('YYYY.MM.DD', filters['date_to']['label'])
        self.assertEqual(self.bridge.dispatch('library.export_filtered').kind, 'delegated')
        request = LibraryExportRequest.from_payload(self.actions[-1][1])
        self.assertEqual(request.query.date_from, '2026.01.01')
        self.assertEqual(request.query.date_to, '2026.12.31')
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'filtered.pgn'
            LibraryExportService(self.db).export_to(target, request)
            games = open_pgn(target).games
            self.assertEqual(len(games), 1)
            self.assertEqual(games[0].tags['Event'], 'Selected')
        self.bridge.dispatch('library.reset_filters')
        self.assertIsNone(self.bridge.projection.query.date_from)

    def test_invalid_dates_leave_query_and_rows_unchanged(self):
        self.bridge.dispatch('library.search', {'date_from': '2026.01.01'})
        before = self.bridge.projection.snapshot()
        for payload in ({'date_from': '2026.02.30'}, {'date_from': '2026.??.??'}, {'date_from': True}, {'date_from': '2027.01.01', 'date_to': '2026.01.01'}):
            self.assertEqual(self.bridge.dispatch('library.search', payload).kind, 'error')
            self.assertEqual(self.bridge.projection.snapshot(), before)

    def test_exact_unknown_date_survives_export_request_roundtrip(self):
        request = LibraryExportRequest.filtered(GameSearchQuery(game_date='2026.??.??'))
        restored = LibraryExportRequest.from_payload(request.browser_payload())
        self.assertEqual(restored.query.game_date, '2026.??.??')

    def test_both_language_filters_have_accessible_labels(self):
        bridge = build_library_export_webview(self.db, lambda *_: None, language=UILanguage.UA)
        filters = {f['id']: f for f in bridge.projection.snapshot()['filters']}
        self.assertEqual(filters['date_from']['label'], 'Дата від (РРРР.ММ.ДД)')
