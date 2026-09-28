from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import unittest

from acs.book_progress_store import (
    BOOK_PROGRESS_STORE_SCHEMA_VERSION,
    BookProgressStore,
    BookProgressStoreError,
    BookProgressStoreErrorCode,
)
from acs.bookdocument import BookDocument, Heading, Paragraph
from acs.bookreader import BookReader


def _document(*, include_after: bool = True) -> BookDocument:
    blocks = [
        Heading(text="Chapter", level=1, block_id="chapter"),
        Paragraph(text="One", block_id="one"),
        Paragraph(text="Two", block_id="two"),
    ]
    if include_after:
        blocks.append(Paragraph(text="After", block_id="after"))
    return BookDocument("Concurrent progress", blocks=blocks)


def _reader(index: int, *, bookmark: str | None = None) -> BookReader:
    reader = BookReader(_document())
    reader.go_to(index)
    if bookmark is not None:
        reader.save_return_point(bookmark)
    return reader


def _process_save(path: str, key: str, index: int, barrier, queue) -> None:
    try:
        store = BookProgressStore(path)
        reader = _reader(index)
        barrier.wait(timeout=15)
        store.save(key, reader)
        queue.put(("ok", key))
    except BaseException as exc:  # pragma: no cover - child evidence reaches parent
        queue.put(("error", type(exc).__name__, str(exc)))
        raise


def _process_crash_while_locked(path: str, ready) -> None:
    store = BookProgressStore(path)
    with store._exclusive_access():  # deliberate white-box crash-recovery proof
        ready.set()
        os._exit(17)


class BookProgressProductionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "state" / "book-progress.json"

    def test_two_store_instances_concurrently_preserve_both_successful_updates(self) -> None:
        first = BookProgressStore(self.path)
        second = BookProgressStore(self.path)
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def write(store: BookProgressStore, key: str, index: int) -> None:
            try:
                barrier.wait(timeout=10)
                store.save(key, _reader(index))
            except BaseException as exc:
                errors.append(exc)

        left = threading.Thread(target=write, args=(first, "book:first", 1))
        right = threading.Thread(target=write, args=(second, "book:second", 2))
        left.start()
        right.start()
        left.join(20)
        right.join(20)

        self.assertFalse(left.is_alive() or right.is_alive())
        self.assertEqual(errors, [])
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(set(payload["entries"]), {"book:first", "book:second"})
        self.assertEqual(payload["schema_version"], BOOK_PROGRESS_STORE_SCHEMA_VERSION)
        self.assertEqual(payload["generation"], 2)

    def test_two_processes_concurrently_preserve_both_successful_updates(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        barrier = ctx.Barrier(2)
        queue = ctx.Queue()
        left = ctx.Process(
            target=_process_save,
            args=(str(self.path), "book:first", 1, barrier, queue),
        )
        right = ctx.Process(
            target=_process_save,
            args=(str(self.path), "book:second", 2, barrier, queue),
        )
        left.start()
        right.start()
        left.join(30)
        right.join(30)

        self.assertFalse(left.is_alive() or right.is_alive())
        self.assertEqual(left.exitcode, 0)
        self.assertEqual(right.exitcode, 0)
        results = {queue.get(timeout=10), queue.get(timeout=10)}
        self.assertEqual(results, {("ok", "book:first"), ("ok", "book:second")})
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(set(payload["entries"]), {"book:first", "book:second"})
        self.assertEqual(payload["generation"], 2)

    def test_save_and_remove_race_do_not_resurrect_or_drop_unrelated_books(self) -> None:
        first = BookProgressStore(self.path)
        second = BookProgressStore(self.path)
        first.save("book:remove", _reader(1))
        first.save("book:keep", _reader(2))
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def remove() -> None:
            try:
                barrier.wait(timeout=10)
                self.assertTrue(first.remove("book:remove"))
            except BaseException as exc:
                errors.append(exc)

        def save() -> None:
            try:
                barrier.wait(timeout=10)
                second.save("book:new", _reader(3))
            except BaseException as exc:
                errors.append(exc)

        left = threading.Thread(target=remove)
        right = threading.Thread(target=save)
        left.start()
        right.start()
        left.join(20)
        right.join(20)
        self.assertEqual(errors, [])

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(set(payload["entries"]), {"book:keep", "book:new"})
        self.assertFalse(first.has("book:remove"))
        self.assertTrue(second.has("book:keep"))
        self.assertTrue(second.has("book:new"))

    def test_process_crash_releases_interprocess_lock_and_next_save_recovers(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        ready = ctx.Event()
        crashing = ctx.Process(target=_process_crash_while_locked, args=(str(self.path), ready))
        crashing.start()
        self.assertTrue(ready.wait(timeout=15))
        crashing.join(20)
        self.assertFalse(crashing.is_alive())
        self.assertEqual(crashing.exitcode, 17)

        store = BookProgressStore(self.path)
        store.save("book:after-crash", _reader(2))
        self.assertEqual(store.restore("book:after-crash", _document()).index, 2)

    def test_schema_v1_is_preserved_and_migrates_on_next_mutation(self) -> None:
        legacy_reader = _reader(2, bookmark="return")
        legacy_payload = {
            "schema_version": 1,
            "entries": {"book:legacy": legacy_reader.snapshot()},
        }
        legacy_bytes = json.dumps(
            legacy_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(legacy_bytes)

        store = BookProgressStore(self.path)
        reopened = store.restore("book:legacy", _document())
        self.assertEqual(reopened.index, 2)
        self.assertEqual(reopened.restore_return_point("return").block_id, "two")

        store.save("book:new", _reader(3))
        migrated = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(migrated["schema_version"], BOOK_PROGRESS_STORE_SCHEMA_VERSION)
        self.assertEqual(migrated["generation"], 1)
        self.assertEqual(set(migrated["entries"]), {"book:legacy", "book:new"})
        self.assertEqual(store.backup_path.read_bytes(), legacy_bytes)
        self.assertEqual(store.restore("book:legacy", _document()).index, 2)

    def test_generation_and_previous_valid_backup_advance_deterministically(self) -> None:
        store = BookProgressStore(self.path)
        store.save("book:one", _reader(1))
        first_bytes = self.path.read_bytes()
        first = json.loads(first_bytes)
        self.assertEqual(first["generation"], 1)
        self.assertFalse(store.backup_path.exists())

        store.save("book:two", _reader(2))
        second_bytes = self.path.read_bytes()
        second = json.loads(second_bytes)
        self.assertEqual(second["generation"], 2)
        self.assertEqual(store.backup_path.read_bytes(), first_bytes)

        store.remove("book:one")
        third = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(third["generation"], 3)
        self.assertEqual(store.backup_path.read_bytes(), second_bytes)
        self.assertEqual(set(third["entries"]), {"book:two"})

    def test_corrupt_primary_can_resume_from_backup_but_mutation_fails_until_recovery(self) -> None:
        store = BookProgressStore(self.path)
        store.save("book:one", _reader(1))
        store.save("book:one", _reader(3))
        previous_valid = store.backup_path.read_bytes()
        corrupt = b'{"schema_version":2,"generation":2,"entries":'
        self.path.write_bytes(corrupt)

        recovered_reader = store.restore("book:one", _document())
        self.assertEqual(recovered_reader.index, 1)
        self.assertTrue(store.has("book:one"))

        with self.assertRaises(BookProgressStoreError) as caught:
            store.save("book:two", _reader(2))
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(self.path.read_bytes(), corrupt)

        self.assertTrue(store.recover_from_backup())
        self.assertEqual(self.path.read_bytes(), previous_valid)
        self.assertFalse(store.recover_from_backup())
        self.assertEqual(store.restore("book:one", _document()).index, 1)

    def test_future_schema_never_rolls_back_through_older_backup(self) -> None:
        store = BookProgressStore(self.path)
        store.save("book:one", _reader(1))
        store.save("book:one", _reader(2))
        self.assertTrue(store.backup_path.exists())
        self.path.write_text(
            json.dumps({"schema_version": 999, "entries": {}}),
            encoding="utf-8",
        )

        with self.assertRaises(BookProgressStoreError) as caught:
            store.restore("book:one", _document())
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.UNSUPPORTED_SCHEMA)
        with self.assertRaises(BookProgressStoreError) as caught_recovery:
            store.recover_from_backup()
        self.assertEqual(caught_recovery.exception.code, BookProgressStoreErrorCode.UNSUPPORTED_SCHEMA)

    def test_noncooperating_external_change_is_not_overwritten(self) -> None:
        store = BookProgressStore(self.path)
        store.save("book:one", _reader(1))
        existing = json.loads(self.path.read_text(encoding="utf-8"))
        external = dict(existing)
        external["generation"] = existing["generation"] + 1
        external_entries = dict(existing["entries"])
        external_entries["book:external"] = existing["entries"]["book:one"]
        external["entries"] = external_entries
        external_bytes = json.dumps(
            external,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        original_publish = store._atomic_publish_bytes_unlocked
        injected = False

        def publish(target: Path, encoded: bytes) -> None:
            nonlocal injected
            original_publish(target, encoded)
            if target == store.backup_path and not injected:
                injected = True
                self.path.write_bytes(external_bytes)

        store._atomic_publish_bytes_unlocked = publish  # type: ignore[method-assign]
        with self.assertRaises(BookProgressStoreError) as caught:
            store.save("book:two", _reader(2))
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(self.path.read_bytes(), external_bytes)
        self.assertEqual(set(json.loads(self.path.read_text())["entries"]), {"book:one", "book:external"})

    def test_changed_book_target_fails_closed_without_mutating_progress(self) -> None:
        store = BookProgressStore(self.path)
        reader = _reader(3)
        reader.save_return_point("last")
        store.save("book:stable", reader)
        persisted = self.path.read_bytes()

        with self.assertRaises(LookupError):
            store.restore("book:stable", _document(include_after=False))
        self.assertEqual(self.path.read_bytes(), persisted)

    def test_stale_temp_files_are_cleaned_before_next_access(self) -> None:
        store = BookProgressStore(self.path)
        self.path.parent.mkdir(parents=True)
        stale_primary = self.path.parent / f".{self.path.name}.dead.tmp"
        stale_backup = self.path.parent / f".{store.backup_path.name}.dead.tmp"
        stale_primary.write_bytes(b"partial")
        stale_backup.write_bytes(b"partial")

        store.save("book:one", _reader(1))
        self.assertFalse(stale_primary.exists())
        self.assertFalse(stale_backup.exists())
        self.assertEqual(store.restore("book:one", _document()).index, 1)


if __name__ == "__main__":
    unittest.main()
