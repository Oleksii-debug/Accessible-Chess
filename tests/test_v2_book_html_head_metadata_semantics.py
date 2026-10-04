from __future__ import annotations

import unittest

from acs.book_html_import import (
    BookHtmlImportError,
    BookHtmlImportErrorCode,
    import_html_book,
)
from acs.bookdocument import Diagram, Game, Heading, Note, Paragraph, Position
from acs.chesscore import Board


PGN = '''[Event "Semantic HTML"]
[White "A"]
[Black "B"]
[Result "*"]

1. e4 e5 *'''


class BookHtmlHeadMetadataSemanticsTests(unittest.TestCase):
    def test_title_and_meta_data_fen_in_head_never_publish_positions(self) -> None:
        source = f'''<html><head>
<title data-acs-fen="{Board.START}">Metadata title</title>
<meta name="author" content="Metadata author" data-acs-fen="{Board.START}">
</head><body>
<p>Visible reading text</p>
<div data-acs-fen="{Board.START}">Visible explicit position</div>
</body></html>'''
        result = import_html_book(source, source_name="head-metadata-fen.html")
        self.assertEqual(result.document.title, "Metadata title")
        self.assertEqual(result.document.author, "Metadata author")
        self.assertTrue(any(isinstance(block, Paragraph) and block.text == "Visible reading text" for block in result.document.blocks))
        positions = [block for block in result.document.blocks if isinstance(block, Position)]
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].fen, Board.START)

    def test_head_marker_and_head_chess_markup_cannot_publish_body_semantics(self) -> None:
        source = f'''<html lang="uk"><head>
<title>{{PGN 9}}</title>
{{PGN 1}}
<img src="hidden.png" alt="Hidden diagram" data-acs-fen="{Board.START}">
<div data-acs-fen="{Board.START}">Hidden position</div>
</head><body>
<h1>Visible chapter</h1><pre>{PGN}</pre>
</body></html>'''
        result = import_html_book(source, source_name="head-chess.html")
        self.assertEqual(result.document.title, "{PGN 9}")
        self.assertEqual(result.document.language, "uk")
        self.assertEqual(result.pgn_games, 0)
        self.assertEqual(result.image_references, ())
        self.assertFalse(any(isinstance(block, (Game, Diagram, Position, Note)) for block in result.document.blocks))
        self.assertTrue(any(isinstance(block, Heading) and block.text == "Visible chapter" for block in result.document.blocks))
        self.assertTrue(any(isinstance(block, Paragraph) and '[Event "Semantic HTML"]' in block.text for block in result.document.blocks))

    def test_visible_body_marker_still_delegates_one_game_to_canonical_ingress(self) -> None:
        source = f'''<html><head><title>{{PGN 9}}</title></head><body>
<h1>Game</h1><pre>{{PGN 1}}
{PGN}</pre></body></html>'''
        result = import_html_book(source, source_name="visible-game.html")
        self.assertEqual(result.document.title, "{PGN 9}")
        self.assertEqual(result.pgn_games, 1)
        self.assertEqual(sum(isinstance(block, Game) for block in result.document.blocks), 1)

    def test_hidden_and_aria_hidden_subtrees_publish_no_accessible_or_chess_semantics(self) -> None:
        for attribute in ("hidden", 'aria-hidden="TRUE"'):
            with self.subTest(attribute=attribute):
                source = f'''<html><body>
<h1>Visible before</h1>
<section {attribute}>
<p>Secret reading text</p>
<div data-acs-fen="{Board.START}">Hidden position</div>
<img src="hidden.png" alt="Hidden image" data-acs-fen="{Board.START}">
<pre>{{PGN 1}}
{PGN}</pre>
</section>
<p>Visible after</p>
</body></html>'''
                result = import_html_book(source, source_name="hidden.html", available_assets={"hidden.png"})
                rendered = "\n".join(getattr(block, "text", "") for block in result.document.blocks)
                self.assertIn("Visible before", rendered)
                self.assertIn("Visible after", rendered)
                self.assertNotIn("Secret reading text", rendered)
                self.assertNotIn('[Event "Semantic HTML"]', rendered)
                self.assertEqual(result.pgn_games, 0)
                self.assertEqual(result.image_references, ())
                self.assertFalse(any(isinstance(block, (Game, Diagram, Position, Note)) for block in result.document.blocks))

    def test_aria_hidden_false_remains_semantically_available(self) -> None:
        result = import_html_book(
            f'''<html><body>
<p aria-hidden="false">Readable text</p>
<div aria-hidden="false" data-acs-fen="{Board.START}">Visible position</div>
</body></html>''',
            source_name="aria-visible.html",
        )
        self.assertTrue(any(isinstance(block, Paragraph) and block.text == "Readable text" for block in result.document.blocks))
        positions = [block for block in result.document.blocks if isinstance(block, Position)]
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].fen, Board.START)

    def test_hidden_void_element_does_not_hide_following_visible_content(self) -> None:
        result = import_html_book(
            f'''<html><body>
<img hidden src="hidden.png" alt="Hidden image" data-acs-fen="{Board.START}">
<p>Visible after hidden image</p>
</body></html>''',
            source_name="hidden-void.html",
            available_assets={"hidden.png"},
        )
        self.assertEqual(result.image_references, ())
        self.assertFalse(any(isinstance(block, (Diagram, Position, Note)) for block in result.document.blocks))
        self.assertTrue(any(isinstance(block, Paragraph) and block.text == "Visible after hidden image" for block in result.document.blocks))

    def test_malformed_hidden_nesting_stays_fail_closed(self) -> None:
        result = import_html_book(
            '''<html><body><p>Visible before</p>
<div hidden><span>Secret text</div>
<p>Must stay omitted after mismatch</p></body></html>''',
            source_name="hidden-mismatch.html",
        )
        rendered = "\n".join(getattr(block, "text", "") for block in result.document.blocks)
        self.assertIn("Visible before", rendered)
        self.assertNotIn("Secret text", rendered)
        self.assertNotIn("Must stay omitted", rendered)
        self.assertTrue(any("mismatched hidden elements" in warning for warning in result.warnings))
        self.assertTrue(any("hidden content unclosed" in warning for warning in result.warnings))

    def test_unclosed_head_cannot_recover_hidden_chess_as_readable_content(self) -> None:
        source = f'''<html><head><title>{{PGN 1}}</title>
<div data-acs-fen="{Board.START}"><pre>{PGN}</pre>'''
        with self.assertRaises(BookHtmlImportError) as caught:
            import_html_book(source, source_name="unclosed-head.html")
        self.assertEqual(caught.exception.code, BookHtmlImportErrorCode.NO_READABLE_CONTENT)

    def test_br_table_and_nested_block_boundaries_do_not_collapse_words(self) -> None:
        cases = (
            ("<html><body><h1>White<br>to move</h1></body></html>", "White to move"),
            ("<html><body><table><tr><td>e4</td><td>e5</td></tr></table></body></html>", "e4 e5"),
            ("<html><body><p>Alpha<div>Beta</div>Gamma</p></body></html>", "Alpha Beta Gamma"),
            ("<html><body><p>Outer<blockquote>Inner<br>Line</blockquote>Tail</p></body></html>", "Outer Inner Line Tail"),
        )
        for source, expected in cases:
            with self.subTest(expected=expected):
                result = import_html_book(source, source_name="boundaries.html")
                rendered = "\n".join(getattr(block, "text", "") for block in result.document.blocks)
                self.assertIn(expected, rendered)

    def test_malformed_image_src_preserves_accessible_content_without_local_asset(self) -> None:
        source = '''<html><body>
<p>Readable before</p>
<img src="//[bad" alt="Accessible diagram description">
<p>Readable after</p>
</body></html>'''
        result = import_html_book(
            source,
            source_name="malformed-image-src.html",
            available_assets={"known.png"},
        )
        rendered = "\n".join(getattr(block, "text", "") for block in result.document.blocks)
        self.assertIn("Readable before", rendered)
        self.assertIn("Readable after", rendered)
        notes = [block for block in result.document.blocks if isinstance(block, Note)]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].text, "Accessible diagram description")
        self.assertEqual(notes[0].note_type, "image")
        self.assertEqual(result.image_references, ("//[bad",))
        self.assertEqual(result.missing_assets, ())

    def test_list_item_br_boundaries_remain_readable(self) -> None:
        result = import_html_book(
            "<html><body><ul><li>White<br>to move</li><li>Black<br/>to move</li></ul></body></html>",
            source_name="list-breaks.html",
        )
        lists = result.document.lists()
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].items, ["White to move", "Black to move"])


if __name__ == "__main__":
    unittest.main()
