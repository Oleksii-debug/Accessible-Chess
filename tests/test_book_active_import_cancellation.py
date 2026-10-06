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
