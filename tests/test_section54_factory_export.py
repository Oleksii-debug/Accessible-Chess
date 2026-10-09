from __future__ import annotations
from hashlib import sha256
import unittest
from acs.bookdocument import BookDocument, Heading, Paragraph, ListBlock, Diagram, Game
from acs.format_factory_export import FactoryExportError, export_factory_preview

FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
SHA = "a" * 64


class FactoryExportTests(unittest.TestCase):
    def test_html_semantics_escape_untrusted_content(self) -> None:
        book = BookDocument(title="Chess <script>danger</script>", language="en",
                            blocks=[Heading(text="Strategy <&>", level=2),
                                    Paragraph(text="Notation & diagrams"),
                                    ListBlock(items=["<img src=x>", "Second"], ordered=True)])
        output = export_factory_preview(book, source_sha256=SHA)
        html = output.output_bytes.decode()
        self.assertIn("<h2>Strategy &lt;&amp;&gt;</h2>", html)
        self.assertIn("<ol>", html)
        self.assertIn("&lt;img src=x&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertEqual(output.losses, ())
        self.assertEqual(output.output_sha256, sha256(output.output_bytes).hexdigest())
        self.assertFalse(output.public_release_approved)

    def test_plain_text_declares_structure_loss_and_requires_explicit_approval(self) -> None:
        book = BookDocument(title="Book", blocks=[Heading(text="Chapter", level=2)])
        with self.assertRaises(FactoryExportError):
            export_factory_preview(book, source_sha256=SHA, output_format="txt")
        output = export_factory_preview(book, source_sha256=SHA, output_format="txt", allow_semantic_loss=True)
        self.assertIn("TEXT_STRUCTURE_NOT_MACHINE_NAVIGABLE", output.losses)
        self.assertIn(b"Heading 2: Chapter", output.output_bytes)

    def test_diagram_cannot_be_falsely_lossless(self) -> None:
        book = BookDocument(title="Book", blocks=[Diagram(fen=FEN, alt_text="Opening position")])
        with self.assertRaises(FactoryExportError):
            export_factory_preview(book, source_sha256=SHA)
        output = export_factory_preview(book, source_sha256=SHA, allow_semantic_loss=True)
        self.assertIn("ORIGINAL_DIAGRAM_GRAPHICS_NOT_REPRODUCED", output.losses)
        self.assertIn("Opening position", output.output_bytes.decode())
        self.assertIn(FEN, output.output_bytes.decode())

    def test_game_reference_without_source_pgn_is_blocked(self) -> None:
        book = BookDocument(title="Book", blocks=[Game(game_id=17)])
        with self.assertRaises(FactoryExportError):
            export_factory_preview(book, source_sha256=SHA)

    def test_invalid_format_does_not_emit_bytes(self) -> None:
        book = BookDocument(title="Book", blocks=[Paragraph(text="Hello")])
        for output_format in ("pdf", "epub3", "pgn", "docx"):
            with self.subTest(output_format=output_format), self.assertRaises(FactoryExportError):
                export_factory_preview(book, source_sha256=SHA, output_format=output_format)


if __name__ == "__main__":
    unittest.main()
