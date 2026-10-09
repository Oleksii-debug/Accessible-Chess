from __future__ import annotations

from hashlib import sha256
import unittest

from acs.format_factory_conversion import FactoryConversionError, convert_factory_book_private
from acs.format_factory_policy import FactoryJobPolicy, FactorySelection


CHAPTER_BOOK = b"# First chapter\n\nFirst unique text.\n\n# Second chapter\n\nSecond unique text.\n"


def policy(source: bytes, *, scope: FactorySelection | None = None,
           formats: tuple[str, ...] = ("html",), **kwargs: object) -> FactoryJobPolicy:
    return FactoryJobPolicy(
        source_sha256=sha256(source).hexdigest(),
        source_id="chapter-book",
        selection=scope or FactorySelection("all"),
        output_formats=formats, output_language="en", **kwargs,
    )


class FactoryPrivateConversionTests(unittest.TestCase):
    def test_markdown_whole_book_html_uses_canonical_importer(self) -> None:
        p = policy(CHAPTER_BOOK)
        result = convert_factory_book_private(
            CHAPTER_BOOK, source_name="chapters.md", policy=p, source_language="en",
        )
        self.assertEqual(result.source_sha256, p.source_sha256)
        self.assertEqual(result.policy_sha256, p.digest())
        self.assertEqual(result.importer, "acs.book_text_import")
        self.assertGreaterEqual(result.selected_block_count, 2)
        self.assertIn(b"First unique text.", result.outputs[0].output_bytes)
        self.assertIn(b"Second unique text.", result.outputs[0].output_bytes)
        self.assertFalse(result.public_release_approved)
        self.assertFalse(result.outputs[0].public_release_approved)

    def test_chapter_scope_selects_only_requested_verified_content(self) -> None:
        selected = FactorySelection.from_text("chapters", "2")
        result = convert_factory_book_private(
            CHAPTER_BOOK, source_name="chapters.md", policy=policy(CHAPTER_BOOK, scope=selected),
            source_language="en", chapter_heading_level=1,
        )
        output = result.outputs[0].output_bytes
        self.assertIn(b"Second unique text.", output)
        self.assertNotIn(b"First unique text.", output)

    def test_chapter_level_requires_explicit_reader_selection(self) -> None:
        with self.assertRaises(FactoryConversionError):
            convert_factory_book_private(
                CHAPTER_BOOK, source_name="chapters.md",
                policy=policy(CHAPTER_BOOK, scope=FactorySelection.from_text("chapters", "1")),
                source_language="en",
            )

    def test_book_title_heading_must_not_be_guessed_as_chapter(self) -> None:
        source = b"# Book title\\n\\n## First chapter\\n\\nAlpha.\\n\\n## Second chapter\\n\\nBeta.\\n"
        chosen = FactorySelection.from_text("chapters", "2")
        result = convert_factory_book_private(
            source, source_name="edition.md",
            policy=policy(source, scope=chosen),
            source_language="en", chapter_heading_level=2,
        )
        output = result.outputs[0].output_bytes
        self.assertIn(b"Beta.", output)
        self.assertNotIn(b"Alpha.", output)

    def test_missing_chapter_fails_closed(self) -> None:
        with self.assertRaises(FactoryConversionError):
            convert_factory_book_private(
                CHAPTER_BOOK, source_name="chapters.md",
                policy=policy(CHAPTER_BOOK, scope=FactorySelection.from_text("chapters", "3")),
                source_language="en", chapter_heading_level=1,
            )

    def test_page_selection_has_no_fake_edition_mapping(self) -> None:
        with self.assertRaises(FactoryConversionError):
            convert_factory_book_private(
                CHAPTER_BOOK, source_name="chapters.md",
                policy=policy(CHAPTER_BOOK, scope=FactorySelection.from_text("printed_pages", "1-2")),
                source_language="en",
            )

    def test_source_drift_and_mismatched_language_refuse(self) -> None:
        with self.assertRaises(FactoryConversionError):
            convert_factory_book_private(
                CHAPTER_BOOK + b"CHANGED", source_name="chapters.md",
                policy=policy(CHAPTER_BOOK), source_language="en",
            )
        with self.assertRaises(FactoryConversionError):
            convert_factory_book_private(
                CHAPTER_BOOK, source_name="chapters.md",
                policy=policy(CHAPTER_BOOK), source_language="uk",
            )

    def test_unimplemented_formats_and_external_calls_refuse(self) -> None:
        for p in (policy(CHAPTER_BOOK, formats=("html", "epub3")),
                  policy(CHAPTER_BOOK, allowed_external_search=True),
                  policy(CHAPTER_BOOK, allowed_external_ai=True, provider_id="provider",
                         model_id="model", max_input_tokens=30, max_output_tokens=20)):
            with self.subTest(policy=p.digest()), self.assertRaises(FactoryConversionError):
                convert_factory_book_private(CHAPTER_BOOK, source_name="chapters.md",
                                             policy=p, source_language="en")

    def test_multi_output_requires_loss_review_before_any_result(self) -> None:
        p = policy(CHAPTER_BOOK, formats=("html", "txt"))
        with self.assertRaises(FactoryConversionError):
            convert_factory_book_private(CHAPTER_BOOK, source_name="chapters.md",
                                         policy=p, source_language="en")
        result = convert_factory_book_private(
            CHAPTER_BOOK, source_name="chapters.md", policy=p,
            source_language="en", allow_semantic_loss=True,
        )
        self.assertEqual([o.output_format for o in result.outputs], ["html", "txt"])
        self.assertIn("TEXT_STRUCTURE_NOT_MACHINE_NAVIGABLE", result.outputs[1].losses)
        self.assertEqual(result.outputs[0].losses, ())

    def test_private_html_source_prevents_script_injection(self) -> None:
        data = b"<html><body><h1>Study</h1><p>&lt;script&gt;bad&lt;/script&gt;</p></body></html>"
        result = convert_factory_book_private(data, source_name="study.html",
                                               policy=policy(data), source_language="en")
        value = result.outputs[0].output_bytes.decode()
        self.assertNotIn("<script>", value)
        self.assertIn("&lt;script&gt;", value)


if __name__ == "__main__":
    unittest.main()
