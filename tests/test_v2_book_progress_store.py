from __future__ import annotations

import hashlib
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
    MAX_BOOK_PROGRESS_ENTRIES,
    MAX_BOOK_PROGRESS_JSON_KEY_CHARS,
    MAX_BOOK_PROGRESS_STORE_BYTES,
    MAX_BOOK_SNAPSHOT_BYTES,
    BookProgressStore,
    BookProgressStoreError,
    BookProgressStoreErrorCode,
    _snapshot_copy,
    _sync_published_path,
    _validate_payload,
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

    def test_active_mapping_ingress_is_rejected_without_executing_hooks(self) -> None:
        class ActiveMapping(dict):
            def __init__(self, *args, **kwargs) -> None:
                dict.__init__(self, *args, **kwargs)
                self.touched = False

            def _touch(self):
                self.touched = True
                raise AssertionError("active mapping hook executed")

            def __iter__(self):
                return self._touch()

            def __len__(self):
                return self._touch()

            def __contains__(self, key):
                return self._touch()

            def __getitem__(self, key):
                return self._touch()

            def items(self):
                return self._touch()

        snapshot = ActiveMapping(
            {
                "schema_version": 2,
                "current_target": "block:intro",
                "return_points": {},
                "fallback_digests": {},
            }
        )
        with self.assertRaises(BookProgressStoreError) as snapshot_error:
            _snapshot_copy(snapshot)
        self.assertEqual(
            snapshot_error.exception.code,
            BookProgressStoreErrorCode.CORRUPT_STORE,
        )
        self.assertFalse(snapshot.touched)

        root = ActiveMapping(
            {"schema_version": 2, "generation": 0, "entries": {}}
        )
        with self.assertRaises(BookProgressStoreError) as root_error:
            _validate_payload(root)
        self.assertEqual(
            root_error.exception.code,
            BookProgressStoreErrorCode.CORRUPT_STORE,
        )
        self.assertFalse(root.touched)

        entries = ActiveMapping({})
        with self.assertRaises(BookProgressStoreError) as entries_error:
            _validate_payload(
                {"schema_version": 2, "generation": 0, "entries": entries}
            )
        self.assertEqual(
            entries_error.exception.code,
            BookProgressStoreErrorCode.CORRUPT_STORE,
        )
        self.assertFalse(entries.touched)

    def test_json_object_member_count_is_bounded_before_hashing(self) -> None:
        self.path.parent.mkdir(parents=True)
        entries = ",".join(
            f'"book:{index}":{{}}'
            for index in range(MAX_BOOK_PROGRESS_ENTRIES + 1)
        )
        raw = (
            '{"schema_version":2,"generation":0,"entries":{'
            + entries
            + '}}'
        ).encode("utf-8")
        self.assertLess(len(raw), MAX_BOOK_PROGRESS_STORE_BYTES)
        self.path.write_bytes(raw)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:any")

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.RESOURCE_LIMIT)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_oversized_json_integer_uses_stable_corrupt_store_error(self) -> None:
        self.path.parent.mkdir(parents=True)
        raw = (
            '{"schema_version":2,"generation":'
            + ("9" * 5000)
            + ',"entries":{}}'
        ).encode("utf-8")
        self.assertLess(len(raw), MAX_BOOK_PROGRESS_STORE_BYTES)
        self.path.write_bytes(raw)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:oversized-integer")

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(self.path.read_bytes(), raw)

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

    def test_oversized_json_object_key_is_bounded_before_duplicate_detection(self) -> None:
        self.path.parent.mkdir(parents=True)
        oversized_key = "x" * (MAX_BOOK_PROGRESS_JSON_KEY_CHARS + 1)
        original = (
            '{"schema_version":2,"generation":0,"entries":{},"'
            + oversized_key
            + '":0}'
        ).encode("utf-8")
        self.path.write_bytes(original)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:one")

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.RESOURCE_LIMIT,
        )
        self.assertEqual(self.path.read_bytes(), original)

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

    def test_invalid_configured_storage_paths_fail_before_filesystem_mutation(self) -> None:
        root_path = Path(Path.cwd().anchor)
        for invalid in ("", "\x00", root_path):
            with self.subTest(invalid=repr(invalid)):
                with self.assertRaises(BookProgressStoreError) as caught:
                    BookProgressStore(invalid)
                self.assertEqual(
                    caught.exception.code,
                    BookProgressStoreErrorCode.INVALID_ARGUMENT,
                )

    def test_bytes_storage_path_is_rejected_as_non_text(self) -> None:
        with self.assertRaises(TypeError):
            BookProgressStore(os.fsencode(self.path))

    def test_storage_path_collapses_lexical_parent_segments_at_construction(self) -> None:
        origin = Path(self.tempdir.name) / "lexical-origin"
        (origin / "pivot").mkdir(parents=True)
        previous_cwd = Path.cwd()
        try:
            os.chdir(origin)
            store = BookProgressStore(Path("pivot") / ".." / "book-progress.json")
        finally:
            os.chdir(previous_cwd)

        self.assertEqual(store.path, origin / "book-progress.json")

    @unittest.skipIf(
        os.name == "nt",
        "Windows symlink creation requires environment-specific privileges",
    )
    def test_symlink_parent_pivot_cannot_split_lock_and_data_authority(self) -> None:
        origin = Path(self.tempdir.name) / "pivot-origin"
        outside = Path(self.tempdir.name) / "pivot-outside"
        nested = outside / "nested"
        origin.mkdir()
        nested.mkdir(parents=True)
        (origin / "pivot").symlink_to(nested, target_is_directory=True)
        previous_cwd = Path.cwd()
        try:
            os.chdir(origin)
            store = BookProgressStore(Path("pivot") / ".." / "book-progress.json")
            reader = BookReader(self.original_document())
            store.save("book:pivot", reader)
        finally:
            os.chdir(previous_cwd)

        self.assertEqual(store.path, origin / "book-progress.json")
        self.assertTrue((origin / "book-progress.json").is_file())
        self.assertTrue((origin / "book-progress.json.lock").is_file())
        self.assertFalse((outside / "book-progress.json").exists())
        self.assertFalse((outside / "book-progress.json.lock").exists())

    def test_relative_storage_path_is_bound_before_working_directory_changes(self) -> None:
        origin = Path(self.tempdir.name) / "cwd-origin"
        destination = Path(self.tempdir.name) / "cwd-destination"
        origin.mkdir()
        destination.mkdir()
        previous_cwd = Path.cwd()
        try:
            os.chdir(origin)
            relative_path = Path("relative-state") / "book-progress.json"
            store = BookProgressStore(relative_path)
            bound_path = origin / relative_path
            self.assertEqual(store.path, bound_path)

            os.chdir(destination)
            reader = BookReader(self.original_document())
            reader.go_to(1)
            store.save("book:cwd-bound", reader)
        finally:
            os.chdir(previous_cwd)

        self.assertTrue(bound_path.is_file())
        self.assertTrue(bound_path.with_name(bound_path.name + ".lock").is_file())
        self.assertFalse((destination / relative_path).exists())

    @unittest.skipIf(
        os.name == "nt",
        "Windows symlink creation requires environment-specific privileges",
    )
    def test_symlinked_storage_directory_fails_closed_before_lock_or_progress_write(self) -> None:
        outside = Path(self.tempdir.name) / "outside-progress-directory"
        outside.mkdir()
        self.path.parent.symlink_to(outside, target_is_directory=True)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.save(
                "book:symlinked-parent",
                BookReader(self.original_document()),
            )

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertFalse((outside / self.path.name).exists())
        self.assertFalse((outside / f"{self.path.name}.lock").exists())
        self.assertFalse((outside / f"{self.path.name}.bak").exists())

    def test_storage_directory_swap_before_lock_open_fails_closed(self) -> None:
        self.path.parent.mkdir(parents=True)
        displaced = Path(self.tempdir.name) / "state-before-lock-swap"
        original_open = self.store._open_lock_descriptor
        swapped = False

        def swap_then_open(*, expected_directory_identity=None):
            nonlocal swapped
            if not swapped:
                self.path.parent.rename(displaced)
                self.path.parent.mkdir()
                swapped = True
            return original_open(
                expected_directory_identity=expected_directory_identity
            )

        with mock.patch.object(
            self.store,
            "_open_lock_descriptor",
            side_effect=swap_then_open,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save(
                    "book:directory-swap-before-lock",
                    BookReader(self.original_document()),
                )

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertFalse(self.path.exists())
        self.assertFalse(self.store.backup_path.exists())
        self.assertFalse(self.store._lock_path.exists())
        self.assertTrue(displaced.is_dir())

    @unittest.skipIf(
        os.name == "nt",
        "renaming a directory that contains the open lock is not portable on Windows",
    )
    def test_storage_directory_swap_during_temp_creation_fails_before_publication(self) -> None:
        self.path.parent.mkdir(parents=True)
        displaced = Path(self.tempdir.name) / "state-during-publish-swap"
        real_mkstemp = tempfile.mkstemp
        swapped = False

        def swap_then_create_temp(*args, **kwargs):
            nonlocal swapped
            if not swapped:
                self.path.parent.rename(displaced)
                self.path.parent.mkdir()
                swapped = True
            return real_mkstemp(*args, **kwargs)

        with mock.patch(
            "acs.book_progress_store.tempfile.mkstemp",
            side_effect=swap_then_create_temp,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save(
                    "book:directory-swap-during-publish",
                    BookReader(self.original_document()),
                )

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertFalse(self.path.exists())
        self.assertFalse(self.store.backup_path.exists())
        self.assertFalse(self.store._lock_path.exists())
        self.assertEqual(
            [],
            [
                item.name
                for item in self.path.parent.iterdir()
                if item.name.startswith(f".{self.path.name}.")
            ],
        )
        self.assertTrue((displaced / f"{self.path.name}.lock").exists())

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

    def test_semantically_malformed_persisted_snapshot_fails_before_has(self) -> None:
        valid = {
            "schema_version": 2,
            "current_target": "block:intro",
            "return_points": {},
            "fallback_digests": {},
        }
        cases = (
            ("snapshot-schema", {**valid, "schema_version": 999}),
            ("current-target-type", {**valid, "current_target": 7}),
            ("return-points-type", {**valid, "return_points": []}),
            (
                "fallback-digest-format",
                {
                    **valid,
                    "current_target": "index:0",
                    "fallback_digests": {"index:0": "not-a-digest"},
                },
            ),
            (
                "missing-index-fallback-binding",
                {
                    **valid,
                    "current_target": "index:0",
                    "fallback_digests": {},
                },
            ),
        )
        for label, snapshot in cases:
            with self.subTest(label=label):
                payload = {
                    "schema_version": BOOK_PROGRESS_STORE_SCHEMA_VERSION,
                    "generation": 1,
                    "entries": {"book:malformed": snapshot},
                }
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(payload), encoding="utf-8")

                with self.assertRaises(BookProgressStoreError) as caught:
                    self.store.has("book:malformed")

                self.assertEqual(
                    caught.exception.code,
                    BookProgressStoreErrorCode.CORRUPT_STORE,
                )

    def test_save_does_not_republish_semantically_malformed_existing_snapshot(self) -> None:
        payload = {
            "schema_version": BOOK_PROGRESS_STORE_SCHEMA_VERSION,
            "generation": 7,
            "entries": {
                "book:malformed": {
                    "schema_version": 999,
                    "current_target": "block:intro",
                    "return_points": {},
                    "fallback_digests": {},
                }
            },
        }
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        before = self.path.read_bytes()

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.save(
                "book:other",
                BookReader(self.original_document()),
            )

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.CORRUPT_STORE,
        )
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.store.backup_path.exists())

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

    def test_missing_primary_empty_fallback_rechecks_primary_after_backup_read(self) -> None:
        self.path.parent.mkdir(parents=True)
        primary_bytes = b'{"entries":{},"generation":7,"schema_version":2}'
        real_read = self.store._read_raw_file_unlocked
        injected = False

        def primary_appears_after_missing_backup_read(
            path: Path,
            *,
            missing_ok: bool,
        ) -> bytes | None:
            nonlocal injected
            raw = real_read(path, missing_ok=missing_ok)
            if (
                not injected
                and Path(path) == self.store.backup_path
                and raw is None
            ):
                self.path.write_bytes(primary_bytes)
                injected = True
            return raw

        with mock.patch.object(
            self.store,
            "_read_raw_file_unlocked",
            side_effect=primary_appears_after_missing_backup_read,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:empty-pair-race")

        self.assertTrue(injected)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)
        self.assertEqual(self.path.read_bytes(), primary_bytes)
        self.assertFalse(self.store.backup_path.exists())

    def test_missing_primary_empty_fallback_rechecks_backup_after_backup_read(self) -> None:
        self.path.parent.mkdir(parents=True)
        backup_bytes = b'{"entries":{},"generation":5,"schema_version":2}'
        real_read = self.store._read_raw_file_unlocked
        injected = False

        def backup_appears_after_missing_backup_read(
            path: Path,
            *,
            missing_ok: bool,
        ) -> bytes | None:
            nonlocal injected
            raw = real_read(path, missing_ok=missing_ok)
            if (
                not injected
                and Path(path) == self.store.backup_path
                and raw is None
            ):
                self.store.backup_path.write_bytes(backup_bytes)
                injected = True
            return raw

        with mock.patch.object(
            self.store,
            "_read_raw_file_unlocked",
            side_effect=backup_appears_after_missing_backup_read,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:empty-backup-race")

        self.assertTrue(injected)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)

    def test_backup_fallback_rejects_same_bytes_backup_inode_replacement(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:backup-inode-race", reader)
        reader.go_to(3)
        self.store.save("book:backup-inode-race", reader)

        backup_bytes = self.store.backup_path.read_bytes()
        self.path.unlink()
        real_primary_check = self.store._require_recovery_primary_unchanged_unlocked
        injected = False

        def replace_backup_before_primary_recheck(
            expected_identity: os.stat_result | None,
            expected_raw: bytes | None,
        ) -> None:
            nonlocal injected
            if not injected:
                replacement = self.store.backup_path.with_name(
                    "same-byte-backup-fallback-replacement.json"
                )
                replacement.write_bytes(backup_bytes)
                os.replace(replacement, self.store.backup_path)
                injected = True
            real_primary_check(expected_identity, expected_raw)

        with mock.patch.object(
            self.store,
            "_require_recovery_primary_unchanged_unlocked",
            side_effect=replace_backup_before_primary_recheck,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.restore(
                    "book:backup-inode-race",
                    self.original_document(),
                )

        self.assertTrue(injected)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)

    def test_missing_primary_backup_fallback_rechecks_primary_after_backup_read(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:recovery-read-race", reader)
        reader.go_to(3)
        self.store.save("book:recovery-read-race", reader)

        newer_primary = self.path.read_bytes()
        backup_bytes = self.store.backup_path.read_bytes()
        self.path.unlink()
        real_read = self.store._read_raw_file_unlocked
        injected = False

        def recreate_primary_after_backup_read(
            path: Path,
            *,
            missing_ok: bool,
        ) -> bytes | None:
            nonlocal injected
            raw = real_read(path, missing_ok=missing_ok)
            if (
                not injected
                and Path(path) == self.store.backup_path
                and raw is not None
            ):
                injected = True
                self.path.write_bytes(newer_primary)
            return raw

        with mock.patch.object(
            self.store,
            "_read_raw_file_unlocked",
            side_effect=recreate_primary_after_backup_read,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:recovery-read-race")

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertEqual(self.path.read_bytes(), newer_primary)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)

    def test_corrupt_primary_missing_backup_preserves_primary_corruption_error(self) -> None:
        self.path.parent.mkdir(parents=True)
        corrupt_primary = b'{"schema_version":2,"generation":'
        self.path.write_bytes(corrupt_primary)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:corrupt-no-backup")

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.CORRUPT_STORE,
        )
        self.assertEqual(self.path.read_bytes(), corrupt_primary)
        self.assertFalse(self.store.backup_path.exists())

    def test_corrupt_primary_fallback_rejects_same_bytes_primary_inode_replacement(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:primary-inode-race", reader)
        reader.go_to(3)
        self.store.save("book:primary-inode-race", reader)

        corrupt_primary = b'{"schema_version":2,"generation":'
        self.path.write_bytes(corrupt_primary)
        backup_bytes = self.store.backup_path.read_bytes()
        real_read = self.store._read_raw_file_unlocked
        injected = False

        def replace_primary_with_same_bytes_after_backup_read(
            path: Path,
            *,
            missing_ok: bool,
        ) -> bytes | None:
            nonlocal injected
            raw = real_read(path, missing_ok=missing_ok)
            if (
                not injected
                and Path(path) == self.store.backup_path
                and raw is not None
            ):
                replacement = self.path.with_name(
                    "same-byte-primary-fallback-replacement.json"
                )
                replacement.write_bytes(corrupt_primary)
                os.replace(replacement, self.path)
                injected = True
            return raw

        with mock.patch.object(
            self.store,
            "_read_raw_file_unlocked",
            side_effect=replace_primary_with_same_bytes_after_backup_read,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.restore(
                    "book:primary-inode-race",
                    self.original_document(),
                )

        self.assertTrue(injected)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)
        self.assertEqual(self.path.read_bytes(), corrupt_primary)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)

    def test_corrupt_primary_backup_fallback_rechecks_primary_after_backup_read(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:recovery-corrupt-race", reader)
        reader.go_to(3)
        self.store.save("book:recovery-corrupt-race", reader)

        newer_primary = self.path.read_bytes()
        backup_bytes = self.store.backup_path.read_bytes()
        self.path.write_bytes(b'{"schema_version":2,"generation":')
        real_read = self.store._read_raw_file_unlocked
        injected = False

        def replace_corrupt_primary_after_backup_read(
            path: Path,
            *,
            missing_ok: bool,
        ) -> bytes | None:
            nonlocal injected
            raw = real_read(path, missing_ok=missing_ok)
            if (
                not injected
                and Path(path) == self.store.backup_path
                and raw is not None
            ):
                injected = True
                self.path.write_bytes(newer_primary)
            return raw

        with mock.patch.object(
            self.store,
            "_read_raw_file_unlocked",
            side_effect=replace_corrupt_primary_after_backup_read,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.restore(
                    "book:recovery-corrupt-race",
                    self.original_document(),
                )

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertEqual(self.path.read_bytes(), newer_primary)
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

    def test_recovery_pair_validation_reports_stale_if_primary_changes_during_backup_validation(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:validation-race", reader)
        reader.go_to(3)
        self.store.save("book:validation-race", reader)

        valid_primary = self.path.read_bytes()
        backup_bytes = self.store.backup_path.read_bytes()
        self.path.write_bytes(b'{"schema_version":2,"generation":')
        real_read_state = self.store._read_state_unlocked
        injected = False

        def read_state_and_replace_primary(path: Path, *, missing_ok: bool):
            nonlocal injected
            result = real_read_state(path, missing_ok=missing_ok)
            if Path(path) == self.store.backup_path and not injected:
                self.path.write_bytes(valid_primary)
                injected = True
            return result

        with mock.patch.object(
            self.store,
            "_read_state_unlocked",
            side_effect=read_state_and_replace_primary,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.validated_recovery_revisions(
                    "book:validation-race",
                    self.original_document(),
                )

        self.assertTrue(injected)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), valid_primary)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)

    def test_recovery_pair_rejects_different_corrupt_primary_after_confirmation(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:primary-confirmation-race", reader)
        reader.go_to(3)
        self.store.save("book:primary-confirmation-race", reader)

        corrupt_primary = b'{"schema_version":2,"generation":'
        self.path.write_bytes(corrupt_primary)
        backup_bytes = self.store.backup_path.read_bytes()
        primary_revision, backup_revision = self.store.validated_recovery_revisions(
            "book:primary-confirmation-race",
            self.original_document(),
        )
        self.assertIsNotNone(primary_revision)

        changed_corrupt_primary = b'{"schema_version":2,"entries":'
        self.path.write_bytes(changed_corrupt_primary)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.recover_from_backup(
                expected_backup_revision=backup_revision,
                expected_primary_revision=primary_revision,
            )

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), changed_corrupt_primary)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)

    def test_recovery_pair_rejects_primary_appearance_after_missing_validation(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:missing-confirmation-race", reader)
        reader.go_to(3)
        self.store.save("book:missing-confirmation-race", reader)

        self.path.unlink()
        backup_bytes = self.store.backup_path.read_bytes()
        primary_revision, backup_revision = self.store.validated_recovery_revisions(
            "book:missing-confirmation-race",
            self.original_document(),
        )
        self.assertIsNone(primary_revision)

        appeared_corrupt_primary = b'{"schema_version":2,"generation":'
        self.path.write_bytes(appeared_corrupt_primary)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.recover_from_backup(
                expected_backup_revision=backup_revision,
                expected_primary_revision=primary_revision,
            )

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), appeared_corrupt_primary)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)

    def test_recovery_pair_validation_rejects_already_valid_primary(self) -> None:
        reader = BookReader(self.original_document())
        self.store.save("book:valid-primary-pair", reader)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.validated_recovery_revisions(
                "book:valid-primary-pair",
                self.original_document(),
            )

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)

    def test_explicit_recovery_rejects_invalid_primary_revision_token(self) -> None:
        for invalid in ("", "not-a-revision", "A" * 64, "0" * 63, 7):
            with self.subTest(invalid=invalid):
                with self.assertRaises(BookProgressStoreError) as caught:
                    self.store.recover_from_backup(
                        expected_primary_revision=invalid,
                    )
                self.assertEqual(
                    caught.exception.code,
                    BookProgressStoreErrorCode.INVALID_ARGUMENT,
                )

    def test_revision_bound_missing_primary_recovery_rejects_disappeared_backup(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:backup-disappears-missing", reader)
        reader.go_to(3)
        self.store.save("book:backup-disappears-missing", reader)

        self.path.unlink()
        primary_revision, backup_revision = self.store.validated_recovery_revisions(
            "book:backup-disappears-missing",
            self.original_document(),
        )
        self.assertIsNone(primary_revision)
        self.store.backup_path.unlink()

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.recover_from_backup(
                expected_backup_revision=backup_revision,
                expected_primary_revision=primary_revision,
            )

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.store.backup_path.exists())

    def test_revision_bound_recovery_normalizes_corrupt_backup_drift_as_stale(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:backup-corrupt-after-confirm", reader)
        reader.go_to(3)
        self.store.save("book:backup-corrupt-after-confirm", reader)

        corrupt_primary = b'{"schema_version":2,"generation":'
        self.path.write_bytes(corrupt_primary)
        primary_revision, backup_revision = self.store.validated_recovery_revisions(
            "book:backup-corrupt-after-confirm",
            self.original_document(),
        )
        changed_backup = b'{"schema_version":2,"entries":'
        self.store.backup_path.write_bytes(changed_backup)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.recover_from_backup(
                expected_backup_revision=backup_revision,
                expected_primary_revision=primary_revision,
            )

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), corrupt_primary)
        self.assertEqual(self.store.backup_path.read_bytes(), changed_backup)

    def test_revision_bound_corrupt_primary_recovery_rejects_disappeared_backup(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:backup-disappears-corrupt", reader)
        reader.go_to(3)
        self.store.save("book:backup-disappears-corrupt", reader)

        corrupt_primary = b'{"schema_version":2,"generation":'
        self.path.write_bytes(corrupt_primary)
        primary_revision, backup_revision = self.store.validated_recovery_revisions(
            "book:backup-disappears-corrupt",
            self.original_document(),
        )
        self.assertIsNotNone(primary_revision)
        self.store.backup_path.unlink()

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.recover_from_backup(
                expected_backup_revision=backup_revision,
                expected_primary_revision=primary_revision,
            )

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), corrupt_primary)
        self.assertFalse(self.store.backup_path.exists())

    def test_primary_only_bound_recovery_with_valid_primary_is_stale(self) -> None:
        reader = BookReader(self.original_document())
        self.store.save("book:primary-only-bound", reader)
        primary_bytes = self.path.read_bytes()
        primary_revision = hashlib.sha256(primary_bytes).hexdigest()

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.recover_from_backup(
                expected_primary_revision=primary_revision,
            )

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), primary_bytes)

    def test_revision_bound_recovery_rejects_primary_repaired_during_confirmation(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:confirmation-race", reader)
        reader.go_to(3)
        self.store.save("book:confirmation-race", reader)

        valid_primary = self.path.read_bytes()
        backup_bytes = self.store.backup_path.read_bytes()
        self.path.write_bytes(b'{"schema_version":2,"generation":')
        backup_revision = self.store.validated_backup_revision(
            "book:confirmation-race",
            self.original_document(),
        )

        replacement = self.path.with_name("externally-repaired-primary.json")
        replacement.write_bytes(valid_primary)
        os.replace(replacement, self.path)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.recover_from_backup(
                expected_backup_revision=backup_revision,
            )

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), valid_primary)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)

    def test_unbound_recovery_with_valid_primary_retains_historical_noop(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(2)
        self.store.save("book:recovery-noop", reader)
        primary_bytes = self.path.read_bytes()

        self.assertFalse(self.store.recover_from_backup())
        self.assertEqual(self.path.read_bytes(), primary_bytes)

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

    def test_first_save_backup_appearance_after_primary_replace_reports_durability_unknown(self) -> None:
        backup_bytes = b'{"entries":{},"generation":7,"schema_version":2}'
        real_replace = __import__(
            "acs.book_progress_store",
            fromlist=["_replace_published_path"],
        )._replace_published_path
        injected = False

        def publish_primary_then_create_backup(source: Path, destination: Path) -> None:
            nonlocal injected
            real_replace(source, destination)
            if Path(destination) == self.path and not injected:
                self.store.backup_path.write_bytes(backup_bytes)
                injected = True

        with mock.patch(
            "acs.book_progress_store._replace_published_path",
            side_effect=publish_primary_then_create_backup,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save(
                    "book:first-save-post-replace-backup",
                    BookReader(self.original_document()),
                )

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
        )
        self.assertTrue(self.path.exists())
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)

    def test_save_rechecks_primary_after_temp_fsync_before_replace(self) -> None:
        self.path.parent.mkdir(parents=True)
        external = b'{"entries":{},"generation":41,"schema_version":2}'
        real_mkstemp = tempfile.mkstemp
        injected = False

        def primary_appears_during_temp_write(*args, **kwargs):
            nonlocal injected
            descriptor, name = real_mkstemp(*args, **kwargs)
            if kwargs.get("prefix") == f".{self.path.name}.":
                self.path.write_bytes(external)
                injected = True
            return descriptor, name

        with mock.patch(
            "acs.book_progress_store.tempfile.mkstemp",
            side_effect=primary_appears_during_temp_write,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save(
                    "book:primary-temp-race",
                    BookReader(self.original_document()),
                )

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.STALE_WRITE,
        )
        self.assertEqual(self.path.read_bytes(), external)
        self.assertFalse(self.store.backup_path.exists())
        self.assertFalse(
            any(
                item.name.startswith(f".{self.path.name}.")
                and item.name.endswith(".tmp")
                for item in self.path.parent.iterdir()
            )
        )

    def test_publish_rejects_substituted_temp_inode_without_deleting_substitute(self) -> None:
        self.path.parent.mkdir(parents=True)
        real_require = self.store._require_no_orphan_backup_unlocked
        checks = 0
        substituted_path: Path | None = None
        substitute_bytes = b"user-owned-substitute-bytes"

        def substitute_after_temp_fsync() -> None:
            nonlocal checks, substituted_path
            checks += 1
            real_require()
            if checks != 4:
                return
            candidates = tuple(
                item
                for item in self.path.parent.iterdir()
                if item.name.startswith(f".{self.path.name}.")
                and item.name.endswith(".tmp")
            )
            self.assertEqual(len(candidates), 1)
            substituted_path = candidates[0]
            replacement = self.path.parent / "user-owned-substitute.bin"
            replacement.write_bytes(substitute_bytes)
            os.replace(replacement, substituted_path)

        with mock.patch.object(
            self.store,
            "_require_no_orphan_backup_unlocked",
            side_effect=substitute_after_temp_fsync,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save(
                    "book:temp-substitution",
                    BookReader(self.original_document()),
                )

        self.assertEqual(checks, 4)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)
        self.assertFalse(self.path.exists())
        self.assertIsNotNone(substituted_path)
        assert substituted_path is not None
        self.assertTrue(substituted_path.exists())
        self.assertEqual(substituted_path.read_bytes(), substitute_bytes)

    def test_temp_cleanup_last_window_substitution_preserves_foreign_bytes(self) -> None:
        self.path.parent.mkdir(parents=True)
        candidate = self.path.parent / ".book-progress.json.cleanup-probe.tmp"
        candidate.write_bytes(b"writer-owned-temp")
        expected = os.lstat(candidate)
        foreign = self.path.parent / "foreign-temp-last-window.bin"
        foreign_bytes = b"foreign-temp-last-window"
        foreign.write_bytes(foreign_bytes)
        real_replace = os.replace
        injected = False

        def substitute_then_quarantine(source, destination):
            nonlocal injected
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                source_path == candidate
                and ".cleanup-quarantine-" in destination_path.name
                and not injected
            ):
                real_replace(foreign, candidate)
                injected = True
            return real_replace(source, destination)

        with mock.patch(
            "acs.book_progress_store.os.replace",
            side_effect=substitute_then_quarantine,
        ):
            self.store._discard_owned_temp_unlocked(candidate, expected)

        self.assertTrue(injected)
        self.assertFalse(candidate.exists())
        quarantines = tuple(
            item
            for item in self.path.parent.iterdir()
            if item.name.startswith(
                f".{candidate.name}.cleanup-quarantine-"
            )
        )
        self.assertEqual(len(quarantines), 1)
        self.assertEqual(quarantines[0].read_bytes(), foreign_bytes)

    def test_publish_rejects_hardlinked_temp_inode_without_unlinking_peer(self) -> None:
        self.path.parent.mkdir(parents=True)
        real_require = self.store._require_no_orphan_backup_unlocked
        checks = 0
        temp_path: Path | None = None
        peer = self.path.parent / "user-owned-temp-hardlink.bin"

        def hardlink_after_temp_fsync() -> None:
            nonlocal checks, temp_path
            checks += 1
            real_require()
            if checks != 4:
                return
            candidates = tuple(
                item
                for item in self.path.parent.iterdir()
                if item.name.startswith(f".{self.path.name}.")
                and item.name.endswith(".tmp")
            )
            self.assertEqual(len(candidates), 1)
            temp_path = candidates[0]
            try:
                os.link(temp_path, peer)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")

        with mock.patch.object(
            self.store,
            "_require_no_orphan_backup_unlocked",
            side_effect=hardlink_after_temp_fsync,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save(
                    "book:temp-hardlink",
                    BookReader(self.original_document()),
                )

        self.assertEqual(checks, 4)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)
        self.assertFalse(self.path.exists())
        self.assertIsNotNone(temp_path)
        assert temp_path is not None
        self.assertTrue(temp_path.exists())
        self.assertTrue(peer.exists())
        self.assertEqual(temp_path.read_bytes(), peer.read_bytes())
        self.assertEqual(os.lstat(temp_path).st_nlink, 2)

    def test_cross_run_temp_scavenging_preserves_all_candidate_pathnames(self) -> None:
        self.path.parent.mkdir(parents=True)
        exact_candidates = (
            self.path.parent / ".book-progress.json.abcd_123.tmp",
            self.path.parent / ".book-progress.json.bak.xy_987ab.tmp",
        )
        for path in exact_candidates:
            path.write_bytes(b"stale-looking-user-data")

        user_files = (
            self.path.parent / ".book-progress.json.bad.token.tmp",
            self.path.parent / ".book-progress.json.bad-token.tmp",
            self.path.parent / ".book-progress.json..tmp",
            self.path.parent / ".book-progress.json.a.tmp",
            self.path.parent / ".book-progress.json.abcdefghi.tmp",
            self.path.parent / "book-progress.json.abcd_123.tmp",
            self.path.parent / ".book-progress.json.abcd_123.tmp.keep",
            self.path.parent / ".book-progress.json.bak.bad.token.tmp",
            self.path.parent / ".book-progress.json.bak.xy_987.tmp",
        )
        for path in user_files:
            path.write_bytes(b"user-data")

        user_directory = self.path.parent / ".book-progress.json.zz_123.tmp"
        user_directory.mkdir()
        (user_directory / "keep.bin").write_bytes(b"directory-user-data")

        with self.store._exclusive_access():
            pass

        for path in exact_candidates:
            self.assertEqual(path.read_bytes(), b"stale-looking-user-data")
        for path in user_files:
            self.assertEqual(path.read_bytes(), b"user-data")
        self.assertEqual(
            (user_directory / "keep.bin").read_bytes(),
            b"directory-user-data",
        )

    def test_stale_temp_cleanup_preserves_hardlinked_exact_name(self) -> None:
        self.path.parent.mkdir(parents=True)
        peer = self.path.parent / "user-owned-temp-peer.bin"
        peer.write_bytes(b"user-owned-hardlink-bytes")
        candidate = self.path.parent / ".book-progress.json.abcd_123.tmp"
        try:
            os.link(peer, candidate)
        except (OSError, NotImplementedError):
            self.skipTest("hard-link creation is unavailable on this runner")

        with self.store._exclusive_access():
            pass

        self.assertTrue(candidate.exists())
        self.assertEqual(candidate.read_bytes(), b"user-owned-hardlink-bytes")
        self.assertEqual(peer.read_bytes(), b"user-owned-hardlink-bytes")
        self.assertEqual(os.lstat(peer).st_nlink, 2)

    def test_cross_run_scavenging_preserves_exact_and_similar_backup_names(self) -> None:
        self.path.parent.mkdir(parents=True)
        exact_candidate = self.path.parent / ".book-progress.json.bak.a1_b2c3d.tmp"
        exact_candidate.write_bytes(b"preserve-exact")
        similar = (
            self.path.parent / ".book-progress.json.bak.a1.b2.tmp",
            self.path.parent / ".book-progress.json.bak.a1-b2.tmp",
            self.path.parent / ".book-progress.json.bak.a1_b2.tmp.extra",
        )
        for path in similar:
            path.write_bytes(b"preserve")

        with self.store._exclusive_access():
            pass

        self.assertEqual(exact_candidate.read_bytes(), b"preserve-exact")
        for path in similar:
            self.assertEqual(path.read_bytes(), b"preserve")

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

    def test_missing_primary_recovery_rechecks_primary_after_temp_fsync(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:recovery-temp-race", reader)
        reader.go_to(3)
        self.store.save("book:recovery-temp-race", reader)

        backup_bytes = self.store.backup_path.read_bytes()
        backup_revision = self.store.validated_backup_revision(
            "book:recovery-temp-race",
            self.original_document(),
        )
        external = self.path.read_bytes()
        self.path.unlink()
        real_mkstemp = tempfile.mkstemp
        injected = False

        def primary_reappears_during_temp_write(*args, **kwargs):
            nonlocal injected
            descriptor, name = real_mkstemp(*args, **kwargs)
            if kwargs.get("prefix") == f".{self.path.name}.":
                self.path.write_bytes(external)
                injected = True
            return descriptor, name

        with mock.patch(
            "acs.book_progress_store.tempfile.mkstemp",
            side_effect=primary_reappears_during_temp_write,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.recover_from_backup(
                    expected_backup_revision=backup_revision,
                )

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.STALE_WRITE,
        )
        self.assertEqual(self.path.read_bytes(), external)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)
        self.assertFalse(
            any(
                item.name.startswith(f".{self.path.name}.")
                and item.name.endswith(".tmp")
                for item in self.path.parent.iterdir()
            )
        )

    def test_missing_primary_recovery_rechecks_backup_after_temp_fsync(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:recovery-backup-race", reader)
        reader.go_to(3)
        self.store.save("book:recovery-backup-race", reader)

        validated_backup = self.store.backup_path.read_bytes()
        backup_revision = self.store.validated_backup_revision(
            "book:recovery-backup-race",
            self.original_document(),
        )
        newer_backup = self.path.read_bytes()
        self.path.unlink()
        real_mkstemp = tempfile.mkstemp
        injected = False

        def backup_advances_during_primary_temp_write(*args, **kwargs):
            nonlocal injected
            descriptor, name = real_mkstemp(*args, **kwargs)
            if kwargs.get("prefix") == f".{self.path.name}.":
                self.store.backup_path.write_bytes(newer_backup)
                injected = True
            return descriptor, name

        with mock.patch(
            "acs.book_progress_store.tempfile.mkstemp",
            side_effect=backup_advances_during_primary_temp_write,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.recover_from_backup(
                    expected_backup_revision=backup_revision,
                )

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.STALE_WRITE,
        )
        self.assertFalse(self.path.exists())
        self.assertNotEqual(validated_backup, newer_backup)
        self.assertEqual(self.store.backup_path.read_bytes(), newer_backup)
        self.assertFalse(
            any(
                item.name.startswith(f".{self.path.name}.")
                and item.name.endswith(".tmp")
                for item in self.path.parent.iterdir()
            )
        )

    def test_missing_primary_recovery_rejects_same_bytes_backup_inode_replacement_before_publish(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:explicit-backup-inode", reader)
        reader.go_to(3)
        self.store.save("book:explicit-backup-inode", reader)

        backup_bytes = self.store.backup_path.read_bytes()
        backup_revision = self.store.validated_backup_revision(
            "book:explicit-backup-inode",
            self.original_document(),
        )
        self.path.unlink()
        real_publish = self.store._atomic_publish_bytes_unlocked
        injected = False

        def publish_after_same_bytes_backup_replacement(target, encoded, **kwargs):
            nonlocal injected
            if Path(target) == self.path and not injected:
                replacement = self.store.backup_path.with_name(
                    "same-byte-explicit-recovery-backup-replacement.json"
                )
                replacement.write_bytes(backup_bytes)
                os.replace(replacement, self.store.backup_path)
                injected = True
            return real_publish(target, encoded, **kwargs)

        with mock.patch.object(
            self.store,
            "_atomic_publish_bytes_unlocked",
            side_effect=publish_after_same_bytes_backup_replacement,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.recover_from_backup(
                    expected_backup_revision=backup_revision,
                )

        self.assertTrue(injected)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)

    def test_corrupt_primary_recovery_rejects_same_bytes_primary_inode_replacement_before_publish(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:explicit-primary-inode", reader)
        reader.go_to(3)
        self.store.save("book:explicit-primary-inode", reader)

        corrupt_primary = b'{"schema_version":2,"generation":'
        self.path.write_bytes(corrupt_primary)
        backup_bytes = self.store.backup_path.read_bytes()
        backup_revision = self.store.validated_backup_revision(
            "book:explicit-primary-inode",
            self.original_document(),
        )
        real_publish = self.store._atomic_publish_bytes_unlocked
        injected = False

        def publish_after_same_bytes_primary_replacement(target, encoded, **kwargs):
            nonlocal injected
            if Path(target) == self.path and not injected:
                replacement = self.path.with_name(
                    "same-byte-explicit-recovery-primary-replacement.json"
                )
                replacement.write_bytes(corrupt_primary)
                os.replace(replacement, self.path)
                injected = True
            return real_publish(target, encoded, **kwargs)

        with mock.patch.object(
            self.store,
            "_atomic_publish_bytes_unlocked",
            side_effect=publish_after_same_bytes_primary_replacement,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.recover_from_backup(
                    expected_backup_revision=backup_revision,
                )

        self.assertTrue(injected)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), corrupt_primary)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)

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

    def test_valid_primary_save_preserves_future_schema_backup(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:future-rolling", reader)
        primary_before = self.path.read_bytes()
        future_backup = b'{"entries":{},"generation":99,"schema_version":999}'
        self.store.backup_path.write_bytes(future_backup)

        reader.go_to(2)
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.save("book:future-rolling", reader)

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.UNSUPPORTED_SCHEMA,
        )
        self.assertEqual(self.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), future_backup)

    def test_valid_primary_save_preserves_newer_generation_backup(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:newer-rolling", reader)
        primary_before = self.path.read_bytes()
        newer_backup = b'{"entries":{},"generation":99,"schema_version":2}'
        self.store.backup_path.write_bytes(newer_backup)

        reader.go_to(2)
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.save("book:newer-rolling", reader)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), newer_backup)

    def test_valid_primary_save_rejects_divergent_same_generation_backup(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:divergent-rolling", reader)
        primary_before = self.path.read_bytes()
        divergent_backup = b'{"entries":{},"generation":1,"schema_version":2}'
        self.store.backup_path.write_bytes(divergent_backup)

        reader.go_to(2)
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.save("book:divergent-rolling", reader)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), divergent_backup)

    def test_valid_primary_save_repairs_corrupt_backup(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:repair-rolling", reader)
        primary_before = self.path.read_bytes()
        self.store.backup_path.write_bytes(
            b'{"entries":{},"generation":'
        )

        reader.go_to(2)
        saved = self.store.save("book:repair-rolling", reader)

        self.assertEqual(saved["current_target"], "block:diagram")
        self.assertNotEqual(self.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), primary_before)

    def test_legacy_generation_zero_primary_can_repair_divergent_legacy_backup(self) -> None:
        primary_reader = BookReader(self.original_document())
        primary_reader.go_to(1)
        backup_reader = BookReader(self.original_document())
        backup_reader.go_to(0)
        legacy_primary = json.dumps(
            {
                "schema_version": 1,
                "entries": {"book:legacy-migrate": primary_reader.snapshot()},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        legacy_backup = json.dumps(
            {
                "schema_version": 1,
                "entries": {"book:legacy-migrate": backup_reader.snapshot()},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(legacy_primary)
        self.store.backup_path.write_bytes(legacy_backup)

        primary_reader.go_to(2)
        saved = self.store.save("book:legacy-migrate", primary_reader)

        self.assertEqual(saved["current_target"], "block:diagram")
        self.assertEqual(self.store.backup_path.read_bytes(), legacy_primary)
        migrated = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["generation"], 1)

    def test_v2_generation_zero_primary_preserves_divergent_v2_backup(self) -> None:
        primary_reader = BookReader(self.original_document())
        primary_reader.go_to(1)
        backup_reader = BookReader(self.original_document())
        backup_reader.go_to(0)
        primary = json.dumps(
            {
                "schema_version": 2,
                "generation": 0,
                "entries": {"book:v2-zero": primary_reader.snapshot()},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        backup = json.dumps(
            {
                "schema_version": 2,
                "generation": 0,
                "entries": {"book:v2-zero": backup_reader.snapshot()},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(primary)
        self.store.backup_path.write_bytes(backup)

        primary_reader.go_to(2)
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.save("book:v2-zero", primary_reader)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), primary)
        self.assertEqual(self.store.backup_path.read_bytes(), backup)

    def test_legacy_primary_preserves_divergent_v2_generation_zero_backup(self) -> None:
        primary_reader = BookReader(self.original_document())
        primary_reader.go_to(1)
        backup_reader = BookReader(self.original_document())
        backup_reader.go_to(0)
        legacy_primary = json.dumps(
            {
                "schema_version": 1,
                "entries": {"book:legacy-v2-zero": primary_reader.snapshot()},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        v2_backup = json.dumps(
            {
                "schema_version": 2,
                "generation": 0,
                "entries": {"book:legacy-v2-zero": backup_reader.snapshot()},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(legacy_primary)
        self.store.backup_path.write_bytes(v2_backup)

        primary_reader.go_to(2)
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.save("book:legacy-v2-zero", primary_reader)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), legacy_primary)
        self.assertEqual(self.store.backup_path.read_bytes(), v2_backup)

    def test_v2_generation_zero_primary_preserves_divergent_legacy_backup(self) -> None:
        primary_reader = BookReader(self.original_document())
        primary_reader.go_to(1)
        backup_reader = BookReader(self.original_document())
        backup_reader.go_to(0)
        v2_primary = json.dumps(
            {
                "schema_version": 2,
                "generation": 0,
                "entries": {"book:v2-zero-legacy": primary_reader.snapshot()},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        legacy_backup = json.dumps(
            {
                "schema_version": 1,
                "entries": {"book:v2-zero-legacy": backup_reader.snapshot()},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(v2_primary)
        self.store.backup_path.write_bytes(legacy_backup)

        primary_reader.go_to(2)
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.save("book:v2-zero-legacy", primary_reader)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), v2_primary)
        self.assertEqual(self.store.backup_path.read_bytes(), legacy_backup)

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
            "acs.book_progress_store._replace_published_path",
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

    def test_backup_publication_rechecks_target_after_temp_fsync(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:backup-temp-race", reader)
        reader.go_to(2)
        self.store.save("book:backup-temp-race", reader)

        primary_before = self.path.read_bytes()
        external_backup = b'{"entries":{},"generation":91,"schema_version":2}'
        real_mkstemp = tempfile.mkstemp
        injected = False

        def backup_changes_during_temp_write(*args, **kwargs):
            nonlocal injected
            descriptor, name = real_mkstemp(*args, **kwargs)
            if kwargs.get("prefix") == f".{self.store.backup_path.name}.":
                self.store.backup_path.write_bytes(external_backup)
                injected = True
            return descriptor, name

        reader.go_to(3)
        with mock.patch(
            "acs.book_progress_store.tempfile.mkstemp",
            side_effect=backup_changes_during_temp_write,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:backup-temp-race", reader)

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.STALE_WRITE,
        )
        self.assertEqual(self.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), external_backup)
        self.assertFalse(
            any(
                item.name.startswith(f".{self.store.backup_path.name}.")
                and item.name.endswith(".tmp")
                for item in self.path.parent.iterdir()
            )
        )

    def test_backup_publication_rechecks_primary_after_temp_fsync(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:backup-primary-guard", reader)
        reader.go_to(2)
        self.store.save("book:backup-primary-guard", reader)

        primary_before = self.path.read_bytes()
        backup_before = self.store.backup_path.read_bytes()
        external_primary = b'{"entries":{},"generation":99,"schema_version":2}'
        real_mkstemp = tempfile.mkstemp
        injected = False

        def primary_changes_during_backup_temp_write(*args, **kwargs):
            nonlocal injected
            descriptor, name = real_mkstemp(*args, **kwargs)
            if kwargs.get("prefix") == f".{self.store.backup_path.name}.":
                self.path.write_bytes(external_primary)
                injected = True
            return descriptor, name

        reader.go_to(3)
        with mock.patch(
            "acs.book_progress_store.tempfile.mkstemp",
            side_effect=primary_changes_during_backup_temp_write,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:backup-primary-guard", reader)

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.STALE_WRITE,
        )
        self.assertEqual(self.path.read_bytes(), external_primary)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)
        self.assertNotEqual(primary_before, external_primary)
        self.assertFalse(
            any(
                item.name.startswith(f".{self.store.backup_path.name}.")
                and item.name.endswith(".tmp")
                for item in self.path.parent.iterdir()
            )
        )

    def test_primary_publication_rechecks_backup_after_temp_fsync(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:primary-backup-guard", reader)
        reader.go_to(2)
        self.store.save("book:primary-backup-guard", reader)

        primary_before = self.path.read_bytes()
        external_backup = b'{"entries":{},"generation":77,"schema_version":2}'
        real_mkstemp = tempfile.mkstemp
        injected = False

        def backup_changes_during_primary_temp_write(*args, **kwargs):
            nonlocal injected
            descriptor, name = real_mkstemp(*args, **kwargs)
            if kwargs.get("prefix") == f".{self.path.name}.":
                self.store.backup_path.write_bytes(external_backup)
                injected = True
            return descriptor, name

        reader.go_to(3)
        with mock.patch(
            "acs.book_progress_store.tempfile.mkstemp",
            side_effect=backup_changes_during_primary_temp_write,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:primary-backup-guard", reader)

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.STALE_WRITE,
        )
        self.assertEqual(self.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), external_backup)
        self.assertFalse(
            any(
                item.name.startswith(f".{self.path.name}.")
                and item.name.endswith(".tmp")
                for item in self.path.parent.iterdir()
            )
        )

    def test_save_rejects_same_bytes_primary_inode_replacement_after_load(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:transaction-primary-inode", reader)

        primary_before = self.path.read_bytes()
        real_write = self.store._write_payload_unlocked
        injected = False

        def write_after_same_bytes_primary_replacement(payload, **kwargs):
            nonlocal injected
            if not injected:
                replacement = self.path.with_name(
                    "same-byte-transaction-primary-replacement.json"
                )
                replacement.write_bytes(primary_before)
                os.replace(replacement, self.path)
                injected = True
            return real_write(payload, **kwargs)

        reader.go_to(2)
        with mock.patch.object(
            self.store,
            "_write_payload_unlocked",
            side_effect=write_after_same_bytes_primary_replacement,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:transaction-primary-inode", reader)

        self.assertTrue(injected)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), primary_before)
        self.assertFalse(self.store.backup_path.exists())
        restored = self.store.restore_primary(
            "book:transaction-primary-inode",
            self.original_document(),
        )
        self.assertEqual(restored.index, 1)

    def test_backup_publication_rejects_same_bytes_backup_inode_replacement_before_publish_entry(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:transaction-backup-target", reader)
        reader.go_to(2)
        self.store.save("book:transaction-backup-target", reader)

        primary_before = self.path.read_bytes()
        backup_before = self.store.backup_path.read_bytes()
        real_publish = self.store._atomic_publish_bytes_unlocked
        injected = False

        def publish_after_same_bytes_backup_replacement(target, encoded, **kwargs):
            nonlocal injected
            if Path(target) == self.store.backup_path and not injected:
                replacement = self.store.backup_path.with_name(
                    "same-byte-transaction-backup-target-replacement.json"
                )
                replacement.write_bytes(backup_before)
                os.replace(replacement, self.store.backup_path)
                injected = True
            return real_publish(target, encoded, **kwargs)

        reader.go_to(3)
        with mock.patch.object(
            self.store,
            "_atomic_publish_bytes_unlocked",
            side_effect=publish_after_same_bytes_backup_replacement,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:transaction-backup-target", reader)

        self.assertTrue(injected)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)
        restored = self.store.restore_primary(
            "book:transaction-backup-target",
            self.original_document(),
        )
        self.assertEqual(restored.index, 2)

    def test_primary_publication_rejects_same_bytes_backup_inode_replacement_between_publications(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:transaction-backup-guard", reader)

        primary_before = self.path.read_bytes()
        real_publish = self.store._atomic_publish_bytes_unlocked
        injected = False

        def publish_then_replace_backup_with_same_bytes(target, encoded, **kwargs):
            nonlocal injected
            result = real_publish(target, encoded, **kwargs)
            if Path(target) == self.store.backup_path and not injected:
                backup_bytes = self.store.backup_path.read_bytes()
                replacement = self.store.backup_path.with_name(
                    "same-byte-between-publications-backup-replacement.json"
                )
                replacement.write_bytes(backup_bytes)
                os.replace(replacement, self.store.backup_path)
                injected = True
            return result

        reader.go_to(2)
        with mock.patch.object(
            self.store,
            "_atomic_publish_bytes_unlocked",
            side_effect=publish_then_replace_backup_with_same_bytes,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:transaction-backup-guard", reader)

        self.assertTrue(injected)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), primary_before)
        restored = self.store.restore_primary(
            "book:transaction-backup-guard",
            self.original_document(),
        )
        self.assertEqual(restored.index, 1)

    def test_primary_publication_rejects_same_bytes_primary_inode_replacement_between_publications(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:transaction-primary-target", reader)

        primary_before = self.path.read_bytes()
        real_publish = self.store._atomic_publish_bytes_unlocked
        injected = False

        def publish_backup_then_replace_primary_with_same_bytes(target, encoded, **kwargs):
            nonlocal injected
            result = real_publish(target, encoded, **kwargs)
            if Path(target) == self.store.backup_path and not injected:
                replacement = self.path.with_name(
                    "same-byte-between-publications-primary-replacement.json"
                )
                replacement.write_bytes(primary_before)
                os.replace(replacement, self.path)
                injected = True
            return result

        reader.go_to(2)
        with mock.patch.object(
            self.store,
            "_atomic_publish_bytes_unlocked",
            side_effect=publish_backup_then_replace_primary_with_same_bytes,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:transaction-primary-target", reader)

        self.assertTrue(injected)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), primary_before)
        restored = self.store.restore_primary(
            "book:transaction-primary-target",
            self.original_document(),
        )
        self.assertEqual(restored.index, 1)

    def test_backup_publication_primary_guard_change_after_replace_reports_durability_unknown(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:post-replace-primary-guard", reader)
        primary_before = self.path.read_bytes()
        real_replace = __import__(
            "acs.book_progress_store",
            fromlist=["_replace_published_path"],
        )._replace_published_path
        injected = False

        def publish_backup_then_replace_primary(source: Path, destination: Path) -> None:
            nonlocal injected
            real_replace(source, destination)
            if Path(destination) == self.store.backup_path and not injected:
                replacement = self.path.with_name(
                    "same-byte-post-backup-primary-guard.json"
                )
                replacement.write_bytes(primary_before)
                os.replace(replacement, self.path)
                injected = True

        reader.go_to(2)
        with mock.patch(
            "acs.book_progress_store._replace_published_path",
            side_effect=publish_backup_then_replace_primary,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:post-replace-primary-guard", reader)

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
        )
        self.assertEqual(self.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), primary_before)

    def test_primary_publication_backup_guard_change_after_replace_reports_durability_unknown(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:post-replace-backup-guard", reader)
        primary_before = self.path.read_bytes()
        real_replace = __import__(
            "acs.book_progress_store",
            fromlist=["_replace_published_path"],
        )._replace_published_path
        injected = False

        def publish_then_replace_backup_guard(source: Path, destination: Path) -> None:
            nonlocal injected
            real_replace(source, destination)
            if Path(destination) == self.path and not injected:
                backup_bytes = self.store.backup_path.read_bytes()
                replacement = self.store.backup_path.with_name(
                    "same-byte-post-primary-backup-guard.json"
                )
                replacement.write_bytes(backup_bytes)
                os.replace(replacement, self.store.backup_path)
                injected = True

        reader.go_to(2)
        with mock.patch(
            "acs.book_progress_store._replace_published_path",
            side_effect=publish_then_replace_backup_guard,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:post-replace-backup-guard", reader)

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
        )
        self.assertNotEqual(self.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), primary_before)

    def test_save_preserves_newer_backup_when_primary_advances_before_backup_publish(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:backup-transaction-cas", reader)
        reader.go_to(2)
        self.store.save("book:backup-transaction-cas", reader)

        external_primary = b'{"entries":{},"generation":99,"schema_version":2}'
        external_backup = b'{"entries":{},"generation":98,"schema_version":2}'
        real_publish = self.store._atomic_publish_bytes_unlocked
        injected = False

        def publish_after_external_commit(target, encoded, **kwargs):
            nonlocal injected
            if target == self.store.backup_path and not injected:
                self.path.write_bytes(external_primary)
                self.store.backup_path.write_bytes(external_backup)
                injected = True
            return real_publish(target, encoded, **kwargs)

        reader.go_to(3)
        with mock.patch.object(
            self.store,
            "_atomic_publish_bytes_unlocked",
            side_effect=publish_after_external_commit,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:backup-transaction-cas", reader)

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.STALE_WRITE,
        )
        self.assertEqual(self.path.read_bytes(), external_primary)
        self.assertEqual(self.store.backup_path.read_bytes(), external_backup)
        self.assertFalse(
            any(
                item.name.startswith(f".{self.store.backup_path.name}.")
                and item.name.endswith(".tmp")
                for item in self.path.parent.iterdir()
            )
        )

    def test_windows_publication_sync_uses_writable_nonreparse_descriptor(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"durable")
        descriptor = os.open(self.path, os.O_RDWR)

        with (
            mock.patch("acs.book_progress_store.os.name", "nt"),
            mock.patch(
                "acs.book_progress_store._windows_open_existing_writable_no_reparse",
                return_value=descriptor,
            ) as open_bound,
            mock.patch("acs.book_progress_store.os.fsync") as fsync,
        ):
            _sync_published_path(self.path)

        open_bound.assert_called_once_with(self.path)
        fsync.assert_called_once_with(descriptor)
        with self.assertRaises(OSError):
            os.fstat(descriptor)

    def test_post_replace_canonical_change_reports_durability_unknown(self) -> None:
        self.path.parent.mkdir(parents=True)
        external = b'{"entries":{},"generation":41,"schema_version":2}'

        def replace_after_sync(path: Path) -> None:
            if Path(path) == self.path:
                self.path.write_bytes(external)

        with mock.patch(
            "acs.book_progress_store._sync_published_path",
            side_effect=replace_after_sync,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save(
                    "book:post-replace-race",
                    BookReader(self.original_document()),
                )

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
        )
        self.assertEqual(self.path.read_bytes(), external)

    def test_post_replace_same_bytes_substitution_during_sync_reports_durability_unknown(self) -> None:
        injected = False

        def sync_after_same_bytes_substitution(path: Path) -> None:
            nonlocal injected
            path = Path(path)
            if path == self.path:
                foreign = path.with_name("foreign-during-primary-sync.json")
                foreign.write_bytes(path.read_bytes())
                os.replace(foreign, path)
                injected = True

        with mock.patch(
            "acs.book_progress_store._sync_published_path",
            side_effect=sync_after_same_bytes_substitution,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save(
                    "book:same-bytes-during-primary-sync",
                    BookReader(self.original_document()),
                )

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
        )
        self.assertTrue(self.store.has("book:same-bytes-during-primary-sync"))

    def test_backup_same_bytes_substitution_during_sync_reports_durability_unknown(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:same-bytes-during-backup-sync", reader)
        primary_before = self.path.read_bytes()
        injected = False

        def sync_after_same_bytes_substitution(path: Path) -> None:
            nonlocal injected
            path = Path(path)
            if path == self.store.backup_path:
                foreign = path.with_name("foreign-during-backup-sync.json")
                foreign.write_bytes(path.read_bytes())
                os.replace(foreign, path)
                injected = True

        reader.go_to(2)
        with mock.patch(
            "acs.book_progress_store._sync_published_path",
            side_effect=sync_after_same_bytes_substitution,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:same-bytes-during-backup-sync", reader)

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
        )
        self.assertEqual(self.path.read_bytes(), primary_before)
        self.assertTrue(self.store.has("book:same-bytes-during-backup-sync"))

    def test_backup_publication_rejects_same_bytes_primary_guard_substitution(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:guard-inode-primary", reader)

        primary_before = self.path.read_bytes()
        real_read = self.store._read_raw_file_unlocked
        primary_reads = 0
        injected = False

        def substitute_primary_guard_after_read(
            path: Path,
            *,
            missing_ok: bool,
        ) -> bytes | None:
            nonlocal primary_reads, injected
            raw = real_read(path, missing_ok=missing_ok)
            if Path(path) == self.path:
                primary_reads += 1
                if primary_reads == 3 and raw is not None:
                    foreign = self.path.with_name("foreign-primary-guard.json")
                    foreign.write_bytes(raw)
                    os.replace(foreign, self.path)
                    injected = True
            return raw

        reader.go_to(2)
        with mock.patch.object(
            self.store,
            "_read_raw_file_unlocked",
            side_effect=substitute_primary_guard_after_read,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:guard-inode-primary", reader)

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.STALE_WRITE,
        )
        self.assertEqual(self.path.read_bytes(), primary_before)
        self.assertFalse(self.store.backup_path.exists())
        restored = self.store.restore_primary(
            "book:guard-inode-primary",
            self.original_document(),
        )
        self.assertEqual(restored.index, 1)

    def test_primary_publication_rejects_same_bytes_backup_guard_substitution(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:guard-inode-backup", reader)

        primary_before = self.path.read_bytes()
        real_read = self.store._read_raw_file_unlocked
        backup_nonmissing_reads = 0
        injected = False

        def substitute_backup_guard_after_read(
            path: Path,
            *,
            missing_ok: bool,
        ) -> bytes | None:
            nonlocal backup_nonmissing_reads, injected
            raw = real_read(path, missing_ok=missing_ok)
            if Path(path) == self.store.backup_path and raw is not None:
                backup_nonmissing_reads += 1
                if backup_nonmissing_reads == 2:
                    foreign = self.store.backup_path.with_name(
                        "foreign-backup-guard.json"
                    )
                    foreign.write_bytes(raw)
                    os.replace(foreign, self.store.backup_path)
                    injected = True
            return raw

        reader.go_to(2)
        with mock.patch.object(
            self.store,
            "_read_raw_file_unlocked",
            side_effect=substitute_backup_guard_after_read,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:guard-inode-backup", reader)

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.STALE_WRITE,
        )
        self.assertEqual(self.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), primary_before)
        restored = self.store.restore_primary(
            "book:guard-inode-backup",
            self.original_document(),
        )
        self.assertEqual(restored.index, 1)

    def test_primary_publication_rejects_same_bytes_target_inode_substitution(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:target-inode-primary", reader)
        primary_before = self.path.read_bytes()
        real_read = self.store._read_raw_file_unlocked
        primary_reads = 0
        injected = False

        def substitute_primary_after_cas_read(
            path: Path,
            *,
            missing_ok: bool,
        ) -> bytes | None:
            nonlocal primary_reads, injected
            raw = real_read(path, missing_ok=missing_ok)
            if Path(path) == self.path:
                primary_reads += 1
                if primary_reads == 5 and raw is not None:
                    foreign = self.path.with_name("foreign-primary-cas.json")
                    foreign.write_bytes(raw)
                    os.replace(foreign, self.path)
                    injected = True
            return raw

        reader.go_to(2)
        with mock.patch.object(
            self.store,
            "_read_raw_file_unlocked",
            side_effect=substitute_primary_after_cas_read,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:target-inode-primary", reader)

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.STALE_WRITE,
        )
        self.assertEqual(self.path.read_bytes(), primary_before)
        restored = self.store.restore_primary(
            "book:target-inode-primary",
            self.original_document(),
        )
        self.assertEqual(restored.index, 1)

    def test_backup_publication_rejects_same_bytes_target_inode_substitution(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:target-inode-backup", reader)
        reader.go_to(2)
        self.store.save("book:target-inode-backup", reader)

        primary_before = self.path.read_bytes()
        backup_before = self.store.backup_path.read_bytes()
        real_read = self.store._read_raw_file_unlocked
        backup_reads = 0
        injected = False

        def substitute_backup_after_cas_read(
            path: Path,
            *,
            missing_ok: bool,
        ) -> bytes | None:
            nonlocal backup_reads, injected
            raw = real_read(path, missing_ok=missing_ok)
            if Path(path) == self.store.backup_path:
                backup_reads += 1
                if backup_reads == 2 and raw is not None:
                    foreign = self.store.backup_path.with_name(
                        "foreign-backup-cas.json"
                    )
                    foreign.write_bytes(raw)
                    os.replace(foreign, self.store.backup_path)
                    injected = True
            return raw

        reader.go_to(3)
        with mock.patch.object(
            self.store,
            "_read_raw_file_unlocked",
            side_effect=substitute_backup_after_cas_read,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:target-inode-backup", reader)

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.STALE_WRITE,
        )
        self.assertEqual(self.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)
        restored = self.store.restore_primary(
            "book:target-inode-backup",
            self.original_document(),
        )
        self.assertEqual(restored.index, 2)

    def test_primary_publication_rejects_same_bytes_temp_inode_substitution(self) -> None:
        injected = False

        def substitute_same_bytes_temp(source: Path, destination: Path) -> None:
            nonlocal injected
            source = Path(source)
            destination = Path(destination)
            if destination == self.path:
                foreign = source.with_name(source.name + ".foreign")
                foreign.write_bytes(source.read_bytes())
                os.replace(foreign, source)
                injected = True
            os.replace(source, destination)

        with mock.patch(
            "acs.book_progress_store._replace_published_path",
            side_effect=substitute_same_bytes_temp,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save(
                    "book:same-bytes-primary-substitution",
                    BookReader(self.original_document()),
                )

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
        )
        self.assertTrue(self.path.exists())
        self.assertTrue(self.store.has("book:same-bytes-primary-substitution"))

    def test_post_replace_same_bytes_canonical_substitution_reports_durability_unknown(self) -> None:
        injected = False

        def publish_then_substitute_same_bytes(source: Path, destination: Path) -> None:
            nonlocal injected
            source = Path(source)
            destination = Path(destination)
            os.replace(source, destination)
            if destination == self.path:
                foreign = destination.with_name("foreign-after-publication.json")
                foreign.write_bytes(destination.read_bytes())
                os.replace(foreign, destination)
                injected = True

        with mock.patch(
            "acs.book_progress_store._replace_published_path",
            side_effect=publish_then_substitute_same_bytes,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save(
                    "book:same-bytes-post-replace",
                    BookReader(self.original_document()),
                )

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
        )
        self.assertTrue(self.store.has("book:same-bytes-post-replace"))

    def test_backup_publication_rejects_same_bytes_temp_inode_substitution(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:same-bytes-backup-substitution", reader)
        primary_before = self.path.read_bytes()
        reader.go_to(2)
        injected = False

        def substitute_same_bytes_temp(source: Path, destination: Path) -> None:
            nonlocal injected
            source = Path(source)
            destination = Path(destination)
            if destination == self.store.backup_path:
                foreign = source.with_name(source.name + ".foreign")
                foreign.write_bytes(source.read_bytes())
                os.replace(foreign, source)
                injected = True
            os.replace(source, destination)

        with mock.patch(
            "acs.book_progress_store._replace_published_path",
            side_effect=substitute_same_bytes_temp,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:same-bytes-backup-substitution", reader)

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
        )
        self.assertEqual(self.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), primary_before)
        restored = self.store.restore_primary(
            "book:same-bytes-backup-substitution",
            self.original_document(),
        )
        self.assertEqual(restored.index, 1)

    def test_restore_primary_never_falls_back_to_corrupt_primary_backup(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:strict-primary", reader)
        reader.go_to(2)
        self.store.save("book:strict-primary", reader)

        self.path.write_bytes(b'{"schema_version":2,"generation":')
        tolerant = self.store.restore(
            "book:strict-primary",
            self.original_document(),
        )
        self.assertEqual(tolerant.index, 1)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.restore_primary(
                "book:strict-primary",
                self.original_document(),
            )
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.CORRUPT_STORE,
        )

    @unittest.skipIf(os.name == "nt", "Windows symlink creation requires environment-specific privileges")
    def test_symlink_store_is_rejected(self) -> None:
        real = Path(self.tempdir.name) / "real.json"
        real.write_text('{"schema_version":1,"entries":{}}', encoding="utf-8")
        self.path.parent.mkdir(parents=True)
        self.path.symlink_to(real)
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:one")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)

    def test_missing_lock_create_race_never_adopts_foreign_file(self) -> None:
        self.path.parent.mkdir(parents=True)
        foreign_bytes = b"user-owned-lock-bytes"
        real_open = os.open
        injected = False

        def foreign_lock_appears_before_exclusive_create(path, flags, mode=0o777, *args, **kwargs):
            nonlocal injected
            if (
                not injected
                and Path(path) == self.store._lock_path
                and flags & os.O_CREAT
                and flags & os.O_EXCL
            ):
                self.store._lock_path.write_bytes(foreign_bytes)
                injected = True
            return real_open(path, flags, mode, *args, **kwargs)

        with mock.patch(
            "acs.book_progress_store.os.open",
            side_effect=foreign_lock_appears_before_exclusive_create,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertEqual(self.store._lock_path.read_bytes(), foreign_bytes)
        self.assertFalse(self.path.exists())

    def test_new_lock_fsync_failure_is_stable_and_retryable(self) -> None:
        with mock.patch(
            "acs.book_progress_store.os.fsync",
            side_effect=OSError("simulated lock fsync failure"),
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertIsNone(caught.exception.__cause__)
        self.assertFalse(self.store._lock_path.exists())
        self.assertFalse(self.path.exists())

        # A transient initialization failure must not poison the canonical lock
        # pathname for every subsequent application start.
        self.assertFalse(self.store.has("book:one"))
        self.assertEqual(self.store._lock_path.read_bytes(), b"\0")

    def test_new_lock_short_marker_write_is_stable_and_retryable(self) -> None:
        with mock.patch(
            "acs.book_progress_store.os.write",
            return_value=0,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertIsNone(caught.exception.__cause__)
        self.assertFalse(self.store._lock_path.exists())
        self.assertFalse(self.path.exists())

        self.assertFalse(self.store.has("book:one"))
        self.assertEqual(self.store._lock_path.read_bytes(), b"\0")

    @unittest.skipIf(
        os.name == "nt",
        "replacing an open lock pathname is a POSIX-specific cleanup race probe",
    )
    def test_failed_lock_initialization_never_unlinks_substituted_foreign_path(self) -> None:
        self.path.parent.mkdir(parents=True)
        foreign = self.path.parent / "foreign-after-lock-create.bin"
        foreign_bytes = b"user-owned-lock-replacement"
        foreign.write_bytes(foreign_bytes)
        real_fsync = os.fsync
        injected = False

        def replace_lock_then_fail(descriptor: int) -> None:
            nonlocal injected
            if not injected:
                os.replace(foreign, self.store._lock_path)
                injected = True
                raise OSError("simulated lock durability failure")
            real_fsync(descriptor)

        with mock.patch(
            "acs.book_progress_store.os.fsync",
            side_effect=replace_lock_then_fail,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertEqual(self.store._lock_path.read_bytes(), foreign_bytes)
        self.assertFalse(self.path.exists())

    def test_lock_cleanup_last_window_substitution_preserves_foreign_bytes(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.store._lock_path.write_bytes(b"\0")
        expected = os.lstat(self.store._lock_path)
        foreign = self.path.parent / "foreign-lock-last-window.bin"
        foreign_bytes = b"foreign-lock-last-window"
        foreign.write_bytes(foreign_bytes)
        real_replace = os.replace
        injected = False

        def substitute_then_quarantine(source, destination):
            nonlocal injected
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                source_path == self.store._lock_path
                and ".cleanup-quarantine-" in destination_path.name
                and not injected
            ):
                real_replace(foreign, self.store._lock_path)
                injected = True
            return real_replace(source, destination)

        with mock.patch(
            "acs.book_progress_store.os.replace",
            side_effect=substitute_then_quarantine,
        ):
            self.store._discard_owned_lock_unlocked(
                self.store._lock_path,
                expected,
            )

        self.assertTrue(injected)
        self.assertFalse(self.store._lock_path.exists())
        quarantines = tuple(
            item
            for item in self.path.parent.iterdir()
            if item.name.startswith(
                f".{self.store._lock_path.name}.cleanup-quarantine-"
            )
        )
        self.assertEqual(len(quarantines), 1)
        self.assertEqual(quarantines[0].read_bytes(), foreign_bytes)

    def test_initializing_empty_lock_can_finish_on_same_inode(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.store._lock_path.write_bytes(b"")
        slept = False

        def finish_initialization(_seconds: float) -> None:
            nonlocal slept
            if slept:
                return
            slept = True
            with self.store._lock_path.open("r+b") as stream:
                stream.write(b"\0")
                stream.flush()
                os.fsync(stream.fileno())

        with mock.patch(
            "acs.book_progress_store.time.sleep",
            side_effect=finish_initialization,
        ):
            self.assertFalse(self.store.has("book:one"))

        self.assertTrue(slept)
        self.assertEqual(self.store._lock_path.read_bytes(), b"\0")
        self.assertFalse(self.path.exists())

    def test_initializing_empty_lock_replacement_fails_closed(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.store._lock_path.write_bytes(b"")
        replacement = self.store._lock_path.with_name("replacement-initializer.lock")
        replacement.write_bytes(b"\0")
        swapped = False

        def replace_during_wait(_seconds: float) -> None:
            nonlocal swapped
            if swapped:
                return
            swapped = True
            os.replace(replacement, self.store._lock_path)

        with mock.patch(
            "acs.book_progress_store.time.sleep",
            side_effect=replace_during_wait,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")

        self.assertTrue(swapped)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)
        self.assertEqual(self.store._lock_path.read_bytes(), b"\0")
        self.assertFalse(self.path.exists())

    def test_preexisting_empty_lock_is_rejected_without_initialization(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.store._lock_path.write_bytes(b"")

        with mock.patch(
            "acs.book_progress_store.time.sleep",
            return_value=None,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertEqual(self.store._lock_path.read_bytes(), b"")
        self.assertFalse(self.path.exists())

    def test_preexisting_wrong_lock_marker_is_rejected_without_mutation(self) -> None:
        self.path.parent.mkdir(parents=True)
        foreign_bytes = b"X"
        self.store._lock_path.write_bytes(foreign_bytes)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:one")

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertEqual(self.store._lock_path.read_bytes(), foreign_bytes)
        self.assertFalse(self.path.exists())

    def test_hardlinked_lock_is_rejected_without_mutating_peer(self) -> None:
        self.path.parent.mkdir(parents=True)
        peer = self.store._lock_path.with_name("user-owned-peer.bin")
        peer.write_bytes(b"")
        try:
            os.link(peer, self.store._lock_path)
        except (OSError, NotImplementedError):
            self.skipTest("hard-link creation is unavailable on this runner")

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:one")

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertEqual(peer.read_bytes(), b"")
        self.assertEqual(os.lstat(peer).st_nlink, 2)
        self.assertFalse(self.path.exists())

    def test_hardlinked_primary_is_rejected_without_mutating_peer(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:hardlinked-primary", reader)
        peer = self.path.parent / "user-owned-primary-peer.json"
        try:
            os.link(self.path, peer)
        except (OSError, NotImplementedError):
            self.skipTest("hard-link creation is unavailable on this runner")

        primary_bytes = self.path.read_bytes()
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.restore("book:hardlinked-primary", self.original_document())

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)
        self.assertEqual(self.path.read_bytes(), primary_bytes)
        self.assertEqual(peer.read_bytes(), primary_bytes)
        self.assertEqual(os.lstat(self.path).st_nlink, 2)

    def test_hardlinked_backup_is_rejected_during_explicit_recovery(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:hardlinked-backup", reader)
        reader.go_to(2)
        self.store.save("book:hardlinked-backup", reader)
        peer = self.path.parent / "user-owned-backup-peer.json"
        try:
            os.link(self.store.backup_path, peer)
        except (OSError, NotImplementedError):
            self.skipTest("hard-link creation is unavailable on this runner")
        backup_bytes = self.store.backup_path.read_bytes()
        self.path.unlink()

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.recover_from_backup()

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.backup_path.read_bytes(), backup_bytes)
        self.assertEqual(peer.read_bytes(), backup_bytes)
        self.assertEqual(os.lstat(self.store.backup_path).st_nlink, 2)

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

    def test_post_read_descriptor_close_failure_does_not_replace_success(self) -> None:
        reader = BookReader(self.original_document())
        self.store.save("book:read-close", reader)

        real_open = os.open
        real_close = os.close
        data_descriptor = None

        def capture_open(path: object, flags: int, mode: int = 0o777) -> int:
            nonlocal data_descriptor
            descriptor = real_open(path, flags, mode)
            if os.fspath(path) == os.fspath(self.path):
                data_descriptor = descriptor
            return descriptor

        def close_then_report_failure(descriptor: int) -> None:
            real_close(descriptor)
            if descriptor == data_descriptor:
                raise OSError("late read descriptor close failure")

        with (
            mock.patch(
                "acs.book_progress_store.os.open",
                side_effect=capture_open,
            ),
            mock.patch(
                "acs.book_progress_store.os.close",
                side_effect=close_then_report_failure,
            ),
        ):
            self.assertTrue(self.store.has("book:read-close"))

    def test_lock_descriptor_fstat_failure_is_stable_storage_error(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.store._lock_path.write_bytes(b"\0")

        with mock.patch(
            "acs.book_progress_store.os.fstat",
            side_effect=OSError("simulated lock descriptor metadata failure"),
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertIsNone(caught.exception.__cause__)
        self.assertEqual(self.store._lock_path.read_bytes(), b"\0")
        self.assertFalse(self.path.exists())

    def test_lock_validation_error_survives_cleanup_close_failure(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.store._lock_path.write_bytes(b"\0")
        replacement = self.store._lock_path.with_name(
            "replacement-close-failure.lock"
        )
        replacement.write_bytes(b"\0")

        real_open = os.open
        real_close = os.close
        opened_lock_descriptor = None
        swapped = False

        def replacing_open(path: object, flags: int, mode: int = 0o777) -> int:
            nonlocal opened_lock_descriptor, swapped
            if (
                not swapped
                and os.fspath(path) == os.fspath(self.store._lock_path)
            ):
                swapped = True
                os.replace(replacement, self.store._lock_path)
            descriptor = real_open(path, flags, mode)
            if os.fspath(path) == os.fspath(self.store._lock_path):
                opened_lock_descriptor = descriptor
            return descriptor

        def close_then_report_failure(descriptor: int) -> None:
            real_close(descriptor)
            if descriptor == opened_lock_descriptor:
                raise OSError("late failed-lock cleanup close failure")

        with (
            mock.patch(
                "acs.book_progress_store.os.open",
                side_effect=replacing_open,
            ),
            mock.patch(
                "acs.book_progress_store.os.close",
                side_effect=close_then_report_failure,
            ),
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertIsNone(caught.exception.__cause__)

    @unittest.skipIf(
        os.name == "nt",
        "replacing an actively locked pathname is a POSIX continuity probe",
    )
    def test_active_lock_path_split_before_publication_fails_without_primary_write(self) -> None:
        self.path.parent.mkdir(parents=True)
        displaced = self.path.parent / "book-progress.lock.displaced"
        replacement = self.path.parent / "replacement-active.lock"
        replacement.write_bytes(b"\0")

        with self.assertRaises(BookProgressStoreError) as caught:
            with self.store._exclusive_access():
                os.replace(self.store._lock_path, displaced)
                os.replace(replacement, self.store._lock_path)
                self.store._atomic_publish_bytes_unlocked(
                    self.path,
                    b"must-not-publish",
                    expected_target_raw=None,
                )

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store._lock_path.read_bytes(), b"\0")

    @unittest.skipIf(
        os.name == "nt",
        "replacing an actively locked pathname is a POSIX continuity probe",
    )
    def test_active_lock_split_after_replace_reports_durability_unknown(self) -> None:
        self.path.parent.mkdir(parents=True)
        displaced = self.path.parent / "book-progress.lock.displaced"
        replacement = self.path.parent / "replacement-active.lock"
        replacement.write_bytes(b"\0")
        real_publish = __import__(
            "acs.book_progress_store",
            fromlist=["_replace_published_path"],
        )._replace_published_path
        injected = False

        def publish_then_split_lock(source: Path, destination: Path) -> None:
            nonlocal injected
            real_publish(source, destination)
            if not injected:
                os.replace(self.store._lock_path, displaced)
                os.replace(replacement, self.store._lock_path)
                injected = True

        with self.assertRaises(BookProgressStoreError) as caught:
            with self.store._exclusive_access():
                with mock.patch(
                    "acs.book_progress_store._replace_published_path",
                    side_effect=publish_then_split_lock,
                ):
                    self.store._atomic_publish_bytes_unlocked(
                        self.path,
                        b"published-before-lock-loss",
                        expected_target_raw=None,
                    )

        self.assertTrue(injected)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
        )
        self.assertEqual(self.path.read_bytes(), b"published-before-lock-loss")
        self.assertEqual(self.store._lock_path.read_bytes(), b"\0")

    def test_lock_marker_is_rechecked_after_os_lock_acquisition(self) -> None:
        real_lock = self.store._lock_file_descriptor

        def corrupt_marker_after_lock(descriptor: int) -> None:
            real_lock(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.write(descriptor, b"X")
            os.fsync(descriptor)

        with mock.patch.object(
            self.store,
            "_lock_file_descriptor",
            side_effect=corrupt_marker_after_lock,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertEqual(self.store._lock_path.read_bytes(), b"X")
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

    def test_descriptor_read_oserror_is_stable_storage_error(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"schema_version":1,"entries":{}}', encoding="utf-8")

        with mock.patch(
            "acs.book_progress_store.os.fstat",
            side_effect=OSError("simulated descriptor metadata failure"),
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store._read_raw_file_unlocked(self.path, missing_ok=False)

        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertIsNone(caught.exception.__cause__)

    def test_read_detects_same_inode_change_after_final_descriptor_check(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"schema_version":1,"entries":{}}', encoding="utf-8")
        real_lstat = os.lstat
        path_checks = 0

        def mutate_on_final_path_check(path: object) -> os.stat_result:
            nonlocal path_checks
            if os.fspath(path) == os.fspath(self.path):
                path_checks += 1
                if path_checks == 3:
                    with self.path.open("ab") as stream:
                        stream.write(b" ")
            return real_lstat(path)

        with mock.patch(
            "acs.book_progress_store.os.lstat",
            side_effect=mutate_on_final_path_check,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store._read_raw_file_unlocked(self.path, missing_ok=False)

        self.assertEqual(path_checks, 3)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )

    def test_windows_path_confirmation_does_not_depend_on_cross_interface_ctime(self) -> None:
        self.path.parent.mkdir(parents=True)
        raw = b'{"schema_version":1,"entries":{}}'
        self.path.write_bytes(raw)
        real_lstat = os.lstat
        path_checks = 0

        class StatAlias:
            def __init__(self, current: os.stat_result) -> None:
                self._current = current
                self.st_ctime_ns = getattr(current, "st_ctime_ns", 0) + 1

            def __getattr__(self, name: str):
                return getattr(self._current, name)

        def alias_ctime_on_final_path_check(path: object) -> os.stat_result:
            nonlocal path_checks
            current = real_lstat(path)
            if os.fspath(path) == os.fspath(self.path):
                path_checks += 1
                if path_checks == 3:
                    return StatAlias(current)  # type: ignore[return-value]
            return current

        with (
            mock.patch(
                "acs.book_progress_store.os.lstat",
                side_effect=alias_ctime_on_final_path_check,
            ),
            mock.patch("acs.book_progress_store.os.name", "nt"),
        ):
            self.assertEqual(
                self.store._read_raw_file_unlocked(self.path, missing_ok=False),
                raw,
            )

        self.assertEqual(path_checks, 3)

    def test_windows_descriptor_read_rejects_same_metadata_byte_drift(self) -> None:
        self.path.parent.mkdir(parents=True)
        raw = b'{"schema_version":1,"entries":{}}'
        drifted = raw[:-1] + b" "
        self.assertEqual(len(raw), len(drifted))
        self.path.write_bytes(raw)
        real_fdopen = os.fdopen
        read_calls = 0

        class DriftingDescriptorStream:
            def __init__(self, stream):
                self._stream = stream

            def __enter__(self):
                self._stream.__enter__()
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return self._stream.__exit__(exc_type, exc_value, traceback)

            def read(self, limit):
                nonlocal read_calls
                read_calls += 1
                return raw if read_calls == 1 else drifted

            def seek(self, offset, whence=os.SEEK_SET):
                return self._stream.seek(offset, whence)

        def drifting_fdopen(descriptor, mode, closefd=True):
            return DriftingDescriptorStream(
                real_fdopen(descriptor, mode, closefd=closefd)
            )

        with (
            mock.patch(
                "acs.book_progress_store.os.fdopen",
                side_effect=drifting_fdopen,
            ),
            mock.patch("acs.book_progress_store.os.name", "nt"),
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store._read_raw_file_unlocked(
                    self.path,
                    missing_ok=False,
                )

        self.assertEqual(read_calls, 2)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertIsNone(caught.exception.__cause__)

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

    def test_existing_primary_disappearance_between_lstat_and_open_fails_closed_even_when_missing_ok(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"schema_version":1,"entries":{}}', encoding="utf-8")
        real_open = os.open
        removed = False

        def disappearing_open(path: object, flags: int, mode: int = 0o777) -> int:
            nonlocal removed
            if not removed and os.fspath(path) == os.fspath(self.path):
                removed = True
                self.path.unlink()
            return real_open(path, flags, mode)

        with mock.patch("acs.book_progress_store.os.open", side_effect=disappearing_open):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")

        self.assertTrue(removed)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertIsNone(caught.exception.__cause__)
        self.assertFalse(self.path.exists())


    def test_missing_primary_appearance_between_lstat_and_open_fails_closed(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.assertFalse(self.path.exists())
        real_open = os.open
        inserted = False

        def appearing_open(path: object, flags: int, mode: int = 0o777) -> int:
            nonlocal inserted
            if not inserted and os.fspath(path) == os.fspath(self.path):
                inserted = True
                self.path.write_text(
                    '{"schema_version":1,"entries":{}}',
                    encoding="utf-8",
                )
            return real_open(path, flags, mode)

        with mock.patch("acs.book_progress_store.os.open", side_effect=appearing_open):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.has("book:one")

        self.assertTrue(inserted)
        self.assertEqual(
            caught.exception.code,
            BookProgressStoreErrorCode.IO_FAILURE,
        )
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(self.path.is_file())

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

        def capture_lock_descriptor(**kwargs) -> int:
            nonlocal lock_descriptor
            lock_descriptor = real_open_lock(**kwargs)
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
