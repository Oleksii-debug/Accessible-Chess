import unittest

from acs.bookdocument import (
    BOOK_DOCUMENT_SCHEMA_VERSION,
    BookDocument,
    BookDocumentError,
    BookDocumentErrorCode,
    Diagram,
    Exercise,
    Game,
    Heading,
    Note,
    Paragraph,
    Position,
    VariationTree,
)


FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"


class BookDocumentTests(unittest.TestCase):
    def test_semantic_book_preserves_reading_order(self):
        book = BookDocument("Accessible test book", language="uk", author="Author")
        book.extend([
            Heading(text="Розділ 1", level=1, block_id="h1"),
            Paragraph(text="Авторський вступ."),
            Position(fen=FEN, caption="Позиція 1"),
            Game(pgn="[Result \"*\"]\n\n*", title="Приклад"),
            Note(text="Зверніть увагу на короля."),
        ])
        self.assertEqual([block.kind for block in book.blocks], [
            "Heading", "Paragraph", "Position", "Game", "Note"
        ])
        self.assertEqual(book.headings()[0].text, "Розділ 1")
        self.assertEqual(book.as_dict()["blocks"][2]["fen"], FEN)

    def test_semantic_dict_round_trip_preserves_block_types_and_source_anchors(self):
        original = BookDocument(
            "Round trip",
            language="uk",
            author="Author",
            source_name="source.docx",
            warnings=["source warning"],
            blocks=[
                Heading(text="Розділ", level=1, block_id="h1", source_anchor="p12"),
                Diagram(fen=FEN, caption="Diagram", alt_text="White king e2; black king h1", source_anchor="p13"),
                VariationTree(root_fen=FEN, pgn="1. Kf3 (1. Kd3) *", title="Line", source_anchor="p14"),
                Exercise(fen=FEN, prompt="Find a move", answer_text="Kf3", difficulty="beginner", source_anchor="p15"),
            ],
        )
        restored = BookDocument.from_dict(original.as_dict())
        self.assertEqual(
            original.as_dict()["schema_version"],
            BOOK_DOCUMENT_SCHEMA_VERSION,
        )
        self.assertEqual(restored.as_dict(), original.as_dict())
        self.assertIsInstance(restored.blocks[0], Heading)
        self.assertIsInstance(restored.blocks[1], Diagram)
        self.assertIsInstance(restored.blocks[2], VariationTree)
        self.assertIsInstance(restored.blocks[3], Exercise)
        self.assertEqual(restored.blocks[1].source_anchor, "p13")

    def test_unknown_semantic_data_is_rejected_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, "Unsupported BookDocument fields"):
            BookDocument.from_dict({"title": "Book", "mystery": 1})
        with self.assertRaisesRegex(ValueError, "Unsupported BookDocument block kind"):
            BookDocument.from_dict({"title": "Book", "blocks": [{"kind": "Video", "url": "x"}]})
        with self.assertRaisesRegex(ValueError, "Unsupported fields for Paragraph"):
            BookDocument.from_dict({"title": "Book", "blocks": [{"kind": "Paragraph", "text": "ok", "lost": "no"}]})

    def test_diagram_requires_accessibility_warning_when_alt_missing(self):
        book = BookDocument("Book")
        book.append(Diagram(fen=FEN, caption="Diagram"))
        warnings = book.validate_structure()
        self.assertTrue(any("no alt_text" in warning for warning in warnings))

    def test_heading_jump_and_duplicate_ids_are_reported_not_silently_lost(self):
        book = BookDocument("Book")
        book.extend([
            Heading(text="One", level=1, block_id="same"),
            Heading(text="Too deep", level=3, block_id="same"),
        ])
        warnings = book.validate_structure()
        self.assertTrue(any("heading level jumps" in warning for warning in warnings))
        self.assertTrue(any("duplicate block_id" in warning for warning in warnings))

    def test_exercise_carries_prompt_and_solution(self):
        exercise = Exercise(
            fen=FEN,
            prompt="Знайдіть найкращий хід.",
            solution_pgn="1. Kf3 *",
            difficulty="beginner",
        )
        book = BookDocument("Exercises", blocks=[exercise])
        self.assertEqual(book.exercises()[0].difficulty, "beginner")

    def test_variation_tree_keeps_root_position_and_pgn(self):
        tree = VariationTree(root_fen=FEN, pgn="1. Kf3 (1. Kd3) *")
        self.assertEqual(tree.root_fen, FEN)
        self.assertIn("(1. Kd3)", tree.pgn)

    def test_invalid_semantic_blocks_fail_explicitly(self):
        with self.assertRaises(ValueError):
            Heading(text="", level=1)
        with self.assertRaises(ValueError):
            Heading(text="Bad", level=7)
        with self.assertRaises(ValueError):
            Position(fen="bad fen")
        with self.assertRaises(ValueError):
            Exercise(fen=FEN, prompt="Solve", solution_pgn=None, answer_text=None)

    def test_schema_version_is_explicit_with_bounded_legacy_read(self):
        legacy = {
            "title": "Legacy",
            "blocks": [{"kind": "Paragraph", "text": "Preserved"}],
        }
        migrated = BookDocument.from_dict(legacy)
        self.assertEqual(
            migrated.as_dict()["schema_version"],
            BOOK_DOCUMENT_SCHEMA_VERSION,
        )

        for invalid_version in (True, "1", 3, -1):
            with self.subTest(version=invalid_version):
                with self.assertRaises(BookDocumentError) as caught:
                    BookDocument.from_dict(
                        {"schema_version": invalid_version, "title": "Book"}
                    )
                self.assertEqual(
                    caught.exception.code,
                    BookDocumentErrorCode.UNSUPPORTED_SCHEMA,
                )

    def test_heading_and_reference_ids_reject_scalar_coercion(self):
        for level in (True, False, "2", 2.0, None):
            with self.subTest(level=level):
                with self.assertRaises(BookDocumentError) as caught:
                    Heading(text="Heading", level=level)
                self.assertEqual(
                    caught.exception.code,
                    BookDocumentErrorCode.INVALID_FIELD,
                )

        heading = Heading(
            text="Heading",
            level=2,
            block_id="  stable-id  ",
            source_anchor="  source-1  ",
        )
        self.assertEqual(heading.block_id, "stable-id")
        self.assertEqual(heading.source_anchor, "source-1")
        for field, value in (("block_id", True), ("source_anchor", 17)):
            with self.subTest(field=field):
                with self.assertRaises(BookDocumentError):
                    Heading(text="Heading", **{field: value})

    def test_fen_fields_are_structural_and_canonical_not_length_only(self):
        invalid_fens = (
            None,
            True,
            "bad fen",
            "9/8/8/8/8/8/8/8 w - -",
            "8/8/8/8/8/8/8/7Z w - -",
            "44/8/8/8/8/8/8/8 w - -",
            "8/8/8/8/8/8/8/8 white - -",
            "8/8/8/8/8/8/8/8 w KK -",
            "8/8/8/8/8/8/8/8 w qK -",
            "8/8/8/8/8/8/8/8 w - e3",
            "8/8/8/8/8/8/8/8 w - - 00 1",
            "8/8/8/8/8/8/8/8 w - - 0 0",
        )
        for fen in invalid_fens:
            with self.subTest(fen=fen):
                with self.assertRaises(BookDocumentError) as caught:
                    Position(fen=fen)
                self.assertEqual(
                    caught.exception.code,
                    BookDocumentErrorCode.INVALID_FIELD,
                )

        four_field = Position(fen="8/8/8/8/8/8/4K3/7k b - -")
        self.assertEqual(four_field.fen, "8/8/8/8/8/8/4K3/7k b - -")

    def test_fen_requires_a_playable_canonical_position(self):
        invalid_fens = (
            "8/8/8/8/8/8/8/8 w - - 0 1",
            "8/8/8/8/8/8/8/4Kk2 w - - 0 1",
            "7k/8/8/8/8/8/8/K6R w - - 0 1",
            "7k/8/8/8/8/8/8/K7 w - e6 0 1",
        )
        for fen in invalid_fens:
            with self.subTest(fen=fen):
                with self.assertRaises(BookDocumentError):
                    Position(fen=fen)

    def test_embedded_pgn_is_exactly_one_lossless_legal_game(self):
        Game(pgn='[Result "*"]\n\n1. e4 e5 *')

        invalid_games = (
            '1. e4 e5 2. Bh6 *',
            '1. e4 (1... e5 *',
            '[Result "*"]\n\n1. e4 *\n\n[Result "*"]\n\n1. d4 *',
        )
        for pgn in invalid_games:
            with self.subTest(pgn=pgn):
                with self.assertRaises(BookDocumentError) as caught:
                    Game(pgn=pgn)
                self.assertEqual(
                    caught.exception.code,
                    BookDocumentErrorCode.INVALID_CHESS_CONTENT,
                )

    def test_variation_and_exercise_solutions_are_linked_from_exact_root(self):
        root = "8/8/8/8/8/8/8/K6k w - - 0 1"
        VariationTree(root_fen=root, pgn="1. Ka2 *")
        Exercise(fen=root, prompt="Move", solution_pgn="1. Ka2 *")

        for construct in (
            lambda: VariationTree(root_fen=root, pgn="1. Ka3 *"),
            lambda: Exercise(fen=root, prompt="Move", solution_pgn="1. Ka3 *"),
            lambda: VariationTree(
                root_fen=root,
                pgn='[SetUp "1"]\n[FEN "7k/8/8/8/8/8/8/K7 w - - 0 1"]\n\n1. Ka2 *',
            ),
            lambda: VariationTree(
                root_fen=root,
                pgn='[FEN "8/8/8/8/8/8/8/K6k w - - 0 1"]\n\n1. Ka2 *',
            ),
        ):
            with self.subTest(construct=construct):
                with self.assertRaises(BookDocumentError) as caught:
                    construct()
                self.assertEqual(
                    caught.exception.code,
                    BookDocumentErrorCode.INVALID_CHESS_CONTENT,
                )

    def test_game_and_optional_metadata_require_exact_types(self):
        for invalid_id in (True, False, "7", 7.0, -1):
            with self.subTest(game_id=invalid_id):
                with self.assertRaises(BookDocumentError):
                    Game(game_id=invalid_id)
        for constructor in (
            lambda: Game(pgn=17),
            lambda: Paragraph(text=True),
            lambda: Note(text="Note", note_type=False),
            lambda: Diagram(fen=FEN, alt_text=True),
            lambda: BookDocument("Book", language=1),
            lambda: BookDocument("Book", warnings=[""]),
        ):
            with self.assertRaises(BookDocumentError):
                constructor()

    def test_direct_and_bulk_block_mutations_are_validated_atomically(self):
        book = BookDocument("Atomic")
        first = Paragraph(text="First")
        invalid = object()

        with self.assertRaises(BookDocumentError) as append_error:
            book.append(invalid)
        self.assertEqual(
            append_error.exception.code,
            BookDocumentErrorCode.UNSUPPORTED_BLOCK_KIND,
        )
        self.assertEqual(book.blocks, [])

        with self.assertRaises(BookDocumentError):
            book.extend([first, invalid])
        self.assertEqual(book.blocks, [])

    def test_constructor_detaches_caller_owned_collections(self):
        blocks = [Paragraph(text="First")]
        warnings = ["source warning"]
        book = BookDocument("Detached", blocks=blocks, warnings=warnings)

        blocks.append(Paragraph(text="External"))
        warnings.append("external warning")

        self.assertEqual([block.text for block in book.blocks], ["First"])
        self.assertEqual(book.warnings, ["source warning"])

    def test_mixed_type_unknown_keys_fail_with_stable_error_not_sort_type_error(self):
        with self.assertRaises(BookDocumentError) as caught:
            BookDocument.from_dict({"title": "Book", 7: "unknown"})
        self.assertEqual(caught.exception.code, BookDocumentErrorCode.UNKNOWN_FIELD)

        with self.assertRaises(BookDocumentError) as kind_error:
            BookDocument.from_dict(
                {"title": "Book", "blocks": [{"kind": [], "text": "bad"}]}
            )
        self.assertEqual(
            kind_error.exception.code,
            BookDocumentErrorCode.UNSUPPORTED_BLOCK_KIND,
        )


if __name__ == "__main__":
    unittest.main()
