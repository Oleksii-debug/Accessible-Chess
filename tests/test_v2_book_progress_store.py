from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import traceback
import unittest
from unittest import mock

from acs.book_progress_store import (
    BOOK_PROGRESS_STORE_SCHEMA_VERSION,
    MAX_BOOK_KEY_CHARS,
    MAX_BOOK_SNAPSHOT_BYTES,
    BookProgressStore,
    BookProgressStoreError,
    BookProgressStoreErrorCode,
)
from acs.bookdocument import BookDocument, Diagram, Heading, Paragraph
from acs.bookreader import BookReader


WHITE_FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"


class BookProgressStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "state" / "book-progress.json"
        self.store = BookProgressStore(self.path)

    @staticmethod
    def original_document(*, source_name: str | None = None) -> BookDocument:
        return BookDocument(
            "Semantic book",
            source_name=source_name,
            blocks=[
                Heading(text="Chapter", level=1, block_id="chapter"),
                Paragraph(text="Introduction", block_id="intro"),
                Diagram(
                    fen=WHITE_FEN,
                    caption="Critical position",
                    alt_text="White king e2; black king h1.",
                    block_id="diagram",
                    source_anchor="chapter-1-diagram",
                ),
                Paragraph(text="After the position", block_id="after"),
            ],
        )

    @staticmethod
    def reordered_document() -> BookDocument:
        return BookDocument(
            "Semantic book revised",
            blocks=[
                Heading(text="Chapter", level=1, block_id="chapter"),
                Paragraph(text="Inserted", block_id="inserted"),
                Paragraph(text="After the position", block_id="after"),
                Diagram(
                    fen=WHITE_FEN,
                    caption="Critical position",
                    alt_text="White king e2; black king h1.",
                    block_id="diagram",
                    source_anchor="chapter-1-diagram",
                ),
                Paragraph(text="Introduction", block_id="intro"),
            ],
        )

    def test_close_reopen_restores_exact_location_and_named_bookmark(self) -> None:
        document = self.original_document()
        reader = BookReader(document)
        reader.go_to(2)
        reader.save_return_point("analysis-return")
        reader.go_to(3)

        saved = self.store.save("library:book-42", reader)
        self.assertEqual(saved["current_target"], "block:after")

        # Simulate application close: discard the original reader and build a
        # fresh BookDocument/BookReader from persisted state only.
        reopened = self.store.restore("library:book-42", self.original_document())
        self.assertEqual(reopened.location().block_id, "after")
        restored = reopened.restore_return_point("analysis-return")
        self.assertEqual(restored.block_id, "diagram")
        self.assertEqual(restored.position_fen, WHITE_FEN)

    def test_reopen_uses_semantic_identity_after_source_preserving_reorder(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(2)
        reader.save_return_point("board-return")
        reader.go_to(3)
        self.store.save("content:stable-id", reader)

        reopened = self.store.restore("content:stable-id", self.reordered_document())
        self.assertEqual(reopened.location().block_id, "after")
        self.assertEqual(reopened.location().index, 2)
        returned = reopened.restore_return_point("board-return")
        self.assertEqual(returned.block_id, "diagram")
        self.assertEqual(returned.index, 3)

    def test_source_path_is_not_persisted(self) -> None:
        private_source = r"C:\Users\Oleksii\Documents\private-book.epub"
        document = self.original_document(source_name=private_source)
        reader = BookReader(document)
        reader.go_to(2)
        self.store.save("source-sha256:012345", reader)

        persisted = self.path.read_text(encoding="utf-8")
        self.assertNotIn("Users", persisted)
        self.assertNotIn("Oleksii", persisted)
        self.assertNotIn("private-book.epub", persisted)
        self.assertNotIn(private_source, persisted)

    def test_multiple_books_are_isolated_and_removal_is_atomic(self) -> None:
        first = BookReader(self.original_document())
        first.go_to(1)
        second = BookReader(self.original_document())
        second.go_to(3)
        self.store.save("book:first", first)
        self.store.save("book:second", second)

        self.assertTrue(self.store.has("book:first"))
        self.assertTrue(self.store.has("book:second"))
        self.assertEqual(self.store.restore("book:first", self.original_document()).index, 1)
        self.assertEqual(self.store.restore("book:second", self.original_document()).index, 3)

        self.assertTrue(self.store.remove("book:first"))
        self.assertFalse(self.store.has("book:first"))
        self.assertTrue(self.store.has("book:second"))
        self.assertFalse(self.store.remove("book:first"))

    def test_missing_entry_does_not_fall_back_to_another_book(self) -> None:
        self.store.save("book:one", BookReader(self.original_document()))
        with self.assertRaisesRegex(LookupError, "No saved reading progress"):
            self.store.restore("book:two", self.original_document())

    def test_corrupt_store_fails_closed_and_save_does_not_overwrite_it(self) -> None:
        self.path.parent.mkdir(parents=True)
        original = b'{"schema_version":1,"entries":'
        self.path.write_bytes(original)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.save("book:one", BookReader(self.original_document()))
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(self.path.read_bytes(), original)

    def test_duplicate_json_object_keys_fail_closed(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            '{"schema_version":1,"schema_version":1,"entries":{}}',
            encoding="utf-8",
        )
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:one")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)

    def test_deeply_nested_progress_json_fails_with_stable_store_error(self) -> None:
        self.path.parent.mkdir(parents=True)
        depth = 5000
        self.path.write_text(
            "[" * depth + "0" + "]" * depth,
            encoding="utf-8",
        )

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:one")

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.CORRUPT_STORE,
        )
        self.assertIsNone(caught.exception.__cause__)

    def test_unknown_or_future_store_schema_fails_closed(self) -> None:
        cases = [
            {"schema_version": 2, "entries": {}},
            {"schema_version": True, "entries": {}},
            {"schema_version": 1, "entries": {}, "future": 1},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(BookProgressStoreError):
                    self.store.has("book:one")

    def test_invalid_book_keys_fail_before_any_file_mutation(self) -> None:
        reader = BookReader(self.original_document())
        bad = [
            "",
            " book",
            "book ",
            "line\nbreak",
            "\ud800",
            "x" * (MAX_BOOK_KEY_CHARS + 1),
        ]
        for key in bad:
            with self.subTest(key=key):
                with self.assertRaises(BookProgressStoreError):
                    self.store.save(key, reader)
        with self.assertRaises(BookProgressStoreError):
            self.store.save(123, reader)  # type: ignore[arg-type]
        self.assertFalse(self.path.exists())

    def test_invalid_unicode_scalar_in_persisted_snapshot_fails_stably(self) -> None:
        payload = {
            "schema_version": BOOK_PROGRESS_STORE_SCHEMA_VERSION,
            "generation": 1,
            "entries": {
                "book:invalid-unicode": {
                    "schema_version": 2,
                    "current_target": "\ud800",
                    "return_points": {},
                    "fallback_digests": {},
                }
            },
        }
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=True),
            encoding="utf-8",
        )

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:invalid-unicode")

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.CORRUPT_STORE,
        )
        self.assertIsNone(caught.exception.__cause__)

    def test_snapshot_resource_limit_is_checked_before_restore(self) -> None:
        huge_target = "x" * (MAX_BOOK_SNAPSHOT_BYTES + 1)
        payload = {
            "schema_version": BOOK_PROGRESS_STORE_SCHEMA_VERSION,
            "entries": {
                "book:huge": {
                    "schema_version": 2,
                    "current_target": huge_target,
                    "return_points": {},
                    "fallback_digests": {},
                }
            },
        }
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:huge")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.RESOURCE_LIMIT)

    def test_missing_primary_read_path_restores_valid_backup_without_mutation(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:read-orphan", reader)
        reader.go_to(3)
        self.store.save("book:read-orphan", reader)

        backup_bytes = self.store.backup_path.read_bytes()
        self.path.unlink()

        self.assertTrue(self.store.has("book:read-orphan"))
        restored = self.store.restore(
            "book:read-orphan",
            self.original_document(),
        )
        self.assertEqual(restored.index, 1)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)

    def test_missing_primary_with_corrupt_backup_fails_closed_on_read(self) -> None:
        self.path.parent.mkdir(parents=True)
        corrupt_backup = b'{"schema_version":2,"generation":'
        self.store.backup_path.write_bytes(corrupt_backup)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:corrupt-orphan")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.backup_path.read_bytes(), corrupt_backup)

    def test_recovery_without_primary_or_backup_remains_a_noop(self) -> None:
        self.assertFalse(self.store.recover_from_backup())
        self.assertFalse(self.path.exists())
        self.assertFalse(self.store.backup_path.exists())

    def test_missing_primary_can_be_explicitly_recovered_from_validated_backup(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:recover-missing", reader)
        reader.go_to(3)
        self.store.save("book:recover-missing", reader)

        backup_bytes = self.store.backup_path.read_bytes()
        backup_revision = self.store.validated_backup_revision(
            "book:recover-missing",
            self.original_document(),
        )
        self.path.unlink()

        self.assertTrue(
            self.store.recover_from_backup(
                expected_backup_revision=backup_revision,
            )
        )
        self.assertEqual(self.path.read_bytes(), backup_bytes)
        reopened = self.store.restore(
            "book:recover-missing",
            self.original_document(),
        )
        self.assertEqual(reopened.index, 1)

    def test_save_does_not_destroy_orphan_backup_when_primary_is_missing(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:orphan", reader)
        reader.go_to(3)
        self.store.save("book:orphan", reader)

        backup_bytes = self.store.backup_path.read_bytes()
        self.path.unlink()

        replacement = BookReader(self.original_document())
        replacement.go_to(2)
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.save("book:new-state", replacement)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)

    def test_save_rechecks_orphan_backup_immediately_before_primary_publication(self) -> None:
        self.path.parent.mkdir(parents=True)
        backup_bytes = b'{"entries":{},"generation":7,"schema_version":2}'
        real_require = self.store._require_no_orphan_backup_unlocked
        checks = 0

        def backup_appears_after_write_stage_check() -> None:
            nonlocal checks
            checks += 1
            real_require()
            if checks == 2:
                self.store.backup_path.write_bytes(backup_bytes)

        with mock.patch.object(
            self.store,
            "_require_no_orphan_backup_unlocked",
            side_effect=backup_appears_after_write_stage_check,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save(
                    "book:late-orphan",
                    BookReader(self.original_document()),
                )

        self.assertEqual(checks, 3)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)

    def test_save_rechecks_orphan_backup_after_temp_fsync_before_replace(self) -> None:
        self.path.parent.mkdir(parents=True)
        backup_bytes = b'{"entries":{},"generation":7,"schema_version":2}'
        real_mkstemp = tempfile.mkstemp
        injected = False

        def backup_appears_during_primary_temp_write(*args, **kwargs):
            nonlocal injected
            descriptor, name = real_mkstemp(*args, **kwargs)
            if kwargs.get("prefix") == f".{self.path.name}.":
                self.store.backup_path.write_bytes(backup_bytes)
                injected = True
            return descriptor, name

        with mock.patch(
            "acs.book_progress_store.tempfile.mkstemp",
            side_effect=backup_appears_during_primary_temp_write,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save(
                    "book:temp-window-orphan",
                    BookReader(self.original_document()),
                )

        self.assertTrue(injected)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)
        self.assertFalse(
            any(
                item.name.startswith(f".{self.path.name}.")
                and item.name.endswith(".tmp")
                for item in self.path.parent.iterdir()
            )
        )

    def test_publish_orphan_guard_requires_exact_boolean(self) -> None:
        self.path.parent.mkdir(parents=True)
        for invalid in (0, 1, None, "", object()):
            with self.subTest(invalid=repr(invalid)):
                with self.assertRaisesRegex(
                    TypeError,
                    "require_no_orphan_backup_before_replace must be a boolean",
                ):
                    self.store._atomic_publish_bytes_unlocked(
                        self.path,
                        b"{}",
                        require_no_orphan_backup_before_replace=invalid,
                    )
        self.assertFalse(self.path.exists())

    def test_missing_primary_recovery_rejects_stale_backup_revision(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:stale-backup", reader)
        reader.go_to(3)
        self.store.save("book:stale-backup", reader)

        expected_revision = self.store.validated_backup_revision(
            "book:stale-backup",
            self.original_document(),
        )
        newer_valid_bytes = self.path.read_bytes()
        self.path.unlink()
        self.store.backup_path.write_bytes(newer_valid_bytes)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.recover_from_backup(
                expected_backup_revision=expected_revision,
            )
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.backup_path.read_bytes(), newer_valid_bytes)

    def test_missing_primary_recovery_never_overwrites_reappeared_primary(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:reappeared", reader)
        reader.go_to(3)
        self.store.save("book:reappeared", reader)

        reappeared_bytes = self.path.read_bytes()
        backup_revision = self.store.validated_backup_revision(
            "book:reappeared",
            self.original_document(),
        )
        self.path.unlink()

        real_read = self.store._read_raw_file_unlocked
        primary_reads = 0

        def reappearing_read(
            path: Path,
            *,
            missing_ok: bool,
        ) -> bytes | None:
            nonlocal primary_reads
            if path == self.path:
                primary_reads += 1
                if primary_reads == 2:
                    self.path.write_bytes(reappeared_bytes)
            return real_read(path, missing_ok=missing_ok)

        with mock.patch.object(
            self.store,
            "_read_raw_file_unlocked",
            side_effect=reappearing_read,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.recover_from_backup(
                    expected_backup_revision=backup_revision,
                )
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), reappeared_bytes)

    def test_remove_does_not_report_missing_when_orphan_backup_contains_book(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:remove-orphan", reader)
        reader.go_to(3)
        self.store.save("book:remove-orphan", reader)

        backup_bytes = self.store.backup_path.read_bytes()
        self.path.unlink()

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.remove("book:remove-orphan")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)

    def test_future_schema_orphan_backup_is_preserved_and_never_downgraded(self) -> None:
        self.path.parent.mkdir(parents=True)
        future_backup = b'{"entries":{},"generation":9,"schema_version":999}'
        self.store.backup_path.write_bytes(future_backup)

        with self.assertRaises(BookProgressStoreError) as read_error:
            self.store.has("book:future")
        self.assertEqual(
            read_error.exception.code,
            BookProgressStoreErrorCode.UNSUPPORTED_SCHEMA,
        )

        with self.assertRaises(BookProgressStoreError) as save_error:
            self.store.save("book:new", BookReader(self.original_document()))
        self.assertEqual(
            save_error.exception.code,
            BookProgressStoreErrorCode.UNSUPPORTED_SCHEMA,
        )
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.backup_path.read_bytes(), future_backup)

    def test_corrupt_orphan_backup_is_preserved_instead_of_erased_by_save(self) -> None:
        self.path.parent.mkdir(parents=True)
        corrupt_backup = b'{"schema_version":2,"generation":'
        self.store.backup_path.write_bytes(corrupt_backup)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.save("book:new", BookReader(self.original_document()))
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.backup_path.read_bytes(), corrupt_backup)

    def test_failed_atomic_replace_preserves_previous_valid_snapshot(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:atomic", reader)
        original_bytes = self.path.read_bytes()

        reader.go_to(3)
        private_failure = OSError(5, "replace failed", str(self.path))
        with mock.patch(
            "acs.book_progress_store.os.replace",
            side_effect=private_failure,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:atomic", reader)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)
        self.assertIsNone(caught.exception.__cause__)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn(str(self.path), rendered)
        self.assertNotIn(self.tempdir.name, rendered)
        self.assertEqual(self.path.read_bytes(), original_bytes)
        self.assertEqual(self.store.restore("book:atomic", self.original_document()).index, 1)

    @unittest.skipIf(os.name == "nt", "Windows symlink creation requires environment-specific privileges")
    def test_symlink_store_is_rejected(self) -> None:
        real = Path(self.tempdir.name) / "real.json"
        real.write_text('{"schema_version":1,"entries":{}}', encoding="utf-8")
        self.path.parent.mkdir(parents=True)
        self.path.symlink_to(real)
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:one")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)

    def test_lock_file_replacement_between_lstat_and_open_fails_closed(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.store._lock_path.write_bytes(b"\0")
        replacement = self.store._lock_path.with_name("replacement.lock")
        replacement.write_bytes(b"\0")

        real_open = os.open
        swapped = False

        def replacing_open(path: object, flags: int, mode: int = 0o777) -> int:
            nonlocal swapped
            if not swapped and os.fspath(path) == os.fspath(self.store._lock_path):
                swapped = True
                os.replace(replacement, self.store._lock_path)
            return real_open(path, flags, mode)

        with mock.patch("acs.book_progress_store.os.open", side_effect=replacing_open):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)
        self.assertFalse(self.path.exists())

    def test_lock_path_identity_is_rechecked_after_os_lock_acquisition(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.store._lock_path.write_bytes(b"\0")
        replacement = self.store._lock_path.with_name("replacement-after-lock.lock")
        replacement.write_bytes(b"\0")

        real_lstat = os.lstat
        lock_lstats = 0
        replacement_metadata = real_lstat(replacement)

        def drifting_lstat(path: object) -> os.stat_result:
            nonlocal lock_lstats
            if os.fspath(path) == os.fspath(self.store._lock_path):
                lock_lstats += 1
                if lock_lstats == 4:
                    return replacement_metadata
            return real_lstat(path)

        with mock.patch("acs.book_progress_store.os.lstat", side_effect=drifting_lstat):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)
        self.assertFalse(self.path.exists())

    def test_reads_do_not_reopen_path_after_file_identity_validation(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"schema_version":1,"entries":{}}', encoding="utf-8")

        with mock.patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("validated progress file must be read by descriptor"),
        ):
            self.assertFalse(self.store.has("book:one"))

    def test_regular_file_replacement_between_lstat_and_open_fails_closed(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"schema_version":1,"entries":{}}', encoding="utf-8")
        replacement = self.path.with_name("replacement.json")
        replacement.write_text('{"schema_version":1,"entries":{"book:one":{}}}', encoding="utf-8")

        real_open = os.open
        swapped = False

        def replacing_open(path: object, flags: int, mode: int = 0o777) -> int:
            nonlocal swapped
            if not swapped and os.fspath(path) == os.fspath(self.path):
                swapped = True
                os.replace(replacement, self.path)
            return real_open(path, flags, mode)

        with mock.patch("acs.book_progress_store.os.open", side_effect=replacing_open):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)

    def test_regular_file_replacement_during_descriptor_read_fails_closed(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"schema_version":1,"entries":{}}', encoding="utf-8")
        replacement = self.path.with_name("replacement-after-open.json")
        replacement.write_text('{"schema_version":1,"entries":{}}', encoding="utf-8")

        real_lstat = os.lstat
        target_lstats = 0

        def replacing_lstat(path: object) -> os.stat_result:
            nonlocal target_lstats
            if os.fspath(path) == os.fspath(self.path):
                target_lstats += 1
                if target_lstats == 3:
                    os.replace(replacement, self.path)
            return real_lstat(path)

        with mock.patch("acs.book_progress_store.os.lstat", side_effect=replacing_lstat):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)

    @unittest.skipIf(os.name == "nt", "Windows symlink creation requires environment-specific privileges")
    def test_symlink_swap_between_lstat_and_open_fails_closed(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"schema_version":1,"entries":{}}', encoding="utf-8")
        outside = self.path.with_name("outside.json")
        outside.write_text('{"schema_version":1,"entries":{}}', encoding="utf-8")

        real_open = os.open
        swapped = False

        def replacing_open(path: object, flags: int, mode: int = 0o777) -> int:
            nonlocal swapped
            if not swapped and os.fspath(path) == os.fspath(self.path):
                swapped = True
                self.path.unlink()
                self.path.symlink_to(outside)
            return real_open(path, flags, mode)

        with mock.patch("acs.book_progress_store.os.open", side_effect=replacing_open):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)

    def test_post_commit_lock_close_failure_does_not_report_save_failure(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(2)

        real_open_lock = self.store._open_lock_descriptor
        real_close = os.close
        lock_descriptor = None

        def capture_lock_descriptor() -> int:
            nonlocal lock_descriptor
            lock_descriptor = real_open_lock()
            return lock_descriptor

        def close_then_report_failure(descriptor: int) -> None:
            real_close(descriptor)
            if descriptor == lock_descriptor:
                raise OSError("late lock close failure")

        with mock.patch.object(
            self.store,
            "_open_lock_descriptor",
            side_effect=capture_lock_descriptor,
        ), mock.patch(
            "acs.book_progress_store.os.close",
            side_effect=close_then_report_failure,
        ):
            saved = self.store.save("book:post-commit-close", reader)

        self.assertEqual(saved["current_target"], "block:diagram")
        self.assertTrue(self.path.exists())
        restored = self.store.restore(
            "book:post-commit-close",
            self.original_document(),
        )
        self.assertEqual(restored.location().block_id, "diagram")

    def test_storage_errors_do_not_put_local_path_in_exception_message(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"not json")
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:one")
        message = str(caught.exception)
        self.assertNotIn(str(self.path), message)
        self.assertNotIn(self.tempdir.name, message)
        self.assertIsNone(caught.exception.__cause__)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn(str(self.path), rendered)
        self.assertNotIn(self.tempdir.name, rendered)


if __name__ == "__main__":
    unittest.main()
