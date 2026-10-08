from __future__ import annotations

import unittest

import acs.book_html_import as html
from acs.import_contract import SourceReadCancelledError


class BookHtmlRuntimeCorrectnessTests(unittest.TestCase):
    def test_inline_style_comment_scan_observes_control_inside_one_comment(self):
        failure = SourceReadCancelledError(
            "cancelled during one large inline CSS comment"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            html._inline_style_without_comments(
                "/*" + ("x" * 20_000) + "*/display:none",
                cancel,
            )

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_css_whitespace_strip_observes_control(self):
        failure = SourceReadCancelledError(
            "cancelled during CSS whitespace normalization"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            html._controlled_css_strip((" " * 20_000) + "display", cancel)

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_display_tokenization_observes_control_inside_large_token(self):
        failure = SourceReadCancelledError(
            "cancelled during CSS display tokenization"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            html._deterministic_display_value("x" * 20_000, cancel)

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_inline_style_comment_and_important_semantics_are_preserved(self):
        self.assertTrue(
            html._inline_style_hides(
                "display:block;/* retained boundary */display:none ! important"
            )
        )
        self.assertTrue(
            html._inline_style_hides(
                "display:none!important;display:block"
            )
        )
        self.assertFalse(
            html._inline_style_hides(
                "display:none!important;display:block!important"
            )
        )
        self.assertTrue(
            html._inline_style_hides("content-visibility:hidden")
        )

    def test_inline_style_hidden_subtree_stays_off_accessible_surface(self):
        imported = html.import_html_book(
            '<html><body><section style="display: none ! important">'
            '<p>Secret</p></section><p>Visible</p></body></html>',
            source_name="style-hidden.html",
        )

        readable = "\n".join(
            getattr(block, "text", "")
            for block in imported.document.blocks
        )
        self.assertNotIn("Secret", readable)
        self.assertIn("Visible", readable)

    def test_capture_source_anchor_uses_canonical_capture_attrs(self):
        imported = html.import_html_book(
            '<html><body><p id="p1">Readable</p></body></html>',
            source_name="capture-anchor.html",
        )

        self.assertEqual(len(imported.document.blocks), 1)
        self.assertEqual(imported.document.blocks[0].source_anchor, "p1")

    def test_rich_list_fallback_uses_list_attrs_without_runtime_hook(self):
        imported = html.import_html_book(
            '<html><body><ul id="list"><li>First</li>'
            '<li id="rich">Before <img alt="Diagram note"> After</li>'
            '</ul></body></html>',
            source_name="rich-list.html",
        )

        self.assertGreaterEqual(len(imported.document.blocks), 3)
        self.assertTrue(
            any(
                getattr(block, "source_anchor", None) == "list"
                for block in imported.document.blocks
            )
        )

    def test_pgn_candidate_scan_uses_each_candidate_line(self):
        candidates = html._pgn_candidates(
            '{PGN 1}\n[Event "Study"]\n[Result "*"]\n\n1. e4 *\n'
            'End of PGN Supplement\nAfter'
        )

        self.assertEqual(len(candidates), 1)
        self.assertIn('[Event "Study"]', candidates[0].text)
        self.assertNotIn("After", candidates[0].text)

    def test_aria_hidden_true_is_excluded_from_accessible_document(self):
        imported = html.import_html_book(
            '<html><body><section aria-hidden=" true ">'
            '<p>Secret text</p></section><p>Visible text</p></body></html>',
            source_name="aria-hidden.html",
        )

        readable = "\n".join(
            getattr(block, "text", "")
            for block in imported.document.blocks
        )
        self.assertNotIn("Secret text", readable)
        self.assertIn("Visible text", readable)


if __name__ == "__main__":
    unittest.main()
