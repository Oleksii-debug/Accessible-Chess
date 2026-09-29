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
from acs.pgn_service import open_pgn
from acs.presentation_privacy import redact_local_paths
from acs.search_service import GameSearchQuery
from acs.settings import Settings
from acs.version2_application import Version2Application


_LIBRARY_PGN = """[Event "Шляхова партія"]
[White "Олена"]
[Black "Борис"]
[Result "*"]

1. e4 e5 *

[Event "Друга партія"]
[White "Ірина"]
[Black "Марко"]
[Result "*"]

1. d4 d5 *
"""

_CONTAINER = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''


def _epub(chapter: bytes) -> bytes:
    opf = b'''<?xml version="1.0" encoding="UTF-8"?>
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
</package>'''
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


class WindowsPathPortabilitySpacesCyrillicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Шахи тест" / "Папка з пробілами"
        self.root.mkdir(parents=True)

    def test_settings_persist_and_reopen_under_spaces_and_cyrillic(self) -> None:
        path = self.root / "Стан користувача" / "налаштування програми.json"

        settings = Settings(path)
        settings.set("language", "en")
        settings.set("notation", "san")
        settings.set("volume", 37)
        settings.set("sounds", False)

        persisted = path.read_bytes()
        self.assertTrue(persisted.endswith(b"\n"))
        self.assertFalse(path.with_suffix(path.suffix + ".tmp").exists())

        reopened = Settings(path)
        self.assertEqual(reopened.get("language"), "en")
        self.assertEqual(reopened.get("notation"), "san")
        self.assertEqual(reopened.get("volume"), 37)
        self.assertFalse(reopened.get("sounds"))
        self.assertEqual(path.read_bytes(), persisted)

    def test_pgn_save_as_save_and_reopen_are_byte_stable(self) -> None:
        target = self.root / "Партії з аналізом" / "Моя партія № 1.pgn"
        session = PgnDocumentSession.new_game(
            {
                "Event": "Перевірка шляху",
                "White": "Олена",
                "Black": "Борис",
                "Result": "*",
            }
        )

        saved = session.save_as(target)
        first_bytes = target.read_bytes()
        self.assertEqual(saved.path, str(target.resolve()))
        self.assertIn("Олена".encode("utf-8"), first_bytes)

        session.save()
        self.assertEqual(target.read_bytes(), first_bytes)

        reopened = PgnDocumentSession.open(target)
        self.assertEqual(reopened.copy_pgn(), session.copy_pgn())
        self.assertEqual(
            reopened.workspace.current_game().tags["Event"],
            "Перевірка шляху",
        )
        self.assertFalse(reopened.dirty)

    def test_library_trusted_import_selected_and_filtered_export(self) -> None:
        source = self.root / "Джерела" / "Колекція з пробілами.pgn"
        source.parent.mkdir(parents=True)
        source.write_text(_LIBRARY_PGN, encoding="utf-8", newline="\n")
        opened = open_pgn(source)

        database_path = self.root / "Бібліотека користувача" / "Моя база.acsdb"
        database_path.parent.mkdir(parents=True)
        with AcsDatabase(database_path) as database:
            imported = LibraryImportService(database).import_games(
                opened.games,
                source_name=source.name,
                source_format="pgn",
                source_sha256=opened.source.sha256,
            )
            self.assertEqual(imported.game_count, 2)

            exporter = LibraryExportService(database)
            export_root = self.root / "Експорт бібліотеки"
            export_root.mkdir(parents=True)

            selected_path = export_root / "Вибрані партії.pgn"
            selected = exporter.export_to(
                selected_path,
                LibraryExportRequest.selected([imported.first_game_id]),
            )
            self.assertEqual(selected.game_count, 1)
            selected_opened = open_pgn(selected_path)
            self.assertEqual(selected_opened.total_games, 1)
            self.assertEqual(
                selected_opened.games[0].tags["Event"],
                "Шляхова партія",
            )

            filtered_path = export_root / "Фільтр Олена.pgn"
            filtered = exporter.export_to(
                filtered_path,
                LibraryExportRequest.filtered(GameSearchQuery(player="Олена")),
            )
            self.assertEqual(filtered.game_count, 1)
            filtered_opened = open_pgn(filtered_path)
            self.assertEqual(filtered_opened.total_games, 1)
            self.assertEqual(filtered_opened.games[0].tags["White"], "Олена")

        with AcsDatabase(database_path) as reopened_database:
            page = reopened_database.search_games(player="Олена", limit=20)
            self.assertEqual(len(page), 1)
            self.assertEqual(page[0]["white"], "Олена")

    def test_native_book_open_and_progress_reopen_for_txt_and_epub(self) -> None:
        database_path = self.root / "Книги і база" / "книги.acsdb"
        database_path.parent.mkdir(parents=True)
        database = AcsDatabase(database_path)
        self.addCleanup(database.close)

        analysis = AnalysisService(lambda: None)
        self.addCleanup(analysis.close)
        engine = EngineAssistedWorkflowService(analysis)
        progress = BookProgressStore(
            self.root / "Стан читання" / "прогрес книг.json"
        )

        def build_app() -> Version2Application:
            return Version2Application(
                database,
                progress_store=progress,
                engine_assistance=engine,
                board_dispatch=lambda *_: None,
                board_position_projector=lambda _fen: {"ok": True},
            )

        text_source = self.root / "Книги" / "Український текст з пробілами.txt"
        text_source.parent.mkdir(parents=True)
        text_source.write_text(
            "Перший абзац доступного тексту.\n\nДругий абзац після перезапуску.",
            encoding="utf-8",
            newline="\n",
        )

        app = build_app()
        app.open_book_dialog = lambda: text_source
        app.browser_command("shell", "book.open")
        app.reader.go_to(1)
        text_location = app.reader.location()
        text_key = app.book_key
        app.save_book_progress()

        restarted_text = build_app()
        restarted_text.open_book_dialog = lambda: text_source
        restarted_text.browser_command("shell", "book.open")
        self.assertEqual(restarted_text.book_key, text_key)
        self.assertEqual(restarted_text.reader.location(), text_location)
        self.assertNotIn(
            str(self.root),
            json.dumps(restarted_text.snapshot(), ensure_ascii=False),
        )

        epub_source = self.root / "Книги" / "Навчання EPUB з пробілами.epub"
        epub_source.write_bytes(
            _epub(
                b'''<html lang="uk"><body>
<h1 id="chapter">Accessible EPUB</h1>
<p>Accessible text EPUB.</p>
<p>Text after restore.</p>
</body></html>'''
            )
        )

        restarted_text.open_book_dialog = lambda: epub_source
        restarted_text.browser_command("shell", "book.open")
        restarted_text.reader.go_to(1)
        epub_location = restarted_text.reader.location()
        epub_key = restarted_text.book_key
        restarted_text.save_book_progress()

        restarted_epub = build_app()
        restarted_epub.open_book_dialog = lambda: epub_source
        restarted_epub.browser_command("shell", "book.open")
        self.assertEqual(restarted_epub.book_key, epub_key)
        self.assertEqual(restarted_epub.reader.location(), epub_location)
        self.assertEqual(restarted_epub.reader.document.title, "Unicode Path EPUB")
        rendered = json.dumps(restarted_epub.snapshot(), ensure_ascii=False)
        self.assertNotIn(str(self.root), rendered)
        self.assertNotIn(str(epub_source), rendered)

    def test_local_path_failures_are_redacted_by_shared_presentation_authority(self) -> None:
        destination = self.root / "Партії" / "вже існує.pgn"
        destination.parent.mkdir(parents=True)
        destination.write_text(_LIBRARY_PGN, encoding="utf-8", newline="\n")
        session = PgnDocumentSession.new_game({"Event": "Не перезаписувати"})

        with self.assertRaises(FileExistsError) as caught:
            session.save_as(destination)

        raw = str(caught.exception)
        self.assertIn(str(destination), raw)
        safe = redact_local_paths(raw, "[local path]")
        self.assertNotIn(str(self.root), safe)
        self.assertNotIn(str(destination), safe)
        self.assertIn("[local path]", safe)


if __name__ == "__main__":
    unittest.main()
