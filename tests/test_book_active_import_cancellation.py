from io import BytesIO
import tempfile
import threading
import zipfile
import unittest
from pathlib import Path
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.chesscore import Board
from acs.book_html_import import import_html_book, _ListCapture, _SemanticHtmlParser
from acs.book_epub_import import import_epub_book
from acs.book_text_import import import_text_book, BookTextFormat
from acs.import_contract import SourceReadCancelledError
from acs.library_import_service import LibraryImportService
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind, Version2ImportWorkerServices, Version2WindowsFileActionDelegate,
)
from test_v2_book_epub_import import _epub, _opf, _simple_epub


HTML = ('<html lang="uk"><head><title>Книга</title></head><body>'
        '<p id="prose">' + 'текст ' * 6000 + '&amp; кінець</p>'
        '<ul><li>Перший</li><li>Другий</li></ul>'
        f'<div id="position" data-acs-fen="{Board.START}"></div>'
        '<pre id="games">{PGN 1}\n[Event "Урок"]\n[Result "*"]\n\n'
        '1. e4 {Коментар} (1. d4 d5 (1... Nf6)) e5 *\n\n'
        '[Event "Другий"]\n[Result "*"]\n\n1. Nf3 *</pre>'
        '<p>Після партій</p></body></html>')


class BookActiveImportCancellationTests(unittest.TestCase):
    def test_chunk_boundaries_preserve_entities_comments_and_semantic_markers(self):
        fragments = ('&amp; текст', '<!-- hidden -->текст',
                     f'<img id="diagram" src="board.png" data-acs-fen="{Board.START}">',
                     '<pre>{PGN 1}\n[Event "Study"]\n[Result "*"]\n\n1. e4 *</pre>')
        for fragment in fragments:
            for split in (1, 3, len(fragment) // 2):
                with self.subTest(fragment=fragment[:15], split=split):
                    prefix = '<html><body><p>'
                    text = prefix + 'a' * (16_384 - len(prefix) - split) + fragment + '</p><p>After</p></body></html>'
                    plain = import_html_book(text, source_name='boundary.html')
                    controlled = import_html_book(text, source_name='boundary.html', control_checkpoint=lambda: None)
                    self.assertEqual(plain.document.as_dict(), controlled.document.as_dict())
                    self.assertEqual(plain.warnings, controlled.warnings)

    def test_chunked_html_preserves_full_semantic_document_and_identity(self):
        calls = []
        original = import_html_book(HTML, source_name='study.html')
        controlled = import_html_book(HTML, source_name='study.html', control_checkpoint=lambda: calls.append(1))
        self.assertGreater(len(calls), 6)
        self.assertEqual(original.document.as_dict(), controlled.document.as_dict())
        self.assertEqual(original.book_key, controlled.book_key)
        self.assertEqual(original.warnings, controlled.warnings)
        self.assertEqual(controlled.pgn_games, 2)

    def test_epub_central_directory_validation_observes_control(self):
        import acs.book_epub_import as epub

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
            for index in range(300):
                archive.writestr(f'entry-{index:03}.txt', b'x')

        failure = SourceReadCancelledError('cancelled during EPUB central directory validation')
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._validate_single_disk_zip_end_records(buffer.getvalue(), cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_epub_archive_index_observes_control_inside_large_package_scan(self):
        import acs.book_epub_import as epub

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
            for index in range(300):
                archive.writestr(f'entry-{index:03}.txt', b'x')

        failure = SourceReadCancelledError('cancelled during EPUB package scan')
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        with zipfile.ZipFile(BytesIO(buffer.getvalue()), 'r') as archive:
            with self.assertRaises(SourceReadCancelledError) as caught:
                epub._archive_index(archive, cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_epub_safe_name_segment_scan_observes_control(self):
        import acs.book_epub_import as epub

        failure = SourceReadCancelledError('cancelled during EPUB OCF path scan')
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        name = '/'.join(f'p{index}' for index in range(300))
        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._safe_entry_name(name, cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_epub_local_zip64_extra_scan_observes_control(self):
        import acs.book_epub_import as epub

        failure = SourceReadCancelledError('cancelled during EPUB ZIP extra scan')
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        extra = b'\x02\x00\x00\x00' * 300
        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._local_zip64_sizes(
                extra,
                needs_uncompressed=False,
                needs_compressed=False,
                control_checkpoint=cancel,
            )
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_epub_entry_decompression_observes_control_before_full_payload_read(self):
        import acs.book_epub_import as epub

        buffer = BytesIO()
        payload = b'x' * (512 * 1024)
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('large.bin', payload)

        failure = SourceReadCancelledError('cancelled during EPUB entry decompression')
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        with zipfile.ZipFile(BytesIO(buffer.getvalue()), 'r') as archive:
            index = {'large.bin': archive.getinfo('large.bin')}
            with self.assertRaises(SourceReadCancelledError) as caught:
                epub._read_entry(
                    archive, index, 'large.bin', control_checkpoint=cancel
                )
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_epub_xml_structure_scan_observes_control_before_tree_materialization(self):
        import acs.book_epub_import as epub

        data = ('<root>' + '<item />' * 500 + '</root>').encode('utf-8')
        failure = SourceReadCancelledError('cancelled during EPUB XML scan')
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        with patch.object(epub.ET, 'fromstring') as materialize:
            with self.assertRaises(SourceReadCancelledError) as caught:
                epub._xml_root(data, 'test metadata', cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)
        materialize.assert_not_called()

    def test_epub_xml_tree_materialization_observes_control_between_chunks(self):
        import acs.book_epub_import as epub

        data = ("<root>" + ("x" * (192 * 1024)) + "</root>").encode("utf-8")
        failure = SourceReadCancelledError(
            "cancelled during EPUB XML tree materialization"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._materialize_xml_root(data, "test metadata", cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_epub_package_metadata_validation_observes_control_before_id_walk(self):
        import acs.book_epub_import as epub

        metadata = '''
    <dc:identifier id="bookid">urn:uuid:test-fixture</dc:identifier>
    <dc:title>Cancelable package</dc:title>
    <dc:language>uk</dc:language>
''' + '\n'.join(
            f'    <ext:note xmlns:ext="urn:test:ext" id="foreign-{index}">x</ext:note>'
            for index in range(300)
        )
        package = epub.ET.fromstring(
            _opf(
                manifest='    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>',
                spine='    <itemref idref="c1"/>',
                metadata=metadata,
            )
        )
        failure = SourceReadCancelledError('cancelled during EPUB package metadata validation')
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 6:
                raise failure

        with patch.object(epub, '_validate_package_ids_unique') as id_walk:
            with self.assertRaises(SourceReadCancelledError) as caught:
                epub._validate_package_document(package, cancel)
        self.assertIs(caught.exception, failure)
        id_walk.assert_not_called()

    def test_epub_manifest_scan_observes_control_before_full_metadata_walk(self):
        import acs.book_epub_import as epub

        manifest = '\n'.join(
            f'    <item id="i{index}" href="Text/{index}.xhtml" media-type="application/xhtml+xml"/>'
            for index in range(300)
        )
        package = epub.ET.fromstring(
            _opf(manifest=manifest, spine='    <itemref idref="i0"/>')
        )
        failure = SourceReadCancelledError('cancelled during EPUB manifest scan')
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._manifest_items(package, 'OEBPS', cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_epub_spine_scan_observes_control_before_full_reading_order_walk(self):
        import acs.book_epub_import as epub

        manifest_text = '\n'.join(
            f'    <item id="i{index}" href="Text/{index}.xhtml" media-type="application/xhtml+xml"/>'
            for index in range(300)
        )
        spine_text = '\n'.join(
            f'    <itemref idref="i{index}"/>' for index in range(300)
        )
        package = epub.ET.fromstring(
            _opf(manifest=manifest_text, spine=spine_text)
        )
        manifest = epub._manifest_items(package, 'OEBPS')
        failure = SourceReadCancelledError('cancelled during EPUB spine scan')
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._spine_ids(package, epub._Warnings(), manifest, cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_epub_nested_html_control_preserves_order_and_closes_archive_on_cancel(self):
        raw = _simple_epub(HTML.encode('utf-8'))
        plain = import_epub_book(raw, source_name='study.epub')
        controlled = import_epub_book(raw, source_name='study.epub', control_checkpoint=lambda: None)
        self.assertEqual(plain.document.as_dict(), controlled.document.as_dict())
        import acs.book_epub_import as epub
        archives = []
        constructor = epub.zipfile.ZipFile
        def capture(*args, **kwargs):
            archive = constructor(*args, **kwargs)
            archives.append(archive)
            return archive
        calls = 0
        failure = SourceReadCancelledError('cancelled')
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 7:
                raise failure
        with patch.object(epub.zipfile, 'ZipFile', side_effect=capture):
            with self.assertRaises(SourceReadCancelledError) as caught:
                import_epub_book(raw, source_name='study.epub', control_checkpoint=cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(len(archives), 1)
        self.assertIsNone(archives[0].fp)

    def test_markdown_and_txt_control_preserve_semantics(self):
        for fmt, text in ((BookTextFormat.MARKDOWN, '# Урок\n\n' + '- пункт\n' * 400 + '\n```pgn\n1. e4 *\n```'),
                          (BookTextFormat.TXT, 'Рядок\n' * 400)):
            with self.subTest(fmt=fmt):
                args = dict(source_name='study', source_format=fmt)
                plain = import_text_book(text, **args)
                calls = []
                controlled = import_text_book(text, **args, control_checkpoint=lambda: calls.append(1))
                self.assertGreater(len(calls), 3)
                self.assertEqual(plain.document.as_dict(), controlled.document.as_dict())
                self.assertEqual(plain.book_key, controlled.book_key)

    def test_markdown_large_fence_observes_control_before_pgn_parse(self):
        failure = SourceReadCancelledError('cancelled')
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 4:
                raise failure
        with patch('acs.book_text_import.parse_pgn_text') as parse:
            with self.assertRaises(SourceReadCancelledError) as caught:
                import_text_book('```pgn\n' + '{comment}\n' * 1000 + '1. e4 *\n```',
                                 source_name='study.md', source_format=BookTextFormat.MARKDOWN,
                                 control_checkpoint=cancel)
        self.assertIs(caught.exception, failure)
        parse.assert_not_called()

    def test_html_explicit_pgn_preamble_scan_observes_control(self):
        import acs.book_html_import as html

        failure = SourceReadCancelledError("cancelled during explicit PGN preamble scan")
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        raw = "{PGN 1}\n" + ("   \n" * 400) + '[Event "Study"]\n'
        with self.assertRaises(SourceReadCancelledError) as caught:
            html._explicit_pgn_pre(raw, cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_html_pgn_blank_region_scan_observes_control(self):
        import acs.book_html_import as html

        failure = SourceReadCancelledError("cancelled during PGN blank-region scan")
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 4:
                raise failure

        visible = "{PGN 1}\n" + ("\n" * 400) + '[Event "Study"]\n'
        with self.assertRaises(SourceReadCancelledError) as caught:
            html._pgn_candidates(visible, cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 4)

    def test_html_list_aggregation_observes_control(self):
        failure = SourceReadCancelledError('cancelled during HTML list aggregation')
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        parser = _SemanticHtmlParser(
            available_assets=None,
            control_checkpoint=cancel,
        )
        captured = _ListCapture(
            tag='ul',
            attrs={},
            items=[f'item {index}' for index in range(300)],
            identity_items=[f'item {index}' for index in range(300)],
        )
        with self.assertRaises(SourceReadCancelledError) as caught:
            parser._emit_list(captured)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_html_visible_pgn_scan_observes_control_across_large_prose(self):
        import acs.book_html_import as html

        failure = SourceReadCancelledError('cancelled during visible PGN scan')
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        visible = ('x' * 16_383 + '\r\n') * 4
        with self.assertRaises(SourceReadCancelledError) as caught:
            html._pgn_candidates(visible, cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_html_parser_events_observe_control_inside_single_feed_chunk(self):
        failure = SourceReadCancelledError('cancelled inside HTMLParser.feed')
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        parser = _SemanticHtmlParser(
            available_assets=None,
            control_checkpoint=cancel,
        )
        source = '<p>' * 400 + 'unreached'
        with self.assertRaises(SourceReadCancelledError) as caught:
            parser.feed(source)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)
        self.assertLess(parser._node_count, 400)

    def test_html_inline_style_scan_observes_control_inside_one_starttag(self):
        failure = SourceReadCancelledError("cancelled during HTML inline style scan")
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        parser = _SemanticHtmlParser(
            available_assets=None,
            control_checkpoint=cancel,
        )
        with self.assertRaises(SourceReadCancelledError) as caught:
            parser.handle_starttag("div", [("style", "x" * 10_000)])
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)
        self.assertEqual(parser.blocks, [])

    def test_html_starttag_attribute_normalization_observes_control(self):
        failure = SourceReadCancelledError("cancelled during HTML attribute normalization")
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        parser = _SemanticHtmlParser(
            available_assets=None,
            control_checkpoint=cancel,
        )
        attrs = [(f"data-test-{index}", "x") for index in range(400)]
        with self.assertRaises(SourceReadCancelledError) as caught:
            parser.handle_starttag("div", attrs)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)
        self.assertEqual(parser.blocks, [])

    def test_html_data_fanout_observes_control_inside_deep_capture_stack(self):
        parser = _SemanticHtmlParser(available_assets=None)
        parser.feed('<p>' * 400)
        failure = SourceReadCancelledError('cancelled during HTML capture fanout')
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        parser.control_checkpoint = cancel
        parser._control_event_count = 0
        with self.assertRaises(SourceReadCancelledError) as caught:
            parser.feed('payload')
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)
        self.assertEqual(parser.visible_chars, 0)

    def test_html_inline_projection_observes_control_with_many_semantic_events(self):
        parser = _SemanticHtmlParser(available_assets=None)
        parser.feed('<p>' + '<img alt="diagram">' * 300)
        failure = SourceReadCancelledError('cancelled during inline semantic projection')
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        parser.control_checkpoint = cancel
        parser._control_event_count = 0
        with self.assertRaises(SourceReadCancelledError) as caught:
            parser.handle_endtag('p')
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_html_endtag_deep_capture_search_observes_control_before_mutation(self):
        parser = _SemanticHtmlParser(available_assets=None)
        parser.feed("<p>" * 400)
        failure = SourceReadCancelledError("cancelled during deep HTML end-tag search")
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        parser.control_checkpoint = cancel
        parser._control_event_count = 0
        with self.assertRaises(SourceReadCancelledError) as caught:
            parser.handle_endtag("div")
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)
        self.assertEqual(len(parser._captures), 400)

    def test_html_css_ascii_lower_control_preserves_non_ascii_semantics(self):
        import acs.book_html_import as html

        sample = ("DISPLAY" * 1_000) + " ÄÖÜ Σ"
        calls = []
        controlled = html._css_ascii_lower(sample, lambda: calls.append(1))
        self.assertEqual(controlled, html._css_ascii_lower(sample))
        self.assertIn("ä", controlled.lower())
        self.assertTrue(controlled.endswith(" ÄÖÜ Σ"))
        self.assertGreater(len(calls), 2)

    def test_html_css_ascii_lower_observes_control_inside_large_token(self):
        import acs.book_html_import as html

        failure = SourceReadCancelledError("cancelled during CSS ASCII folding")
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            html._css_ascii_lower("DISPLAY" * 2_000, cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_html_asset_path_scan_observes_control_inside_large_segment_set(self):
        import acs.book_html_import as html

        failure = SourceReadCancelledError("cancelled during HTML asset path scan")
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 5:
                raise failure

        value = "/".join(f"segment{index}" for index in range(400))
        with self.assertRaises(SourceReadCancelledError) as caught:
            html._asset_name(value, cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 5)

    def test_html_controlled_compaction_matches_uncontrolled_whitespace_semantics(self):
        import acs.book_html_import as html

        sample = (
            "  Alpha\tBeta\nGamma\xa0Delta\u2003Epsilon  "
            + ("word\t" * 2_000)
            + "tail"
        )
        calls = []
        controlled = html._compact(sample, lambda: calls.append(1))
        self.assertEqual(controlled, html._compact(sample))
        self.assertGreater(len(calls), 2)

    def test_html_large_capture_compaction_observes_control_before_block_publication(self):
        parser = _SemanticHtmlParser(available_assets=None)
        parser.feed("<p>" + ("Alpha\tBeta " * 2_000))
        capture = parser._captures[-1]
        failure = SourceReadCancelledError("cancelled during HTML text compaction")
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        parser.control_checkpoint = cancel
        with self.assertRaises(SourceReadCancelledError) as caught:
            parser._finish_capture(capture)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)
        self.assertEqual(parser.blocks, [])

    def test_html_body_implicit_head_unwind_observes_control_before_capture_mutation(self):
        parser = _SemanticHtmlParser(available_assets=None)
        parser.feed("<head>" + "<title>" * 300)
        before = tuple(parser._captures)
        failure = SourceReadCancelledError("cancelled before implicit HEAD unwind")
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise failure

        parser.control_checkpoint = cancel
        parser._control_event_count = 1
        with self.assertRaises(SourceReadCancelledError) as caught:
            parser.handle_starttag("body", [])
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 1)
        self.assertEqual(tuple(parser._captures), before)

    def test_html_ancestor_unwind_observes_control_before_capture_mutation(self):
        parser = _SemanticHtmlParser(available_assets=None)
        parser.feed("<p>" + "<blockquote>" * 300)
        before = tuple(parser._captures)
        failure = SourceReadCancelledError("cancelled before malformed ancestor unwind")
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        parser.control_checkpoint = cancel
        parser._control_event_count = 1
        with self.assertRaises(SourceReadCancelledError) as caught:
            parser.handle_endtag("p")
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)
        self.assertEqual(tuple(parser._captures), before)

    def test_html_list_close_unwind_observes_control_before_capture_mutation(self):
        parser = _SemanticHtmlParser(available_assets=None)
        parser.feed("<ul><li>" + "<blockquote>" * 300)
        before_captures = tuple(parser._captures)
        before_lists = tuple(parser._lists)
        failure = SourceReadCancelledError("cancelled before malformed list unwind")
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 5:
                raise failure

        parser.control_checkpoint = cancel
        parser._control_event_count = 1
        with self.assertRaises(SourceReadCancelledError) as caught:
            parser.handle_endtag("ul")
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)
        self.assertEqual(tuple(parser._captures), before_captures)
        self.assertEqual(tuple(parser._lists), before_lists)

    def test_html_large_list_fallback_observes_control_before_publication(self):
        import acs.book_html_import as html

        failure = SourceReadCancelledError("cancelled during HTML list fallback")
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        parser = _SemanticHtmlParser(
            available_assets=None,
            control_checkpoint=cancel,
        )
        captured = html._ListCapture(
            tag="ol",
            attrs={},
            items=[f"item {index}" for index in range(400)],
            unsupported=True,
            structural_unsupported=True,
        )
        with self.assertRaises(SourceReadCancelledError) as caught:
            parser._emit_list(captured)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)
        self.assertEqual(parser.blocks, [])

    def test_html_close_recovery_control_failure_preserves_exact_exception(self):
        failure = SourceReadCancelledError('cancelled during malformed HTML recovery')
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 4:
                raise failure

        malformed = '<p>' * 300 + 'unfinished'
        with self.assertRaises(SourceReadCancelledError) as caught:
            import_html_book(
                malformed,
                source_name='unfinished.html',
                control_checkpoint=cancel,
            )
        self.assertIs(caught.exception, failure)

    def test_canonical_pgn_serializer_validation_observes_control_inside_large_warning_collection(self):
        import acs.gametree as gametree
        from acs.gametree import PgnGame, VariationLine

        failure = SourceReadCancelledError('cancelled during canonical PGN warning validation')
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        game = PgnGame(
            line=VariationLine(result='*'),
            warnings=[f'warning {index}' for index in range(300)],
        )
        with self.assertRaises(SourceReadCancelledError) as caught:
            gametree._validate_game_for_serialization(
                game,
                control_checkpoint=cancel,
            )
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_canonical_pgn_serializer_observes_control_inside_large_nag_projection(self):
        import acs.gametree as gametree
        from acs.gametree import MoveNode, VariationLine

        failure = SourceReadCancelledError('cancelled during canonical PGN NAG projection')
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 5:
                raise failure

        line = VariationLine(
            moves=[MoveNode('e4', move_number='1.', nags=['$1'] * 300)],
            result='*',
        )
        with self.assertRaises(SourceReadCancelledError) as caught:
            gametree._serialize_line(line, control_checkpoint=cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 5)

    def test_canonical_pgn_serializer_observes_control_while_snapshotting_large_tags(self):
        from acs.gametree import PgnGame, VariationLine, serialize_game

        failure = SourceReadCancelledError('cancelled while snapshotting canonical PGN tags')
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 9:
                raise failure

        game = PgnGame(
            tags={f'Tag{index}': 'value' for index in range(300)},
            line=VariationLine(result='*'),
        )
        with self.assertRaises(SourceReadCancelledError) as caught:
            serialize_game(game, control_checkpoint=cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 9)

    def test_canonical_pgn_serializer_observes_control_inside_large_comment_collection(self):
        import acs.gametree as gametree
        from acs.gametree import Comment, VariationLine

        failure = SourceReadCancelledError('cancelled during canonical PGN serialization')
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        line = VariationLine(
            leading_comments=[Comment(f'note {index}', 'brace') for index in range(300)]
        )
        with self.assertRaises(SourceReadCancelledError) as caught:
            gametree._serialize_line(line, control_checkpoint=cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_canonical_pgn_control_requires_callable_parse_and_serialize_hooks(self):
        from acs.gametree import serialize_game
        from acs.pgn_roundtrip import parse_pgn_text

        source = '[Event "Study"]\n[Result "*"]\n\n*\n'
        with self.assertRaises(TypeError):
            parse_pgn_text(source, strict=False, control_checkpoint=True)
        game = parse_pgn_text(source, strict=False)[0]
        with self.assertRaises(TypeError):
            serialize_game(game, control_checkpoint=True)

    def test_canonical_pgn_serializer_control_preserves_exact_output(self):
        from acs.gametree import serialize_game
        from acs.pgn_roundtrip import parse_pgn_text

        game = parse_pgn_text(
            '[Event "Study"]\n[Result "*"]\n\n1. e4 {note} (1. d4 d5) e5 *\n',
            strict=False,
        )[0]
        plain = serialize_game(game)
        calls = []
        controlled = serialize_game(game, control_checkpoint=lambda: calls.append(1))
        self.assertEqual(controlled, plain)
        self.assertGreater(len(calls), 3)

    def test_html_pgn_collection_threads_control_into_canonical_serializer(self):
        import acs.gametree as gametree

        failure = ValueError('trusted cancellation-shaped serializer failure')
        armed = False
        calls = 0
        real_serialize = gametree.serialize_game

        def control():
            nonlocal calls
            calls += 1
            if armed:
                raise failure

        def controlled_serialize(game, *args, **kwargs):
            nonlocal armed
            forwarded_control = kwargs.get('control_checkpoint')
            self.assertTrue(callable(forwarded_control))
            armed = True
            return real_serialize(game, *args, **kwargs)

        with patch('acs.book_html_import.serialize_game', side_effect=controlled_serialize):
            with self.assertRaises(ValueError) as caught:
                import_html_book(
                    HTML,
                    source_name='study.html',
                    control_checkpoint=control,
                )
        self.assertIs(caught.exception, failure)
        self.assertTrue(armed)
        self.assertGreater(calls, 1)

    def test_canonical_pgn_normalization_observes_control_inside_large_comment_collection(self):
        import acs.pgn_roundtrip as roundtrip
        from acs.gametree import Comment, VariationLine

        failure = SourceReadCancelledError('cancelled during canonical PGN normalization')
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        line = VariationLine(
            leading_comments=[Comment(f'note {index}', 'brace') for index in range(300)]
        )
        with self.assertRaises(SourceReadCancelledError) as caught:
            roundtrip._normalize_and_validate_line(
                line,
                control_checkpoint=cancel,
            )
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_canonical_pgn_control_preserves_recovery_semantics(self):
        from acs.pgn_roundtrip import parse_pgn_text

        source = '[Event "Study"]\n[Result "*"]\n\n1. e4 {note} (1. d4 d5) e5 *\n'
        plain = parse_pgn_text(source, strict=False)
        calls = []
        controlled = parse_pgn_text(
            source,
            strict=False,
            control_checkpoint=lambda: calls.append(1),
        )
        self.assertEqual(controlled, plain)
        self.assertGreater(len(calls), 3)

    def test_canonical_pgn_large_brace_scan_preserves_exact_cancel(self):
        from acs.pgn_roundtrip import parse_pgn_text

        failure = SourceReadCancelledError('cancelled inside canonical PGN scan')
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 8:
                raise failure

        source = '[Event "Study"]\n[Result "*"]\n\n1. e4 {' + ('x' * 20_000) + '} *\n'
        with self.assertRaises(SourceReadCancelledError) as caught:
            parse_pgn_text(
                source,
                strict=False,
                control_checkpoint=cancel,
            )
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 8)

    def test_canonical_pgn_preserves_control_failure_even_if_it_is_gametree_error(self):
        import acs.pgn_roundtrip as roundtrip
        from acs.gametree import GameTreeContractError, GameTreeErrorCode

        failure = GameTreeContractError(
            'trusted control failure shaped like parser failure',
            code=GameTreeErrorCode.INVALID_MODEL,
        )
        armed = False

        def control():
            if armed:
                raise failure

        def controlled_parse_games(text, control_checkpoint=None):
            nonlocal armed
            armed = True
            self.assertIsNotNone(control_checkpoint)
            control_checkpoint()
            return []

        with patch('acs.pgn_roundtrip.parse_games', side_effect=controlled_parse_games):
            with self.assertRaises(GameTreeContractError) as caught:
                roundtrip.parse_pgn_text(
                    '[Event "Study"]\n[Result "*"]\n\n*\n',
                    strict=False,
                    control_checkpoint=control,
                )
        self.assertIs(caught.exception, failure)
        self.assertTrue(armed)

    def test_html_embedded_pgn_threads_control_into_canonical_authority(self):
        import acs.pgn_roundtrip as roundtrip

        failure = ValueError('trusted cancellation-shaped ValueError from canonical PGN authority')
        armed = False
        calls = 0

        def control():
            nonlocal calls
            calls += 1
            if armed:
                raise failure

        real_parse = roundtrip.parse_pgn_text

        def controlled_parse(*args, **kwargs):
            nonlocal armed
            forwarded_control = kwargs.get('control_checkpoint')
            self.assertTrue(callable(forwarded_control))
            self.assertIsNot(forwarded_control, control)
            armed = True
            return real_parse(*args, **kwargs)

        with patch('acs.book_html_import.parse_pgn_text', side_effect=controlled_parse):
            with self.assertRaises(ValueError) as caught:
                import_html_book(
                    HTML,
                    source_name='study.html',
                    control_checkpoint=control,
                )
        self.assertIs(caught.exception, failure)
        self.assertTrue(armed)
        self.assertGreater(calls, 1)

    def test_html_control_failure_is_not_translated_into_malformed_source(self):
        failure = RuntimeError('trusted control failure')
        calls = 0
        def fail():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure
        with self.assertRaises(RuntimeError) as caught:
            import_html_book(HTML, source_name='study.html', control_checkpoint=fail)
        self.assertIs(caught.exception, failure)

    def test_html_available_asset_normalization_observes_control(self):
        import acs.book_html_import as html

        failure = SourceReadCancelledError("cancelled during asset normalization")
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        assets = [f"images/{index}.png" for index in range(400)]
        with self.assertRaises(SourceReadCancelledError) as caught:
            html._asset_set(assets, cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_non_callable_control_is_rejected(self):
        for importer, source, args in ((import_html_book, HTML, {}),
                                       (import_epub_book, b'not a package', {}),
                                       (import_text_book, 'text', {'source_format': 'txt'})):
            with self.subTest(importer=importer):
                with self.assertRaises(TypeError):
                    importer(source, source_name='study', control_checkpoint=True, **args)

    def test_native_cancel_interrupts_large_epub_package_scan_before_library_staging(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / 'study.epub'
        chapter = b'<html><body><p>Readable chapter</p></body></html>'
        raw = _epub(
            opf=_opf(
                manifest='    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>',
                spine='    <itemref idref="c1"/>',
            ),
            entries={'OEBPS/Text/ch1.xhtml': chapter},
            prepend=[(f'Extras/{index:03}.bin', b'x') for index in range(300)],
        )
        source.write_bytes(raw)
        original = source.read_bytes()
        database = AcsDatabase(root / 'library.acsdb')
        self.addCleanup(database.close)
        ready, release, closed = threading.Event(), threading.Event(), threading.Event()
        events = []

        class Dialogs:
            def open_pgn(self): return None
            def save_pgn_as(self, *args): return None
            def select_library_import(self): return source

        def services():
            worker_database = AcsDatabase(root / 'library.acsdb')
            def close():
                worker_database.close()
                closed.set()
            return Version2ImportWorkerServices(
                LibraryImportService(worker_database), None, close
            )

        delegate = Version2WindowsFileActionDelegate(
            dialogs=Dialogs(), get_pgn_session=lambda: None, set_pgn_session=lambda _: None,
            import_services_factory=services, event_sink=events.append, next_delegate=lambda *_: None,
        )
        import acs.book_epub_import as epub
        validate = epub._validate_local_zip_header
        calls = 0
        def pause(archive, info, control_checkpoint=None):
            nonlocal calls
            result = validate(archive, info, control_checkpoint)
            calls += 1
            if calls == 100:
                ready.set()
                if not release.wait(5):
                    raise RuntimeError('test EPUB scan release timed out')
            return result

        with patch.object(epub, '_validate_local_zip_header', pause):
            try:
                delegate('library.import', {})
                self.assertTrue(ready.wait(5))
                delegate('library.cancel_import', {})
            finally:
                release.set()
                self.assertTrue(delegate.wait_for_import(5))

        self.assertTrue(closed.is_set())
        self.assertEqual(
            1,
            sum(event.kind is FileWorkflowEventKind.IMPORT_CANCELLED for event in events),
        )
        self.assertFalse(
            any(
                event.kind in {FileWorkflowEventKind.FAILED, FileWorkflowEventKind.IMPORT_COMPLETED}
                for event in events
            )
        )
        self.assertEqual(source.read_bytes(), original)
        for table in ('sources', 'games', 'import_attempts'):
            self.assertEqual(
                database.conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0],
                0,
            )

    def test_native_cancel_interrupts_actual_html_parser_before_any_library_staging(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        with self.subTest(format='HTML'):
            root = Path(temporary.name)
            source = root / 'study.html'
            source.write_text(HTML, encoding='utf-8')
            original = source.read_bytes()
            database = AcsDatabase(root / 'library.acsdb')
            self.addCleanup(database.close)
            ready, release, closed = threading.Event(), threading.Event(), threading.Event()
            events = []
            class Dialogs:
                def open_pgn(self): return None
                def save_pgn_as(self, *args): return None
                def select_library_import(self): return source
            def services():
                worker_database = AcsDatabase(root / 'library.acsdb')
                def close():
                    worker_database.close()
                    closed.set()
                return Version2ImportWorkerServices(LibraryImportService(worker_database), None, close)
            delegate = Version2WindowsFileActionDelegate(
                dialogs=Dialogs(), get_pgn_session=lambda: None, set_pgn_session=lambda _: None,
                import_services_factory=services, event_sink=events.append, next_delegate=lambda *_: None,
            )
            feed = _SemanticHtmlParser.feed
            def pause(parser, text):
                feed(parser, text)
                if not ready.is_set():
                    ready.set()
                    if not release.wait(5):
                        raise RuntimeError('test parser release timed out')
            with patch.object(_SemanticHtmlParser, 'feed', pause):
                try:
                    delegate('library.import', {})
                    self.assertTrue(ready.wait(5))
                    delegate('library.cancel_import', {})
                finally:
                    release.set()
                    self.assertTrue(delegate.wait_for_import(5))
            self.assertTrue(closed.is_set())
            self.assertEqual(1, sum(event.kind is FileWorkflowEventKind.IMPORT_CANCELLED for event in events))
            self.assertFalse(any(event.kind in {FileWorkflowEventKind.FAILED, FileWorkflowEventKind.IMPORT_COMPLETED} for event in events))
            self.assertEqual(source.read_bytes(), original)
            for table in ('sources', 'games', 'import_attempts'):
                self.assertEqual(database.conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
