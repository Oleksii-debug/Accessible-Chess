"""Owner-reported gameplay regressions; machine evidence, never an NVDA claim."""
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.chesscore import Board
from acs.full_product_presenters import LibraryPresenter
from acs.library_import_service import LibraryImportService
from acs.library_webview_projection import LibraryWebViewProjection
from acs.pgn_roundtrip import parse_pgn_text
from acs.release_app import create_release_api
from acs.search_service import GameSearchQuery, GameSearchService
from acs.settings import Settings
from acs.sound_events import SoundEvent
from acs.version2_application import Version2Application
from tests.test_stage1_release_composition_ui import _FakeRuntime, _Playback


class OwnerGameplayFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='Шахи пробіли ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.playback = _Playback()
        self.api, self.runtime = create_release_api(
            application_dir=self.root, runtime_factory=_FakeRuntime,
            sound_playback=self.playback, settings_path=self.root / 'settings.json',
        )
        self.addCleanup(self.runtime.close)
        self.addCleanup(self.api.close_analysis)

    def test_lowercase_knight_move_updates_board_history_and_emits_move_sound(self):
        for notation in ('e4', 'e5', 'nf3'):
            self.assertTrue(self.api.make_move(notation)['ok'])
        state = self.api.get_state()
        self.assertEqual(self.api.sans, ['e4', 'e5', 'Nf3'])
        self.assertEqual(self.api.board.board[21], 'N')
        self.assertEqual(state['lastMove'], 'кінь f 3')
        self.assertEqual(state['announcement'], 'Зіграно: кінь f 3')
        self.assertEqual([event for event, _ in self.playback.calls], [SoundEvent.MOVE] * 3)
        self.assertTrue(all(volume == 80 for _, volume in self.playback.calls))

    def test_uppercase_san_and_coordinate_moves_still_work(self):
        for notation in ('e2e4', 'e7e5', 'Nf3'):
            self.assertTrue(self.api.make_move(notation)['ok'])
        self.assertEqual(self.api.sans[-1], 'Nf3')

    def test_pawn_b_capture_keeps_precedence_over_lowercase_bishop(self):
        self.api.set_fen('4k3/8/8/8/8/2p5/1P6/4K3 w - - 0 1')
        self.assertTrue(self.api.make_move('bxc3')['ok'])
        self.assertEqual(self.api.sans[-1], 'bxc3')

    def test_lowercase_bishop_and_rook_preserve_canonical_disambiguation(self):
        self.api.set_fen('4k3/8/8/8/8/8/8/R3K3 w - - 0 1')
        result = self.api.make_move('ra3')
        self.assertTrue(result['ok'])
        self.assertEqual(self.api.sans[-1], 'Ra3')
        self.assertEqual(result['lastMove'], 'тура a 3')
        self.assertNotIn('1', result['lastMove'])
        self.api.set_fen('4k3/8/8/R7/8/8/8/R3K3 w - - 0 1')
        before = self.api.board.fen()
        self.assertFalse(self.api.make_move('ra3')['ok'])
        self.assertEqual(self.api.board.fen(), before)
        self.assertTrue(self.api.make_move('r1a3')['ok'])
        self.assertEqual(self.api.sans[-1], 'R1a3')

    def test_human_case_tolerance_does_not_relax_canonical_import_parser(self):
        board = Board()
        board.push_text('e4'); board.push_text('e5')
        with self.assertRaises(ValueError):
            board.parse_move('nf3')

    def test_invalid_input_keeps_position_and_uses_neutral_feedback(self):
        before = self.api.board.fen()
        result = self.api.make_move('nf9')
        self.assertFalse(result['ok'])
        self.assertEqual(self.api.board.fen(), before)
        self.assertFalse(result['announceMoveErrors'])
        self.assertNotIn('легаль', result['announcement'].lower())
        self.assertEqual(self.api.sans, [])

    def test_move_feedback_preference_roundtrips_and_rejects_non_boolean(self):
        self.assertFalse(self.api.get_move_feedback_settings()['enabled'])
        self.assertTrue(self.api.set_move_error_announcements(True)['ok'])
        self.assertTrue(self.api.make_move('e9')['announceMoveErrors'])
        reopened = Settings(self.root / 'settings.json')
        self.assertTrue(reopened.get('announce_move_errors'))
        self.assertFalse(self.api.set_move_error_announcements('false')['ok'])
        self.assertTrue(self.api.get_move_feedback_settings()['enabled'])
        self.assertTrue(self.api.set_move_error_announcements(False)['ok'])
        self.assertFalse(Settings(self.root / 'settings.json').get('announce_move_errors'))

    def test_move_feedback_settings_fail_closed_without_backing_store(self):
        settings = self.api._settings
        try:
            self.api._settings = None
            self.assertEqual(
                self.api.get_move_feedback_settings(),
                {'ok': False, 'enabled': False},
            )
            self.assertEqual(
                self.api.set_move_error_announcements(True),
                {'ok': False, 'enabled': False},
            )
        finally:
            self.api._settings = settings

    def test_sound_settings_fail_closed_without_backing_store(self):
        settings = self.api._settings
        try:
            self.api._settings = None
            state = self.api.get_sound_settings()
            self.assertFalse(state['ok'])
            self.assertTrue(state['enabled'])
            self.assertEqual(state['volume'], 80)
            self.assertFalse(self.api.set_sound_enabled(False)['ok'])
        finally:
            self.api._settings = settings

    def test_mutable_ui_settings_fail_closed_when_persistence_is_unavailable(self):
        settings = self.api._settings
        baseline_known = settings._baseline_known
        blocked_reason = settings._write_blocked_reason
        original_feedback = settings.get('announce_move_errors', False)
        try:
            settings._baseline_known = False
            self.assertFalse(self.api.get_sound_settings()['ok'])
            self.assertEqual(
                self.api.get_move_feedback_settings(),
                {'ok': False, 'enabled': False},
            )
            self.assertFalse(self.api.set_move_error_announcements(True)['ok'])
            self.assertEqual(
                settings.get('announce_move_errors', False),
                original_feedback,
            )

            settings._baseline_known = True
            settings._write_blocked_reason = 'future schema'
            self.assertFalse(self.api.get_sound_settings()['ok'])
            self.assertEqual(
                self.api.get_move_feedback_settings(),
                {'ok': False, 'enabled': False},
            )
            self.assertFalse(self.api.set_move_error_announcements(True)['ok'])
            self.assertEqual(
                settings.get('announce_move_errors', False),
                original_feedback,
            )
        finally:
            settings._baseline_known = baseline_known
            settings._write_blocked_reason = blocked_reason

    def test_new_position_dispatch_resets_and_plays_start_sound(self):
        self.api.make_move('e4')
        result = self.api.dispatch_action('file.new')
        self.assertTrue(result['ok'])
        self.assertEqual(self.api.board.fen(), Board().fen())
        self.assertEqual(self.playback.calls[-1], (SoundEvent.START, 80))
        self.assertEqual(self.api.keymap_resolve_binding('global', 'Ctrl+N')['actionId'], 'file.new')

    def test_piece_summaries_are_single_paragraph_and_game_info_has_no_build_noise(self):
        state = self.api.get_state()
        for color in ('whitePieces', 'blackPieces'):
            self.assertNotIn('\n', state[color])
            self.assertIn('; ', state[color])
        self.assertNotIn('Version', state['gameInfo'])
        self.assertNotIn('бета', state['gameInfo'])
        self.assertNotIn('Accessible Chess', state['gameInfo'])

    def test_library_lists_imported_games_immediately_after_reopen(self):
        db_path = self.root / 'Бібліотека.acsdb'
        db = AcsDatabase(db_path)
        try:
            games = parse_pgn_text('[Event "Existing library"]\n[White "Alpha"]\n[Black "Beta"]\n[Result "*"]\n\n1. e4 e5 *\n')
            LibraryImportService(db).import_games(games, source_name='games.pgn', source_format='PGN', source_sha256='a' * 64)
        finally:
            db.close()
        reopened = AcsDatabase(db_path)
        try:
            analysis = AnalysisService(lambda: None)
            self.addCleanup(analysis.close)
            app = Version2Application(reopened,
                progress_store=BookProgressStore(self.root / "progress.json"),
                engine_assistance=EngineAssistedWorkflowService(analysis),
                board_dispatch=self.api.dispatch_action)
            snapshot = app.library.projection.snapshot()
            self.assertEqual(len(snapshot['rows']), 1)
            self.assertIn('Alpha', snapshot['rows'][0]['label'])
        finally:
            reopened.close()

    def test_empty_library_and_empty_filtered_search_have_distinct_messages(self):
        db = AcsDatabase(self.root / 'empty.acsdb')
        try:
            projection = LibraryWebViewProjection(LibraryPresenter(GameSearchService(db)), lambda *_: None)
            projection.search(GameSearchQuery())
            self.assertIn('ще немає партій', projection.snapshot()['summary'])
            projection.search(GameSearchQuery(player='Nobody'))
            self.assertIn('фільтрами', projection.snapshot()['summary'])
        finally:
            db.close()
