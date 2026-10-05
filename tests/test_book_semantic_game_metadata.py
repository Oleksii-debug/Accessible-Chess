import json
import unittest
from unittest.mock import patch

from acs.analysis_service import AnalysisService
from acs.book_board_workflow import BookBoardWorkflow
from acs.bookdocument import BookDocument, Game, Paragraph
from acs.bookreader import BookReader
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.full_product_ui_shell import UILanguage
from acs.version2_book_workspace import build_version2_book_webview


class BookSemanticGameMetadataTests(unittest.TestCase):
    def test_narrative_source_language_uses_detached_reader_metadata(self):
        document = BookDocument('Study', language='en-GB', blocks=[Paragraph(text='English prose')])
        reader = BookReader(document)
        analysis = AnalysisService(lambda: None)
        self.addCleanup(analysis.close)
        workflow = BookBoardWorkflow(reader, EngineAssistedWorkflowService(analysis))
        bridge = build_version2_book_webview(reader, workflow, lambda *_: None, language=UILanguage.UA)
        document.language = 'uk'
        snapshot = bridge.projection.snapshot()
        self.assertEqual(snapshot['block']['content_language'], 'en-GB')
        self.assertEqual(snapshot['document']['lang'], 'uk')

    def test_invalid_source_language_is_not_a_browser_attribute(self):
        for language in ('x' * 64, 'en\" onclick=\"attack', 'C:/private/book'):
            reader = BookReader(BookDocument('Study', language=language, blocks=[Paragraph(text='Prose')]))
            analysis = AnalysisService(lambda: None)
            self.addCleanup(analysis.close)
            workflow = BookBoardWorkflow(reader, EngineAssistedWorkflowService(analysis))
            bridge = build_version2_book_webview(reader, workflow, lambda *_: None)
            self.assertNotIn('content_language', bridge.projection.snapshot()['block'])
    def compose(self, pgn, language=UILanguage.UA):
        reader = BookReader(BookDocument('Study', blocks=[Game(pgn=pgn)]))
        analysis = AnalysisService(lambda: None)
        self.addCleanup(analysis.close)
        workflow = BookBoardWorkflow(reader, EngineAssistedWorkflowService(analysis))
        bridge = build_version2_book_webview(reader, workflow, lambda *_: None, language=language)
        return reader, workflow, bridge

    def test_metadata_is_readable_localized_and_does_not_open_board(self):
        pgn = ('[Event "Навчання"]\n[Site "Nitra"]\n[Date "2026.??.??"]\n'
               '[Round "3"]\n[ECO "C20"]\n[Opening "King pawn"]\n'
               '[PrivateOwner "never publish this tag"]\n1. e4 *')
        for language, label in ((UILanguage.UA, 'Подія'), (UILanguage.EN, 'Event')):
            with self.subTest(language=language):
                reader, workflow, bridge = self.compose(pgn, language)
                before = reader.snapshot()
                snapshot = bridge.projection.snapshot()
                details = snapshot['semantic_tree']['details']
                self.assertEqual(len(details), 6)
                self.assertIn({'kind': 'event', 'label': label, 'value': 'Навчання'}, details)
                self.assertEqual(next(row['value'] for row in details if row['kind'] == 'date'), '2026.??.??')
                self.assertNotIn('never publish this tag', json.dumps(snapshot))
                self.assertFalse(workflow.active)
                self.assertEqual(reader.snapshot(), before)

    def test_local_source_paths_in_metadata_are_redacted(self):
        _, _, bridge = self.compose('[Event "Study C:\\\\private\\\\source.pgn"]\n1. e4 *')
        snapshot = bridge.projection.snapshot()
        self.assertEqual(len(snapshot['semantic_tree']['details']), 1)
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn('C:\\\\private', serialized)
        self.assertIn('локальний шлях приховано', serialized)

    def test_oversized_metadata_fails_reading_with_warning_and_preserves_board_handoff(self):
        for value in ('x' * 1201, '🙂' * 601):
            with self.subTest(units=len(value)):
                reader, workflow, bridge = self.compose('[Event "' + value + '"]\n1. e4 *')
                origin = reader.snapshot()
                snapshot = bridge.projection.snapshot()
                self.assertIsNone(snapshot['semantic_tree'])
                self.assertTrue(snapshot['block']['warning'])
                self.assertTrue(next(action['enabled'] for action in snapshot['actions'] if action['command'] == 'book.open_game'))
                self.assertFalse(workflow.active)
                self.assertEqual(reader.snapshot(), origin)

    def test_hostile_metadata_subclass_fails_before_custom_string_hooks(self):
        class StripBomb(str):
            touched = False

            def strip(self, *args):
                type(self).touched = True
                raise AssertionError('custom metadata hook must not run')

        _, workflow, bridge = self.compose('1. e4 *')
        mode, game, warnings = workflow.semantic_game_snapshot(0)
        game.tags['Event'] = StripBomb('Study')
        with patch.object(workflow, 'semantic_game_snapshot', return_value=(mode, game, warnings)):
            snapshot = bridge.projection.snapshot()
        self.assertIsNone(snapshot['semantic_tree'])
        self.assertTrue(snapshot['block']['warning'])
        self.assertFalse(StripBomb.touched)


if __name__ == '__main__':
    unittest.main()
