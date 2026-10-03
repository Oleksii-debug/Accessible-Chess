from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.library_export_service import LibraryExportRequest, LibraryExportService
from acs.library_import_service import LibraryImportService
from acs.pgn_document import PgnDocumentSession
from acs.pgn_roundtrip import canonical_round_trip_text
from acs.pgn_service import open_pgn
from acs.search_service import GameSearchQuery, GameSearchService
from acs.settings import Settings
from acs.version2_application import Version2Application
from acs.version2_release_app import _version2_user_data_layout
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)
from acs.version2_windows_library_export import (
    LibraryExportHostEventKind,
    Version2WindowsLibraryExportDelegate,
)


PGN_TEXT = """[Event "Київ Path Test"]
[Site "Bratislava SVK"]
[Date "2026.09.29"]
[Round "1"]
[White "Олексій"]
[Black "Éva"]
[Result "*"]

1. e4 {центр} e5 (1... c5 $5) 2. Nf3 Nc6 *
"""

LIBRARY_PGN = PGN_TEXT + "\n" + PGN_TEXT.replace(
    'Київ Path Test', 'Filtered Cup'
).replace('[Round "1"]', '[Round "2"]')


_CONTAINER = b"""<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""


def _epub(chapter: bytes) -> bytes:
    opf = b"""<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0"
 xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
  <metadata>
    <dc:title>Unicode Path EPUB</dc:title>
    <dc:language>uk</dc:language>
    <dc:rights>Test fixture</dc:rights>
  </metadata>
  <manifest>
    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>"""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        archive.writestr(mimetype, b"application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            _CONTAINER,
            compress_type=zipfile.ZIP_DEFLATED,
        )
        archive.writestr(
            "OEBPS/content.opf",
            opf,
            compress_type=zipfile.ZIP_DEFLATED,
        )
        archive.writestr(
            "OEBPS/Text/ch1.xhtml",
            chapter,
            compress_type=zipfile.ZIP_DEFLATED,
        )
    return buffer.getvalue()


class _FileDialogs:
    def __init__(self) -> None:
        self.open_path: Path | None = None
        self.save_path: Path | None = None
        self.import_path: Path | None = None

    def open_pgn(self) -> Path | None:
        return self.open_path

    def save_pgn_as(self, suggested_filename: str = "game.pgn") -> Path | None:
        return self.save_path

    def select_library_import(self) -> Path | None:
        return self.import_path


class _ExportDialogs:
    def __init__(self, destination: Path) -> None:
        self.destination = destination

    def export_selection(self, suggested_filename: str = "library-export.pgn") -> Path:
        return self.destination


class WindowsUnicodePathPortabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Шахи тест" / "Папка з пробілами"
        self.root.mkdir(parents=True)
        self.assertTrue(self.root.is_dir())

    def _file_delegate(self, dialogs: _FileDialogs, database_path: Path | None = None):
        events = []
        session_box = {"value": None}

        def services_factory() -> Version2ImportWorkerServices:
            if database_path is None:
                raise AssertionError("Library import was not expected")
            database = AcsDatabase(database_path)
            return Version2ImportWorkerServices(
                LibraryImportService(database),
                None,
                database.close,
            )

        delegate = Version2WindowsFileActionDelegate(
            dialogs=dialogs,
            get_pgn_session=lambda: session_box["value"],
            set_pgn_session=lambda value: session_box.__setitem__("value", value),
            import_services_factory=services_factory,
            event_sink=events.append,
            next_delegate=lambda action_id, payload: ("fallback", action_id),
            current_focus_provider=lambda: "pgn-tree",
        )
        return delegate, events, session_box

    def test_settings_and_native_pgn_open_save_as_reopen(self) -> None:
        state_dir = self.root / "Дані користувача"
        state_dir.mkdir()
        layout = _version2_user_data_layout(
            data_root=state_dir,
            settings_path=state_dir / "налаштування з пробілами.json",
        )
        self.assertEqual(layout.root, state_dir)
        settings_path = layout.settings_path

        settings = Settings(settings_path)
        settings.set("volume", 37)
        reopened_settings = Settings(settings_path)
        self.assertEqual(reopened_settings.get("volume"), 37)
        self.assertEqual(
            json.loads(settings_path.read_text(encoding="utf-8"))["values"]["volume"],
            37,
        )

        pgn_dir = self.root / "Партії з пробілами"
        pgn_dir.mkdir()
        source = pgn_dir / "вхідна партія.pgn"
        destination = pgn_dir / "збережена партія з пробілами.pgn"
        source.write_text(canonical_round_trip_text(PGN_TEXT).text, encoding="utf-8")

        dialogs = _FileDialogs()
        dialogs.open_path = source
        dialogs.save_path = destination
        delegate, events, session_box = self._file_delegate(dialogs)

        opened = delegate("pgn.open", {})
        self.assertEqual(opened.kind, FileWorkflowEventKind.PGN_OPENED)
        session = session_box["value"]
        self.assertIsInstance(session, PgnDocumentSession)
        session.edit_tag("Event", "Київ — збережено")
        saved = delegate("pgn.save_as", {})
        self.assertEqual(saved.kind, FileWorkflowEventKind.PGN_SAVED_AS)

        reopen_dialogs = _FileDialogs()
        reopen_dialogs.open_path = destination
        reopen_delegate, reopen_events, reopen_session_box = self._file_delegate(reopen_dialogs)
        reopened_event = reopen_delegate("pgn.open", {})
        self.assertEqual(reopened_event.kind, FileWorkflowEventKind.PGN_OPENED)
        reopened = reopen_session_box["value"]
        self.assertIsInstance(reopened, PgnDocumentSession)
        self.assertEqual(reopened.workspace.current_game().tags["Event"], "Київ — збережено")
        self.assertEqual(open_pgn(destination).games, reopened.workspace.games())

        rendered = repr((*events, *reopen_events))
        self.assertNotIn(str(self.root), rendered)
        self.assertNotIn(source.name, rendered)
        self.assertNotIn(destination.name, rendered)

    def test_library_native_import_selected_and_filtered_export_reopen(self) -> None:
        library_dir = self.root / "Бібліотека даних"
        import_dir = self.root / "Імпорт з пробілами"
        export_dir = self.root / "Експорт з пробілами"
        for directory in (library_dir, import_dir, export_dir):
            directory.mkdir()

        database_path = library_dir / "бібліотека шахів.acsdb"
        source = import_dir / "джерело партій з пробілами.pgn"
        source.write_text(canonical_round_trip_text(LIBRARY_PGN).text, encoding="utf-8")

        dialogs = _FileDialogs()
        dialogs.import_path = source
        delegate, import_events, _ = self._file_delegate(dialogs, database_path)
        started = delegate("library.import", {})
        self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
        self.assertTrue(delegate.wait_for_import(20.0))
        self.assertEqual(import_events[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
        self.assertEqual(import_events[-1].game_count, 2)

        with AcsDatabase(database_path) as database:
            search = GameSearchService(database)
            service = LibraryExportService(database, search_service=search)
            all_items = search.search(GameSearchQuery(limit=20)).items
            self.assertEqual(len(all_items), 2)

            selected_destination = export_dir / "вибрані партії.pgn"
            selected_events = []
            selected_delegate = Version2WindowsLibraryExportDelegate(
                dialogs=_ExportDialogs(selected_destination),
                service=service,
                event_sink=selected_events.append,
                next_delegate=lambda action_id, payload: ("fallback", action_id),
                current_focus_provider=lambda: "library-results",
            )
            selected_request = LibraryExportRequest.selected([all_items[0].game_id])
            selected_event = selected_delegate(
                "library.export",
                selected_request.browser_payload(),
            )
            self.assertEqual(selected_event.kind, LibraryExportHostEventKind.EXPORTED)
            self.assertEqual(len(open_pgn(selected_destination).games), 1)

            filtered_destination = export_dir / "відфільтровані партії.pgn"
            filtered_events = []
            filtered_delegate = Version2WindowsLibraryExportDelegate(
                dialogs=_ExportDialogs(filtered_destination),
                service=service,
                event_sink=filtered_events.append,
                next_delegate=lambda action_id, payload: ("fallback", action_id),
                current_focus_provider=lambda: "library-results",
            )
            filtered_request = LibraryExportRequest.filtered(
                GameSearchQuery(event="filtered cup")
            )
            filtered_event = filtered_delegate(
                "library.export",
                filtered_request.browser_payload(),
            )
            self.assertEqual(filtered_event.kind, LibraryExportHostEventKind.EXPORTED)
            filtered = open_pgn(filtered_destination)
            self.assertEqual(len(filtered.games), 1)
            self.assertEqual(filtered.games[0].tags["Event"], "Filtered Cup")

            rendered = repr((*selected_events, *filtered_events))
            self.assertNotIn(str(self.root), rendered)
            self.assertNotIn(selected_destination.name, rendered)
            self.assertNotIn(filtered_destination.name, rendered)

            blocked_parent = export_dir / "заблокований каталог"
            blocked_parent.write_text("occupied", encoding="utf-8")
            failed_destination = blocked_parent / "приватна назва партій.pgn"
            failure_events = []
            failure_delegate = Version2WindowsLibraryExportDelegate(
                dialogs=_ExportDialogs(failed_destination),
                service=service,
                event_sink=failure_events.append,
                next_delegate=lambda action_id, payload: ("fallback", action_id),
                current_focus_provider=lambda: "library-results",
            )
            failed_event = failure_delegate(
                "library.export",
                selected_request.browser_payload(),
            )
            self.assertEqual(failed_event.kind, LibraryExportHostEventKind.FAILED)
            self.assertEqual(failed_event.error_code, "library_export_failed")
            self.assertEqual(
                database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0],
                2,
            )
            failed_rendered = repr(failure_events)
            self.assertNotIn(str(self.root), failed_rendered)
            self.assertNotIn(blocked_parent.name, failed_rendered)
            self.assertNotIn(failed_destination.name, failed_rendered)

        with AcsDatabase(database_path) as reopened_database:
            self.assertEqual(
                reopened_database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0],
                2,
            )

        self.assertNotIn(str(self.root), repr(import_events))
        self.assertNotIn(source.name, repr(import_events))

    def test_books_txt_html_epub_open_progress_reopen_and_path_safe_failure(self) -> None:
        book_dir = self.root / "Книги з пробілами"
        state_dir = self.root / "Стан читання"
        book_dir.mkdir()
        state_dir.mkdir()

        txt = book_dir / "текстова книга з пробілами.txt"
        txt.write_text(
            "Перший абзац — Úvod.\n\nДругий абзац — posición.\n\nТретій абзац.",
            encoding="utf-8",
        )
        html = book_dir / "книга українською з пробілами.html"
        html.write_text(
            "<html lang='uk'><head><title>HTML шлях</title></head>"
            "<body><h1>Розділ</h1><p>Доступний текст.</p><p>Ще текст.</p></body></html>",
            encoding="utf-8",
        )
        epub = book_dir / "навчання з пробілами.epub"
        epub.write_bytes(
            _epub(
                b"<html lang='uk'><body><h1>EPUB path</h1>"
                b"<p>Readable.</p><p>Second paragraph.</p></body></html>"
            )
        )

        database = AcsDatabase(state_dir / "бібліотека книги.acsdb")
        self.addCleanup(database.close)
        analysis = AnalysisService(lambda: None)
        self.addCleanup(analysis.close)
        progress = BookProgressStore(state_dir / "прогрес читання.json")
        engine = EngineAssistedWorkflowService(analysis)

        for source in (txt, html, epub):
            with self.subTest(source=source.suffix):
                app = Version2Application(
                    database,
                    progress_store=progress,
                    engine_assistance=engine,
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                app.open_book_dialog = lambda source=source: source
                opened = app.browser_command("shell", "book.open")
                self.assertEqual(opened["kind"], "delegated")
                self.assertNotIn(str(self.root), json.dumps(opened, ensure_ascii=False))
                self.assertNotIn(source.name, json.dumps(opened, ensure_ascii=False))
                self.assertNotIn(
                    str(self.root),
                    json.dumps(app.snapshot(), ensure_ascii=False),
                )
                moved = app.reader.next_block()
                app.save_book_progress()
                saved_key = app.book_key

                restarted = Version2Application(
                    database,
                    progress_store=progress,
                    engine_assistance=engine,
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                restarted.open_book_dialog = lambda source=source: source
                reopened = restarted.browser_command("shell", "book.open")
                self.assertEqual(reopened["kind"], "delegated")
                self.assertNotIn(str(self.root), json.dumps(reopened, ensure_ascii=False))
                self.assertNotIn(source.name, json.dumps(reopened, ensure_ascii=False))
                self.assertNotIn(
                    str(self.root),
                    json.dumps(restarted.snapshot(), ensure_ascii=False),
                )
                self.assertEqual(restarted.book_key, saved_key)
                self.assertEqual(restarted.reader.location(), moved)

        bad = book_dir / "пошкоджена книга з пробілами.epub"
        bad.write_bytes(b"not-an-epub")
        app = Version2Application(
            database,
            progress_store=progress,
            engine_assistance=engine,
            board_dispatch=lambda *_: None,
            board_position_projector=lambda _fen: {"ok": True},
        )
        app.open_book_dialog = lambda: bad
        result = app.browser_command("shell", "book.open")
        rendered = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["kind"], "error")
        self.assertNotIn(str(self.root), rendered)
        self.assertNotIn(bad.name, rendered)


if __name__ == "__main__":
    unittest.main()
