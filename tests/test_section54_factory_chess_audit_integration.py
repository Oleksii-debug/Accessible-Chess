from __future__ import annotations

"""Private conversion must reject structurally illegal chess before any output."""

from hashlib import sha256
import unittest

from acs.format_factory_conversion import FactoryConversionError, convert_factory_book_private
from acs.format_factory_policy import FactoryJobPolicy, FactorySelection


def make_policy(source: bytes) -> FactoryJobPolicy:
    return FactoryJobPolicy(
        source_id="chess-book",
        source_sha256=sha256(source).hexdigest(),
        selection=FactorySelection("all"),
        output_formats=("html",),
        output_language="en",
    )


def pgn(moves: str) -> bytes:
    return ('[Event "Factory chess reading"]\n[Result "*"]\n\n' + moves).encode("utf-8")


class FactoryChessAuditIntegrationTests(unittest.TestCase):
    def test_legal_pgn_exports_private_html_with_explicit_unverified_source(self):
        source = pgn("1. e4 e5 2. Nf3 Nc6 *")
        result = convert_factory_book_private(
            source, source_name="lesson.pgn", policy=make_policy(source),
            source_language="en",
        )
        self.assertEqual(len(result.outputs), 1)
        self.assertEqual(result.outputs[0].output_format, "html")
        self.assertIsNotNone(result.chess_audit)
        self.assertEqual(result.chess_audit.legal_chess_blocks, 1)
        self.assertEqual(result.chess_audit.blocks[0].legal_moves, 4)
        self.assertTrue(result.chess_audit.structure_complete)
        self.assertFalse(result.chess_audit.source_verified)
        self.assertFalse(result.chess_audit.ready_for_publication)
        self.assertFalse(result.public_release_approved)
        self.assertFalse(result.outputs[0].public_release_approved)

    def test_illegal_chess_pgn_is_not_returned_as_successful_conversion(self):
        source = pgn("1. e4 e5 2. Bh5 *")
        with self.assertRaises(FactoryConversionError):
            convert_factory_book_private(
                source, source_name="wrong.pgn", policy=make_policy(source),
                source_language="en",
            )

    def test_plain_book_has_explicit_zero_chess_audit_without_fidelity_claim(self):
        source = b"# Chapter one\n\nThe move e4 is mentioned in prose only.\n"
        result = convert_factory_book_private(
            source, source_name="intro.md", policy=make_policy(source),
            source_language="en",
        )
        self.assertEqual(result.chess_audit.chess_blocks, 0)
        self.assertTrue(result.chess_audit.structure_complete)
        self.assertFalse(result.chess_audit.source_verified)
        self.assertFalse(result.chess_audit.ready_for_publication)


if __name__ == "__main__":
    unittest.main()
