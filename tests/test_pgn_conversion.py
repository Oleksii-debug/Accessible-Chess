from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from acs.pgn_conversion import (
    PgnConversionError, convert_pgn, format_conversion_review, main, preview_conversion,
)
from acs.pgn_conversion_windows import run_conversion_job
from acs.pgn_roundtrip import parse_pgn_text
from acs.pgn_service import open_pgn
from acs.gametree import serialize_game
from acs.game_identity import identity_for_game
from acs.book_text_import import import_text_book
from acs.bookdocument import Game
from acs.book_game_content import resolve_book_game
from acs.acsdb import AcsDatabase
from acs.library_import_service import LibraryImportService
from acs.search_service import GameSearchQuery, GameSearchService


RICH = '''[Event "Шахова книга"]
[White "Олексій"]
[Black "Іван"]
[Result "*"]

{Вступ} 1. e4 {План [%clk 0:05:00]} e5 $1 (1... c5 {Захист} 2. Nf3 (2. Nc3) d6) 2. Nf3 *

[Event "Початкова позиція"]
[SetUp "1"]
[FEN "8/8/8/8/8/8/4k3/7K b - - 0 7"]
[Result "*"]

7... Kf3 *
'''


class PgnConversionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "Шахова бібліотека зі пробілами"
        self.root.mkdir()
        self.source = self.root / "Книга.pgn"
        self.destination = self.root / "Книга UTF8.pgn"

    def write(self, text=RICH, codec="utf-8"):
        self.source.write_bytes(text.encode(codec))
        return self.source.read_bytes()

    def test_review_and_conversion_keep_recursive_annotations_and_custom_start(self):
        original = self.write(codec="cp1251")
        plan = preview_conversion(self.source)
        self.assertEqual(plan.encoding, "windows-1251")
        self.assertEqual((plan.summary.games, plan.summary.variations, plan.summary.custom_starts), (2, 2, 1))
        self.assertEqual(plan.summary.comments, 3)
        self.assertEqual(plan.summary.annotations, 1)
        self.assertIn("Олексій", plan.first_game_preview)
        saved = convert_pgn(self.source, self.destination, reviewed_plan=plan)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(saved.sha256, plan.output_sha256)
        self.assertEqual(saved.size, plan.output_bytes)
        self.assertNotIn(b"\r", self.destination.read_bytes())
        before = parse_pgn_text(RICH)
        after = open_pgn(self.destination).games
        self.assertEqual([identity_for_game(g).record_digest for g in before], [identity_for_game(g).record_digest for g in after])

    def test_bom_utf16_both_byte_orders_and_utf8_bom(self):
        for bom, codec, expected in ((b"\xff\xfe", "utf-16-le", "utf-16"), (b"\xfe\xff", "utf-16-be", "utf-16"), (b"\xef\xbb\xbf", "utf-8", "utf-8")):
            with self.subTest(codec=codec):
                self.source.write_bytes(bom + RICH.encode(codec))
                plan = preview_conversion(self.source)
                self.assertEqual(plan.encoding, expected)
                self.assertEqual(plan.summary.games, 2)

    def test_explicit_western_and_legacy_codepages(self):
        for codec, selection, name in (("cp1252", "windows-1252", "José Müller"), ("latin1", "iso-8859-1", "José Müller"), ("cp866", "cp866", "Шахматная книга"), ("koi8-r", "koi8-r", "Шахматная книга"), ("koi8-u", "koi8-u", "Українська книга")):
            with self.subTest(codec=codec):
                text = f'[Event "{name}"]\n[Result "*"]\n\n1. e4 *\n'
                self.write(text, codec)
                plan = preview_conversion(self.source, encoding=selection)
                self.assertIn(name, plan.first_game_preview)

    def test_unknown_auto_encoding_is_not_replaced(self):
        self.source.write_bytes(b'[Event "Jos\xe9"]\n[Result "*"]\n\n1. e4 *\n')
        with self.assertRaises(PgnConversionError) as raised:
            preview_conversion(self.source)
        self.assertEqual(raised.exception.code, "encoding")
        self.assertFalse(self.destination.exists())

    def test_malformed_encoding_and_conflicting_bom_fail_closed(self):
        for raw, encoding in ((b"\xff\xfeA", "auto"), (b"\xff\xfe\0\0", "auto"), (RICH.encode("utf-8"), "utf-16"), (b"\xef\xbb\xbf" + RICH.encode("utf-8"), "windows-1251"), (b"\xff\xfe" + RICH.encode("utf-16-le"), "windows-1252"), (b'[Event "\x98"]\n[Result "*"]\n\n1. e4 *', "windows-1251")):
            with self.subTest(raw=raw[:10], encoding=encoding):
                self.source.write_bytes(raw)
                with self.assertRaises(PgnConversionError) as raised:
                    preview_conversion(self.source, encoding=encoding)
                self.assertEqual(raised.exception.code, "encoding")

    def test_damaged_and_empty_pgn_do_not_get_silently_repaired(self):
        for text in ("", '[Event "A"]\n[Result "*"]\n\n1. e4', '[Event "A"]\n[Event "B"]\n[Result "*"]\n\n1. e4 *', '[Result "*"]\n\n1. e4 {broken *', '[Result "*"]\n\n1. e4 (1. d4 *'):
            with self.subTest(text=text):
                original = self.write(text)
                with self.assertRaises(PgnConversionError):
                    preview_conversion(self.source)
                self.assertEqual(self.source.read_bytes(), original)

    def test_source_changed_since_preview_prevents_publication(self):
        self.write()
        plan = preview_conversion(self.source)
        self.write(RICH.replace("Іван", "Ігор"))
        with self.assertRaises(PgnConversionError) as raised:
            convert_pgn(self.source, self.destination, reviewed_plan=plan)
        self.assertEqual(raised.exception.code, "source_changed")
        self.assertFalse(self.destination.exists())

    def test_same_source_and_existing_destination_are_protected(self):
        original = self.write()
        plan = preview_conversion(self.source)
        with self.assertRaises(PgnConversionError) as raised:
            convert_pgn(self.source, self.source, reviewed_plan=plan)
        self.assertEqual(raised.exception.code, "same_source")
        self.destination.write_bytes(b"keep this")
        with self.assertRaises(PgnConversionError) as raised:
            convert_pgn(self.source, self.destination, reviewed_plan=plan)
        self.assertEqual(raised.exception.code, "destination_exists")
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(self.destination.read_bytes(), b"keep this")

    def test_invalid_destination_extension_is_rejected(self):
        self.write()
        with self.assertRaises(PgnConversionError) as raised:
            convert_pgn(self.source, self.root / "out.cbh", reviewed_plan=preview_conversion(self.source))
        self.assertEqual(raised.exception.code, "destination_format")

    def test_cancellation_during_serialization_leaves_no_partial_file(self):
        self.write()
        plan = preview_conversion(self.source)
        from acs.pgn_service import save_pgn_atomic as real_save
        cancelled = False

        def cancel_after_temp_is_created(*args, **kwargs):
            def games():
                nonlocal cancelled
                iterator = iter(args[1])
                yield next(iterator)
                cancelled = True
                yield from iterator
            return real_save(args[0], games(), **kwargs)

        with patch("acs.pgn_conversion.save_pgn_atomic", side_effect=cancel_after_temp_is_created):
            with self.assertRaises(PgnConversionError) as raised:
                convert_pgn(self.source, self.destination, reviewed_plan=plan, cancel_check=lambda: cancelled)
        self.assertEqual(raised.exception.code, "cancelled")
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_cancellation_after_fsync_still_prevents_publication(self):
        self.write()
        plan = preview_conversion(self.source)
        from acs.pgn_service import save_pgn_atomic as real_save
        cancelled = False

        def cancel_at_pre_publish(*args, **kwargs):
            original_check = kwargs.get("pre_publish_check")
            self.assertIsNotNone(original_check)

            def force_cancel_now():
                nonlocal cancelled
                cancelled = True
                original_check()

            kwargs["pre_publish_check"] = force_cancel_now
            return real_save(*args, **kwargs)

        with patch("acs.pgn_conversion.save_pgn_atomic", side_effect=cancel_at_pre_publish):
            with self.assertRaises(PgnConversionError) as raised:
                convert_pgn(
                    self.source,
                    self.destination,
                    reviewed_plan=plan,
                    cancel_check=lambda: cancelled,
                )

        self.assertEqual(raised.exception.code, "cancelled")
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_review_digest_cannot_be_changed(self):
        self.write()
        plan = preview_conversion(self.source)
        with self.assertRaises(PgnConversionError):
            convert_pgn(self.source, self.destination, reviewed_plan=replace(plan, output_sha256="0" * 64))
        self.assertFalse(self.destination.exists())

    def test_limits_cancellation_and_passive_encoding_are_checked(self):
        self.write()
        with self.assertRaises(PgnConversionError):
            preview_conversion(self.source, max_bytes=10)
        with self.assertRaises(PgnConversionError) as raised:
            preview_conversion(self.source, cancel_check=lambda: True)
        self.assertEqual(raised.exception.code, "cancelled")
        with self.assertRaises(TypeError):
            preview_conversion(self.source, cancel_check=lambda: "yes")
        class ActiveString(str):
            def __eq__(self, other):
                raise AssertionError("encoding hook must not run")
        with self.assertRaises(ValueError):
            preview_conversion(self.source, encoding=ActiveString("auto"))

    def test_public_report_does_not_leak_paths_or_book_text(self):
        self.write()
        plan = preview_conversion(self.source)
        report = json.dumps(plan.public_report(), ensure_ascii=False)
        self.assertNotIn(str(self.root), report)
        self.assertNotIn("Олексій", report)
        self.assertNotIn("План", report)
        self.assertIn("Допустимість", format_conversion_review(plan))
        self.assertIn("Chess legality", format_conversion_review(plan, "en"))

    def test_native_worker_uses_the_same_review_and_writer(self):
        self.write(codec="utf-16")
        plan = run_conversion_job(self.source, "auto", None, None, lambda: False)
        saved = run_conversion_job(self.source, "utf-16", self.destination, plan, lambda: False)
        self.assertEqual(saved.sha256, plan.output_sha256)

    def test_cli_plain_preview_exposes_both_publication_digests(self):
        original = self.write(codec="cp1251")
        plan = preview_conversion(self.source)
        output = io.StringIO()

        with redirect_stdout(output):
            self.assertEqual(main([str(self.source)]), 0)

        review = output.getvalue()
        self.assertIn("SHA-256 джерела: " + hashlib.sha256(original).hexdigest(), review)
        self.assertIn("SHA-256 UTF-8 результату: " + plan.output_sha256, review)
        self.assertNotIn(str(self.root), review)

    def test_cli_preview_review_bound_write_and_stale_digest(self):
        original = self.write(codec="cp1251")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main([str(self.source), "--json"]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["source_sha256"], hashlib.sha256(original).hexdigest())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(
                main([
                    str(self.source),
                    "--json",
                    "--output",
                    str(self.destination),
                    "--expect-sha256",
                    report["source_sha256"],
                    "--expect-output-sha256",
                    report["output_sha256"],
                ]),
                0,
            )
            self.assertEqual(
                main([
                    str(self.source),
                    "--output",
                    str(self.root / "stale.pgn"),
                    "--expect-sha256",
                    "0" * 64,
                    "--expect-output-sha256",
                    report["output_sha256"],
                ]),
                1,
            )
        self.assertFalse((self.root / "stale.pgn").exists())

    def test_cli_publication_is_bound_to_reviewed_decoding_result(self):
        self.source.write_bytes(b'[Event "\xc9"]\n[Result "*"]\n\n1. e4 *\n')
        reviewed = preview_conversion(self.source, encoding="windows-1251")
        self.assertIn("Й", reviewed.first_game_preview)

        output = io.StringIO()
        with redirect_stdout(output):
            result = main([
                str(self.source),
                "--encoding",
                "windows-1252",
                "--json",
                "--output",
                str(self.destination),
                "--expect-sha256",
                reviewed.source.sha256,
                "--expect-output-sha256",
                reviewed.output_sha256,
            ])

        self.assertEqual(result, 1)
        error = json.loads(output.getvalue())
        self.assertEqual(error["error_code"], "review_changed")
        self.assertFalse(self.destination.exists())

    def test_converted_collection_reopens_in_book_and_library(self):
        self.write(codec="cp1251")
        plan = preview_conversion(self.source)
        convert_pgn(self.source, self.destination, reviewed_plan=plan)
        opened = open_pgn(self.destination)
        markdown = "# Шахова збірка\n\n" + "\n".join("```pgn\n" + serialize_game(game) + "\n```\n" for game in opened.games)
        book = import_text_book(markdown, source_name="collection.md", source_format="markdown")
        resolved = [resolve_book_game(block).game for block in book.document.blocks if type(block) is Game]
        self.assertEqual([identity_for_game(g).record_digest for g in opened.games], [identity_for_game(g).record_digest for g in resolved])
        database = AcsDatabase(self.root / "Колекція.acsdb")
        try:
            LibraryImportService(database).import_games(opened.games, source_name="Книга UTF8.pgn", source_format="pgn", source_sha256=opened.source.sha256)
            results = GameSearchService(database).search(GameSearchQuery(player="Олексій"))
            self.assertEqual(len(results.items), 1)
        finally:
            database.close()


if __name__ == "__main__":
    unittest.main()
