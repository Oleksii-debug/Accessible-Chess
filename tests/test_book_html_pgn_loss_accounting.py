from html import escape
from io import BytesIO
import unittest
import zipfile

from acs.bookdocument import BookDocument, Game, Paragraph
from acs.book_epub_import import import_epub_book
from acs.book_html_import import import_html_book
from acs.book_game_content import resolve_book_game
from acs.analysis_service import AnalysisService
from acs.book_board_workflow import BookBoardWorkflow
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from unittest.mock import patch
import acs.book_html_import as html_import


def html_book(pgn):
    return ('<html><head><title>Study</title></head><body>'
            '<p>Before</p><pre id="game-source">{PGN 1}\n'
            + escape(pgn) + '</pre><p>After</p></body></html>')


def epub_book(chapter):
    output = BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        archive.writestr('META-INF/container.xml', '''<container version="1.0"
xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>
<rootfile full-path="OEBPS/book.opf" media-type="application/oebps-package+xml"/>
</rootfiles></container>''')
        archive.writestr('OEBPS/book.opf', '''<package version="3.0" unique-identifier="uid"
xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="uid">urn:acs:loss-accounting</dc:identifier><dc:title>Study</dc:title>
<dc:language>en</dc:language><meta property="dcterms:modified">2026-10-04T00:00:00Z</meta>
</metadata><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
</manifest><spine><itemref idref="chapter"/></spine></package>''')
        archive.writestr('OEBPS/chapter.xhtml', chapter)
        archive.writestr('OEBPS/nav.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml"><body><nav/></body></html>')
    return output.getvalue()


