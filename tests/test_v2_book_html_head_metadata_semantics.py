from __future__ import annotations

import unittest

from acs.book_html_import import import_html_book
from acs.bookdocument import Paragraph, Position
from acs.chesscore import Board


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
        self.assertTrue(
            any(
                isinstance(block, Paragraph) and block.text == "Visible reading text"
                for block in result.document.blocks
            )
        )
        positions = [
            block for block in result.document.blocks if isinstance(block, Position)
        ]
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].fen, Board.START)


if __name__ == "__main__":
    unittest.main()
