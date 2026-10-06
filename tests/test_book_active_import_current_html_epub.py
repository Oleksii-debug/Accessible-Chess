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

    def test_epub_exact_identifier_scan_observes_control_inside_one_attribute(self):
        import acs.book_epub_import as epub

        failure = SourceReadCancelledError(
            "cancelled during one long EPUB identifier"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._is_exact_identifier("identifier" * 3_000, cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_epub_media_type_scan_observes_control_inside_one_attribute(self):
        import acs.book_epub_import as epub

        failure = SourceReadCancelledError(
            "cancelled during one long EPUB media type"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 4:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._normalized_media_type(
                "application/" + ("x" * 20_000),
                context="test manifest item",
                control_checkpoint=cancel,
            )
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 4)

    def test_epub_href_scan_observes_control_inside_one_attribute(self):
        import acs.book_epub_import as epub

        failure = SourceReadCancelledError(
            "cancelled during one long EPUB href"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._resolve_package_href(
                "",
                "Text/" + ("segment" * 4_000) + ".xhtml",
                control_checkpoint=cancel,
            )
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_epub_rel_scan_observes_control_inside_one_attribute(self):
        import acs.book_epub_import as epub

        failure = SourceReadCancelledError(
            "cancelled during one long EPUB rel attribute"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._is_space_separated_tokens("alternate" * 3_000, cancel)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_epub_resolved_asset_threads_control_into_one_long_reference(self):
        import acs.book_epub_import as epub

        failure = SourceReadCancelledError(
            "cancelled during one long EPUB image reference"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 4:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._resolved_asset(
                "OEBPS/Text/chapter.xhtml",
                "images/" + ("asset" * 5_000) + ".png",
                cancel,
            )
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 4)

    def test_epub_single_token_control_preserves_metadata_semantics(self):
        import acs.book_epub_import as epub

        calls = []
        checkpoint = lambda: calls.append(1)
        self.assertEqual(
            epub._is_exact_identifier("chapter-01"),
            epub._is_exact_identifier("chapter-01", checkpoint),
        )
        self.assertEqual(
            epub._normalized_media_type(
                "application/xhtml+xml",
                context="test",
            ),
            epub._normalized_media_type(
                "application/xhtml+xml",
                context="test",
                control_checkpoint=checkpoint,
            ),
        )
        self.assertEqual(
            epub._resolve_package_href("OEBPS", "Text/chapter.xhtml"),
            epub._resolve_package_href(
                "OEBPS",
                "Text/chapter.xhtml",
                control_checkpoint=checkpoint,
            ),
        )
        self.assertTrue(
            epub._is_space_separated_tokens(
                "alternate stylesheet",
                checkpoint,
            )
        )
        self.assertFalse(
            epub._is_space_separated_tokens(
                "alternate  stylesheet",
                checkpoint,
            )
        )
        self.assertGreater(len(calls), 6)

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

    def test_epub_host_metadata_is_bounded_before_whitespace_normalization(self):
        import acs.book_epub_import as epub

        raw = _simple_epub(b'<html><body><p>Readable</p></body></html>')
        cases = (
            {'source_name': '123456789'},
            {'source_name': 'ok.epub', 'title': '123456789'},
            {'source_name': 'ok.epub', 'author': '123456789'},
            {'source_name': 'ok.epub', 'language': '123456789'},
        )
        with patch.object(epub, 'MAX_BOOK_TEXT_FIELD_CHARS', 8):
            for kwargs in cases:
                with self.subTest(kwargs=kwargs):
                    with self.assertRaises(epub.BookEpubImportError) as caught:
                        import_epub_book(raw, **kwargs)
                    self.assertEqual(
                        caught.exception.code,
                        epub.BookEpubImportErrorCode.RESOURCE_LIMIT,
                    )
                    self.assertIn('BookDocument text field limit', str(caught.exception))

            imported = import_epub_book(raw, source_name='12345678')

        self.assertEqual(imported.document.source_name, '12345678')

    def test_epub_max_source_label_does_not_overflow_nested_html_metadata(self):
        import acs.book_epub_import as epub

        raw = _simple_epub(b'<html><body><p>Readable</p></body></html>')
        source_name = 's' * 64
        with (
            patch.object(epub, 'MAX_BOOK_TEXT_FIELD_CHARS', 64),
            patch.object(epub, 'import_html_book', wraps=epub.import_html_book) as html_import,
        ):
            imported = import_epub_book(raw, source_name=source_name)

        self.assertEqual(imported.document.source_name, source_name)
        self.assertEqual(
            html_import.call_args.kwargs['source_name'],
            'OEBPS/Text/ch1.xhtml',
        )

    def test_epub_final_bookdocument_aggregate_overflow_maps_to_resource_limit(self):
        import acs.book_epub_import as epub
        from acs.bookdocument import BookDocumentErrorCode

        raw = _simple_epub(b'<html><body><p>Readable semantic text</p></body></html>')
        failure = epub.BookDocumentError(
            'BookDocument text exceeds the canonical aggregate limit',
            code=BookDocumentErrorCode.INVALID_FIELD,
        )
        with patch.object(epub, 'BookDocument', side_effect=failure):
            with self.assertRaises(epub.BookEpubImportError) as caught:
                import_epub_book(raw, source_name='book.epub')

        self.assertEqual(
            caught.exception.code,
            epub.BookEpubImportErrorCode.RESOURCE_LIMIT,
        )
        self.assertIn('canonical BookDocument limits', str(caught.exception))
        self.assertIs(caught.exception.__cause__, failure)

    def test_epub_rebased_source_anchor_fails_with_stable_resource_limit(self):
        import acs.book_epub_import as epub

        block = epub.Heading(text='Chapter', source_anchor='anchor')
        with patch.object(epub, 'MAX_BOOK_SOURCE_ANCHOR_CHARS', 10):
            with self.assertRaises(epub.BookEpubImportError) as caught:
                epub._rebase_block(block, '1234', 1, 1)

        self.assertEqual(
            caught.exception.code,
            epub.BookEpubImportErrorCode.RESOURCE_LIMIT,
        )
        self.assertIn('source anchor', str(caught.exception))

    def test_epub_rebased_source_anchor_allows_exact_canonical_boundary(self):
        import acs.book_epub_import as epub

        block = epub.Heading(text='Chapter', source_anchor='abcd')
        with patch.object(epub, 'MAX_BOOK_SOURCE_ANCHOR_CHARS', 8):
            rebased = epub._rebase_block(block, '123', 1, 1)

        self.assertEqual(rebased.source_anchor, '123#abcd')
        self.assertTrue(rebased.block_id.startswith('epub-'))

    def test_epub_aggregate_blocks_fail_closed_at_canonical_document_limit(self):
        import acs.book_epub_import as epub

        manifest = '\n'.join((
            '    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>',
            '    <item id="c2" href="Text/ch2.xhtml" media-type="application/xhtml+xml"/>',
        ))
        spine = '\n'.join((
            '    <itemref idref="c1"/>',
            '    <itemref idref="c2"/>',
        ))
        chapter = b'<html><body><h1>Heading</h1><p>Paragraph</p></body></html>'
        raw = _epub(
            opf=_opf(manifest=manifest, spine=spine),
            entries={
                'OEBPS/Text/ch1.xhtml': chapter,
                'OEBPS/Text/ch2.xhtml': chapter,
            },
        )

        with patch.object(epub, '_rebase_block', wraps=epub._rebase_block) as rebase:
            with patch.object(epub, 'MAX_BOOK_DOCUMENT_BLOCKS', 3):
                with self.assertRaises(epub.BookEpubImportError) as caught:
                    import_epub_book(raw, source_name='aggregate-limit.epub')

        self.assertEqual(
            caught.exception.code,
            epub.BookEpubImportErrorCode.RESOURCE_LIMIT,
        )
        self.assertIn('BookDocument block limit', str(caught.exception))
        self.assertEqual(rebase.call_count, 3)

    def test_epub_aggregate_blocks_allow_exact_canonical_document_limit(self):
        import acs.book_epub_import as epub

        manifest = '\n'.join((
            '    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>',
            '    <item id="c2" href="Text/ch2.xhtml" media-type="application/xhtml+xml"/>',
        ))
        spine = '\n'.join((
            '    <itemref idref="c1"/>',
            '    <itemref idref="c2"/>',
        ))
        chapter = b'<html><body><h1>Heading</h1><p>Paragraph</p></body></html>'
        raw = _epub(
            opf=_opf(manifest=manifest, spine=spine),
            entries={
                'OEBPS/Text/ch1.xhtml': chapter,
                'OEBPS/Text/ch2.xhtml': chapter,
            },
        )

        with patch.object(epub, 'MAX_BOOK_DOCUMENT_BLOCKS', 4):
            imported = import_epub_book(raw, source_name='aggregate-boundary.epub')

        self.assertEqual(len(imported.document.blocks), 4)
        self.assertEqual(imported.spine_documents, 2)

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


    def test_html_host_source_name_trim_observes_control_inside_one_token(self):
        failure = SourceReadCancelledError(
            "cancelled during HTML host source-name normalization"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            import_html_book(
                "<p>Readable</p>",
                source_name=(" " * 20_000) + "book.html",
                control_checkpoint=cancel,
            )

        self.assertIs(caught.exception, failure)

    def test_html_host_optional_metadata_trim_observes_control(self):
        failure = SourceReadCancelledError(
            "cancelled during HTML host title normalization"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 5:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            import_html_book(
                "<p>Readable</p>",
                source_name="book.html",
                title=(" " * 20_000) + "Title",
                control_checkpoint=cancel,
            )

        self.assertIs(caught.exception, failure)

    def test_html_controlled_host_metadata_preserves_strip_semantics(self):
        plain = import_html_book(
            "<p>Readable</p>",
            source_name="\u2003 book.html \u2002",
            title="\t  Study Title  \n",
            author="  Author  ",
            language="\r uk \t",
        )
        controlled = import_html_book(
            "<p>Readable</p>",
            source_name="\u2003 book.html \u2002",
            title="\t  Study Title  \n",
            author="  Author  ",
            language="\r uk \t",
            control_checkpoint=lambda: None,
        )

        self.assertEqual(plain.document.as_dict(), controlled.document.as_dict())
        self.assertEqual(plain.book_key, controlled.book_key)


    def test_epub_host_metadata_normalization_observes_control_inside_one_token(self):
        import acs.book_epub_import as epub

        failure = SourceReadCancelledError(
            "cancelled during EPUB host metadata normalization"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._required_text(
                (" " * 20_000) + "book.epub",
                "source_name",
                cancel,
            )

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_epub_controlled_host_metadata_preserves_collapse_semantics(self):
        import acs.book_epub_import as epub

        sample = "\u2003  Study\tTitle\nwith\rmetadata  \u2002"
        calls = []
        controlled = epub._required_text(
            sample,
            "title",
            lambda: calls.append(1),
        )

        self.assertEqual(controlled, epub._required_text(sample, "title"))
        self.assertEqual(controlled, "Study Title with metadata")
        self.assertGreaterEqual(len(calls), 2)

    def test_epub_import_threads_control_into_all_host_metadata_fields(self):
        import acs.book_epub_import as epub

        raw = _simple_epub(b"<html><body><p>Readable</p></body></html>")
        real_required = epub._required_text
        observed = []

        def observing_required(value, field, control_checkpoint=None):
            observed.append((field, control_checkpoint))
            return real_required(value, field, control_checkpoint)

        checkpoint = lambda: None
        with patch.object(epub, "_required_text", side_effect=observing_required):
            imported = epub.import_epub_book(
                raw,
                source_name=" book.epub ",
                title=" Title ",
                author=" Author ",
                language=" uk ",
                control_checkpoint=checkpoint,
            )

        self.assertEqual(imported.document.title, "Title")
        self.assertEqual(imported.document.author, "Author")
        self.assertEqual(imported.document.language, "uk")
        self.assertEqual(
            [field for field, _ in observed],
            ["source_name", "title", "author", "language"],
        )
        self.assertTrue(all(callback is checkpoint for _, callback in observed))


    def test_epub_dublin_core_text_normalization_observes_control_inside_one_value(self):
        import acs.book_epub_import as epub
        import xml.etree.ElementTree as ET

        metadata = ET.Element("{http://www.idpf.org/2007/opf}metadata")
        title = ET.SubElement(
            metadata,
            "{http://purl.org/dc/elements/1.1/}title",
        )
        title.text = (" " * 20_000) + "Study"
        failure = SourceReadCancelledError(
            "cancelled during Dublin Core metadata normalization"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._metadata_values(metadata, "title", cancel)

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_epub_dublin_core_control_preserves_whitespace_semantics(self):
        import acs.book_epub_import as epub
        import xml.etree.ElementTree as ET

        metadata = ET.Element("{http://www.idpf.org/2007/opf}metadata")
        title = ET.SubElement(
            metadata,
            "{http://purl.org/dc/elements/1.1/}title",
        )
        title.text = "\u2003  Study\tTitle\nwith\rmetadata  \u2002"

        plain = epub._metadata_values(metadata, "title")
        calls = []
        controlled = epub._metadata_values(
            metadata,
            "title",
            lambda: calls.append(1),
        )

        self.assertEqual(controlled, plain)
        self.assertEqual(controlled, ["Study Title with metadata"])
        self.assertGreaterEqual(len(calls), 2)

    def test_epub_first_heading_fallback_observes_control_before_late_heading(self):
        import acs.book_epub_import as epub

        blocks = [object() for _ in range(300)]
        blocks.append(epub.Heading(text="Late heading"))
        failure = SourceReadCancelledError(
            "cancelled during EPUB first-heading fallback"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._first_heading_text(blocks, cancel)

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_epub_creator_rights_join_observes_control_inside_large_collection(self):
        import acs.book_epub_import as epub

        values = [f"Creator {index}" for index in range(400)]
        failure = SourceReadCancelledError(
            "cancelled during EPUB metadata aggregation"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._controlled_join(values, "; ", cancel)

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)
        self.assertEqual(
            epub._controlled_join(["A", "B", "C"], "; ", lambda: None),
            "A; B; C",
        )


    def test_epub_href_surrounding_whitespace_strip_observes_control(self):
        import acs.book_epub_import as epub

        failure = SourceReadCancelledError(
            "cancelled while stripping one long EPUB href"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._resolve_package_href(
                "",
                (" " * 20_000) + "Text/chapter.xhtml",
                allow_surrounding_whitespace=True,
                control_checkpoint=cancel,
            )

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_epub_xml_whitespace_scan_observes_control_inside_one_text_node(self):
        import acs.book_epub_import as epub

        failure = SourceReadCancelledError(
            "cancelled during one long whitespace-only XML text node"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._has_non_whitespace(" " * 20_000, cancel)

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_epub_scalar_control_helpers_preserve_python_whitespace_semantics(self):
        import acs.book_epub_import as epub

        sample = "\u2003\t  Text/chapter.xhtml  \n\u2002"
        calls = []
        controlled = epub._controlled_strip(sample, lambda: calls.append(1))

        self.assertEqual(controlled, sample.strip())
        self.assertFalse(
            epub._has_non_whitespace(" \t\r\n\u2003", lambda: None)
        )
        self.assertTrue(
            epub._has_non_whitespace(" \t readable \u2002", lambda: None)
        )
        self.assertGreaterEqual(len(calls), 2)

    def test_epub_mime_checkpointed_slash_scan_preserves_exact_grammar(self):
        import acs.book_epub_import as epub

        calls = []
        self.assertEqual(
            epub._normalized_media_type(
                "Application/XHTML+XML",
                context="test",
                control_checkpoint=lambda: calls.append(1),
            ),
            "application/xhtml+xml",
        )
        self.assertGreaterEqual(len(calls), 3)
        for malformed in (
            "application//xhtml+xml",
            "/xhtml+xml",
            "application/",
            " application/xhtml+xml",
            "application/xhtml+xml ",
        ):
            with self.subTest(malformed=malformed):
                with self.assertRaises(epub.BookEpubImportError):
                    epub._normalized_media_type(
                        malformed,
                        context="test",
                        control_checkpoint=lambda: None,
                    )


    def test_html_explicit_pgn_long_first_line_strip_observes_control(self):
        import acs.book_html_import as html

        failure = SourceReadCancelledError(
            "cancelled while trimming one long explicit-PGN line"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise failure

        raw = (" " * 20_000) + "{PGN 1}\n[Event \"Study\"]\n"
        with self.assertRaises(SourceReadCancelledError) as caught:
            html._explicit_pgn_pre(raw, cancel)

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)

    def test_html_pgn_line_rstrip_observes_control_inside_one_long_line(self):
        import acs.book_html_import as html

        failure = SourceReadCancelledError(
            "cancelled while trimming one long PGN candidate line"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            html._controlled_rstrip("move" + (" " * 20_000), cancel)

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_html_visible_part_join_observes_control_across_large_part_collection(self):
        import acs.book_html_import as html

        values = [f"part-{index}" for index in range(400)]
        failure = SourceReadCancelledError(
            "cancelled during visible-text assembly"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            html._controlled_join_strings(values, "", cancel)

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)
        self.assertEqual(
            html._controlled_join_strings(["a", "b", "c"], "-", lambda: None),
            "a-b-c",
        )

    def test_html_explicit_pgn_region_count_is_resource_bounded(self):
        import acs.book_html_import as html

        visible = """{PGN 1}
[Event "One"]
[Result "*"]

1. e4 *
{PGN 2}
[Event "Two"]
[Result "*"]

1. d4 *
{PGN 3}
[Event "Three"]
[Result "*"]

1. Nf3 *
"""
        with patch.object(html, "MAX_HTML_PGN_CANDIDATES", 2):
            with self.assertRaises(html.BookHtmlImportError) as caught:
                html._pgn_candidates(visible, lambda: None)

        self.assertEqual(
            caught.exception.code,
            html.BookHtmlImportErrorCode.RESOURCE_LIMIT,
        )
        self.assertIn("too many explicitly marked PGN regions", str(caught.exception))


    def test_html_unicode_source_encoding_observes_control_between_chunks(self):
        import acs.book_html_import as html

        failure = SourceReadCancelledError(
            "cancelled during HTML Unicode source encoding"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            html._source_text("x" * 50_000, cancel)

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_html_oversized_unicode_source_fails_resource_limit_before_encoding(self):
        import acs.book_html_import as html

        invalid_unicode = chr(0xD800) * 9
        with patch.object(html, "MAX_HTML_SOURCE_BYTES", 8):
            with self.assertRaises(html.BookHtmlImportError) as caught:
                html._source_text(invalid_unicode, lambda: None)

        self.assertEqual(
            caught.exception.code,
            html.BookHtmlImportErrorCode.RESOURCE_LIMIT,
        )

    def test_html_controlled_unicode_source_encoding_preserves_exact_bytes(self):
        import acs.book_html_import as html

        source = "Zażółć gęślą ♟\n<p>Readable</p>"
        plain = html._source_text(source)
        calls = []
        controlled = html._source_text(source, lambda: calls.append(1))

        self.assertEqual(controlled, plain)
        self.assertEqual(controlled[1], source.encode("utf-8"))
        self.assertGreaterEqual(len(calls), 2)


    def test_html_markup_names_are_bounded_before_case_normalization(self):
        import acs.book_html_import as html

        with patch.object(html, "MAX_HTML_MARKUP_NAME_CHARS", 8):
            parser = html._SemanticHtmlParser(available_assets=None)
            with self.assertRaises(html.BookHtmlImportError) as start_caught:
                parser.handle_starttag("x" * 9, [])
            self.assertEqual(
                start_caught.exception.code,
                html.BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )

            parser = html._SemanticHtmlParser(available_assets=None)
            with self.assertRaises(html.BookHtmlImportError) as attr_caught:
                parser.handle_starttag("div", [("x" * 9, "value")])
            self.assertEqual(
                attr_caught.exception.code,
                html.BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )

            parser = html._SemanticHtmlParser(available_assets=None)
            with self.assertRaises(html.BookHtmlImportError) as end_caught:
                parser.handle_endtag("x" * 9)
            self.assertEqual(
                end_caught.exception.code,
                html.BookHtmlImportErrorCode.RESOURCE_LIMIT,
            )

    def test_html_aria_hidden_trim_observes_control_inside_one_attribute(self):
        failure = SourceReadCancelledError(
            "cancelled during aria-hidden normalization"
        )
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
        with self.assertRaises(SourceReadCancelledError) as caught:
            parser.handle_starttag(
                "section",
                [("aria-hidden", (" " * 20_000) + "true")],
            )

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)
        self.assertEqual(parser.blocks, [])

    def test_html_image_src_trim_observes_control_inside_one_attribute(self):
        failure = SourceReadCancelledError(
            "cancelled during image src normalization"
        )
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
        with self.assertRaises(SourceReadCancelledError) as caught:
            parser.handle_starttag(
                "img",
                [("src", (" " * 20_000) + "images/board.png")],
            )

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 3)
        self.assertEqual(parser.image_references, [])

    def test_html_asset_name_controlled_segmentation_preserves_relative_semantics(self):
        import acs.book_html_import as html

        calls = []
        self.assertEqual(
            html._asset_name(
                " images\\boards/./main.png?size=2#diagram ",
                lambda: calls.append(1),
            ),
            "images/boards/main.png",
        )
        self.assertEqual(
            html._asset_name("../secret.png", lambda: None),
            "",
        )
        self.assertEqual(
            html._asset_name("https://example.test/board.png", lambda: None),
            "",
        )
        self.assertGreaterEqual(len(calls), 4)


    def test_html_block_identity_hash_observes_control_inside_large_payload(self):
        failure = SourceReadCancelledError(
            "cancelled during HTML block identity hashing"
        )
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
            parser._block_id("Paragraph", "x" * 20_000)

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)
        self.assertEqual(parser._ids, {})

    def test_html_controlled_block_identity_preserves_exact_digest_and_occurrence(self):
        plain = _SemanticHtmlParser(available_assets=None)
        controlled = _SemanticHtmlParser(
            available_assets=None,
            control_checkpoint=lambda: None,
        )
        payload = ("Chess text " * 1_000) + "♟"

        self.assertEqual(
            controlled._block_id("Paragraph", payload),
            plain._block_id("Paragraph", payload),
        )
        self.assertEqual(
            controlled._block_id("Paragraph", payload),
            plain._block_id("Paragraph", payload),
        )

    def test_html_ordered_start_trim_observes_control_inside_one_attribute(self):
        failure = SourceReadCancelledError(
            "cancelled during ordered-list start normalization"
        )
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
            parser._ordered_start({"start": (" " * 20_000) + "7"})

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_html_ordered_start_digit_token_is_bounded_before_regex_and_int(self):
        import acs.book_html_import as html

        parser = _SemanticHtmlParser(available_assets=None)
        with patch.object(html, "MAX_HTML_LIST_START_CHARS", 8):
            self.assertEqual(
                parser._ordered_start({"start": "9" * 9}),
                (None, False),
            )
            self.assertEqual(
                parser._ordered_start({"start": "12345678"}),
                (12345678, True),
            )


    def test_html_text_digest_observes_control_inside_large_semantic_payload(self):
        import acs.book_html_import as html

        failure = SourceReadCancelledError(
            "cancelled during HTML semantic digest"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            html._sha256_text_hex("x" * 20_000, cancel)

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_html_source_digest_observes_control_inside_large_byte_source(self):
        import acs.book_html_import as html

        failure = SourceReadCancelledError(
            "cancelled during HTML source digest"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            html._sha256_bytes_hex(b"x" * 200_000, cancel)

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_html_controlled_digests_preserve_exact_legacy_hashes(self):
        import acs.book_html_import as html
        from hashlib import sha256

        text_value = ("Chess ♟ metadata " * 1_000) + "tail"
        byte_value = text_value.encode("utf-8")
        text_calls = []
        byte_calls = []

        self.assertEqual(
            html._sha256_text_hex(
                text_value,
                lambda: text_calls.append(1),
            ),
            sha256(byte_value).hexdigest(),
        )
        self.assertEqual(
            html._sha256_bytes_hex(
                byte_value,
                lambda: byte_calls.append(1),
            ),
            sha256(byte_value).hexdigest(),
        )
        self.assertGreaterEqual(len(text_calls), 2)
        self.assertGreaterEqual(len(byte_calls), 2)


    def test_epub_source_digest_observes_control_inside_large_byte_source(self):
        import acs.book_epub_import as epub

        failure = SourceReadCancelledError(
            "cancelled during EPUB source digest"
        )
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure

        with self.assertRaises(SourceReadCancelledError) as caught:
            epub._sha256_bytes_hex(b"x" * 200_000, cancel)

        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, 2)

    def test_epub_rebase_digest_observes_control_and_preserves_legacy_id(self):
        import acs.book_epub_import as epub
        from acs.bookdocument import Paragraph
        from hashlib import sha256

        block = Paragraph(
            text="Readable",
            block_id="html-legacy-1",
            source_anchor="p1",
        )
        entry_name = "Text/" + ("chapter-" * 1_000) + ".xhtml"
        identity = f"{entry_name}\0{3}\0{7}\0{block.block_id}"
        expected_id = f"epub-{sha256(identity.encode('utf-8')).hexdigest()[:24]}"

        calls = []
        rebased = epub._rebase_block(
            block,
            entry_name,
            3,
            7,
            lambda: calls.append(1),
        )

        self.assertEqual(rebased.block_id, expected_id)
        self.assertEqual(rebased.source_anchor, f"{entry_name}#p1")
        self.assertGreaterEqual(len(calls), 2)

    def test_epub_controlled_source_digest_preserves_exact_book_key_hash(self):
        import acs.book_epub_import as epub
        from hashlib import sha256

        value = (b"accessible-chess-epub" * 10_000)
        calls = []
        self.assertEqual(
            epub._sha256_bytes_hex(value, lambda: calls.append(1)),
            sha256(value).hexdigest(),
        )
        self.assertGreaterEqual(len(calls), 2)


    def test_html_capture_source_anchor_uses_canonical_capture_attrs(self):
        imported = import_html_book(
            '<html><body><p id="p1">Readable</p></body></html>',
            source_name='capture-anchor.html',
        )

        self.assertEqual(len(imported.document.blocks), 1)
        self.assertEqual(imported.document.blocks[0].source_anchor, 'p1')

    def test_html_rich_list_fallback_uses_list_attrs_without_runtime_hook(self):
        imported = import_html_book(
            '<html><body><ul id="list"><li>First</li>'
            '<li id="rich">Before <img alt="Diagram note"> After</li>'
            '</ul></body></html>',
            source_name='rich-list.html',
        )

        self.assertGreaterEqual(len(imported.document.blocks), 3)
        self.assertTrue(
            any(
                getattr(block, 'source_anchor', None) == 'list'
                for block in imported.document.blocks
            )
        )

    def test_html_pgn_candidate_scan_uses_each_candidate_line(self):
        import acs.book_html_import as html

        candidates = html._pgn_candidates(
            '{PGN 1}\n[Event "Study"]\n[Result "*"]\n\n1. e4 *\n'
            'End of PGN Supplement\nAfter'
        )

        self.assertEqual(len(candidates), 1)
        self.assertIn('[Event "Study"]', candidates[0].text)
        self.assertNotIn('After', candidates[0].text)

    def test_html_aria_hidden_true_is_excluded_from_accessible_document(self):
        imported = import_html_book(
            '<html><body><section aria-hidden=" true ">'
            '<p>Secret text</p></section><p>Visible text</p></body></html>',
            source_name='aria-hidden.html',
        )

        readable = '\n'.join(
            getattr(block, 'text', '')
            for block in imported.document.blocks
        )
        self.assertNotIn('Secret text', readable)
        self.assertIn('Visible text', readable)


if __name__ == '__main__':
    unittest.main()
