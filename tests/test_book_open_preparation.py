from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest

from acs.version2_application import (
    BookOpenCancelled,
    PreparedBookOpen,
    Version2Application,
)


class BookOpenPreparationTests(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "Книга.md"
        source.write_text(
            "# Доступні шахи\n\n"
            "Це локальний семантичний текст для перевірки фонового відкриття.\n\n"
            "## Розділ\n\n"
            "Навігація має залишатися канонічною.\n",
            encoding="utf-8",
        )
        return source

    def test_semantic_preparation_is_safe_off_the_application_ui_thread(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = self._source(Path(raw))
            result: list[object] = []
            errors: list[BaseException] = []

            def worker() -> None:
                try:
                    result.append(Version2Application.prepare_book_open(source))
                except BaseException as exc:  # pragma: no cover - diagnostic capture
                    errors.append(exc)

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(timeout=10)

            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(result), 1)
            prepared = result[0]
            self.assertIs(type(prepared), PreparedBookOpen)
            self.assertTrue(prepared.book_key)
            self.assertIsNone(prepared.document.language)
            self.assertEqual(prepared.warnings, ())
            self.assertIn("Доступні шахи", prepared.document.title)

    def test_cancel_token_reaches_semantic_import_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = self._source(Path(raw))
            calls = 0

            def cancel_after_stable_read() -> bool:
                nonlocal calls
                calls += 1
                # For this small source, calls 1..8 cover the outer checkpoint,
                # the canonical two-pass stable read, and its immediate
                # post-read checkpoint. The next poll is the text importer's
                # own control_checkpoint before semantic parsing.
                return calls >= 9

            with self.assertRaises(BookOpenCancelled):
                Version2Application.prepare_book_open(
                    source,
                    cancel_check=cancel_after_stable_read,
                )

            self.assertGreaterEqual(calls, 9)

    def test_cancel_contract_fails_closed_on_non_boolean_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = self._source(Path(raw))
            with self.assertRaisesRegex(
                TypeError,
                "Book Open cancel_check must return bool",
            ):
                Version2Application.prepare_book_open(
                    source,
                    cancel_check=lambda: 1,
                )

    def test_cancel_before_read_does_not_mutate_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = self._source(Path(raw))
            before = source.read_bytes()

            with self.assertRaises(BookOpenCancelled):
                Version2Application.prepare_book_open(
                    source,
                    cancel_check=lambda: True,
                )

            self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