class HtmlPgnLossAccountingTests(unittest.TestCase):
    def test_rejected_pgn_stays_readable_at_exact_location(self):
        pgn = '[Event "Broken"]\n1. not-a-move *'
        result = import_html_book(html_book(pgn), source_name='study.html')
        self.assertEqual(result.pgn_games, 0)
        self.assertFalse(any(type(block) is Game for block in result.document.blocks))
        self.assertEqual([block.text for block in result.document.blocks], ['Before', pgn, 'After'])
        self.assertIs(type(result.document.blocks[1]), Paragraph)
        self.assertEqual(result.document.blocks[1].source_anchor, 'game-source')
        self.assertTrue(result.warnings)
        restored = BookDocument.from_dict(result.document.as_dict())
        self.assertEqual(restored.as_dict(), result.document.as_dict())

    def test_multi_game_region_becomes_individual_games_in_reading_order(self):
        pgn = '[Event "One"]\n1. e4 *\n\n[Event "Two"]\n1. d4 *'
        result = import_html_book(html_book(pgn), source_name='study.html')
        self.assertEqual(result.pgn_games, 2)
        self.assertEqual([type(block) for block in result.document.blocks], [Paragraph, Game, Game, Paragraph])
        self.assertEqual([resolve_book_game(block).game.tags['Event'] for block in result.document.blocks[1:3]], ['One', 'Two'])
        self.assertNotEqual(result.document.blocks[1].block_id, result.document.blocks[2].block_id)
        self.assertTrue(any('source formatting normalized' in warning for warning in result.warnings))

    def test_recovery_diagnostics_reach_report_and_source_stays_unchanged(self):
        pgn = '[Event "Recovered"]\n1. e4 {comment without end'
        result = import_html_book(html_book(pgn), source_name='study.html')
        self.assertEqual(result.pgn_games, 1)
        block = result.document.blocks[1]
        self.assertIs(type(block), Game)
        self.assertEqual(block.pgn, pgn)
        self.assertEqual(block.source_anchor, 'game-source')
        resolved = resolve_book_game(block)
        self.assertTrue(resolved.warnings)
        for warning in resolved.warnings:
            self.assertIn('PGN candidate 1: ' + warning, result.warnings)
        self.assertEqual(result.document.warnings, list(result.warnings))

    def test_epub_preserves_rejected_text_location_and_package_anchor(self):
        pgn = '[Event "Broken"]\n1. not-a-move *'
        result = import_epub_book(epub_book(html_book(pgn)), source_name='study.epub')
        self.assertEqual(result.pgn_games, 0)
        self.assertEqual([block.text for block in result.document.blocks], ['Before', pgn, 'After'])
        self.assertEqual(result.document.blocks[1].source_anchor, 'OEBPS/chapter.xhtml#game-source')
        self.assertTrue(result.warnings)

    def test_valid_game_keeps_comment_variation_and_explicit_anchor(self):
        pgn = '[Event "Study"]\n1. e4 {Main} (1. d4 {Side}) e5 *'
        result = import_html_book(html_book(pgn), source_name='study.html')
        block = result.document.blocks[1]
        self.assertEqual(block.source_anchor, 'game-source')
        resolved = resolve_book_game(block)
        self.assertEqual(resolved.game.line.moves[0].comments_after[0].text, 'Main')
        self.assertEqual(resolved.game.line.moves[0].variations[0].moves[0].comments_after[0].text, 'Side')

    def test_epub_collection_nested_variations_board_and_exact_return(self):
        pgn = ('[Event "Éтюд"]\n[White "Олексій"]\n[Black "Émile"]\n'
               '1. e4 {Головний} (1. d4 $1 {Гілка} (1. c4 {Nested}) d5) e5 *\n\n'
               '[Event "Second"]\n1. Nf3 *')
        result = import_epub_book(epub_book(html_book(pgn)), source_name='study.epub')
        self.assertEqual(result.pgn_games, 2)
        reader = BookReader(result.document)
        reader.go_to(1)
        origin = reader.location()
        analysis = AnalysisService(lambda: self.fail('navigation must not instantiate an engine'))
        self.addCleanup(analysis.close)
        workflow = BookBoardWorkflow(reader, EngineAssistedWorkflowService(analysis))
        self.assertEqual(workflow.open_current().current_fen, Board.START)
        main = Board(); main.push_text('e4')
        self.assertEqual(workflow.next_move().current_fen, main.fen())
        self.assertEqual(workflow.enter_variation(0).current_fen, Board.START)
        branch = Board(); branch.push_text('d4')
        self.assertEqual(workflow.next_move().current_fen, branch.fen())
        self.assertEqual(workflow.enter_variation(0).current_fen, Board.START)
        nested = Board(); nested.push_text('c4')
        self.assertEqual(workflow.next_move().current_fen, nested.fen())
        self.assertEqual(workflow.leave_variation().current_fen, branch.fen())
        self.assertEqual(workflow.leave_variation().current_fen, main.fen())
        self.assertEqual(workflow.return_to_book(), origin)
        self.assertEqual(reader.location(), origin)
        reader.go_to(2)
        self.assertEqual(workflow.open_current().current_fen, Board.START)
        second = Board(); second.push_text('Nf3')
        self.assertEqual(workflow.next_move().current_fen, second.fen())
        workflow.return_to_book()
        self.assertEqual(reader.location().index, 2)

    def test_collection_game_count_limit_is_not_reset_per_region(self):
        pgn = '[Event "One"]\n1. e4 *\n\n[Event "Two"]\n1. d4 *'
        with patch.object(html_import, 'MAX_HTML_PGN_GAMES', 1):
            with self.assertRaises(html_import.BookHtmlImportError) as caught:
                import_html_book(html_book(pgn), source_name='study.html')
        self.assertEqual(caught.exception.code, html_import.BookHtmlImportErrorCode.RESOURCE_LIMIT)

    def test_split_collection_retains_setup_fen_and_nags(self):
        start = Board(); start.push_text('e4')
        pgn = ('[Event "From position"]\n[SetUp "1"]\n[FEN "' + start.fen()
               + '"]\n1... c5 $2 {Sicilian} *\n\n[Event "Other"]\n1. d4 *')
        result = import_html_book(html_book(pgn), source_name='study.html')
        first = resolve_book_game(result.document.blocks[1]).game
        self.assertEqual(first.tags['FEN'], start.fen())
        self.assertEqual(first.tags['SetUp'], '1')
        self.assertEqual(first.line.moves[0].nags, ['$2'])
        self.assertEqual(first.line.moves[0].comments_after[0].text, 'Sicilian')


if __name__ == '__main__':
    unittest.main()
