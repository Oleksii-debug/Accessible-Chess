from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.book_progress_store import (
    BookProgressStore,
    BookProgressStoreError,
    BookProgressStoreErrorCode,
    _snapshot_copy,
    _validate_payload,
)
from acs.bookdocument import BookDocument, Heading
from acs.bookreader import BookReader


class BookProgressPassiveIngressCurrentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name) / "not-created-yet"
        self.store = BookProgressStore(self.root / "book-progress.json")

    @staticmethod
    def _document() -> BookDocument:
        return BookDocument(
            "Progress ingress",
            blocks=[Heading(text="Chapter", level=1, block_id="chapter")],
        )

    def test_save_rejects_reader_subclass_before_snapshot_or_storage_access(self) -> None:
        class HostileReader(BookReader):
            touched = False

            def snapshot(self):
                type(self).touched = True
                raise AssertionError("rejected BookReader subclass snapshot must not execute")

        reader = HostileReader(self._document())

        with self.assertRaisesRegex(TypeError, "^reader must be BookReader$"):
            self.store.save("book:hostile-reader", reader)

        self.assertFalse(HostileReader.touched)
        self.assertFalse(self.root.exists())

    def test_restore_boundaries_reject_document_subclass_before_storage_access(self) -> None:
        class HostileDocument(BookDocument):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if type(self).armed and name in {"as_dict", "blocks", "warnings", "title"}:
                    type(self).touched = True
                    raise AssertionError("rejected BookDocument subclass must remain passive")
                return super().__getattribute__(name)

        document = HostileDocument(
            "Hostile restore",
            blocks=[Heading(text="Chapter", level=1, block_id="chapter")],
        )
        HostileDocument.armed = True

        operations = (
            self.store.restore,
            self.store.restore_primary,
            self.store.validated_recovery_revisions,
            self.store.validated_backup_revision,
        )
        for operation in operations:
            HostileDocument.touched = False
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(TypeError, "^document must be BookDocument$"):
                    operation("book:hostile-document", document)
                self.assertFalse(HostileDocument.touched)
                self.assertFalse(self.root.exists())

    def test_persisted_mapping_ingress_rejects_active_objects_without_hooks(self) -> None:
        class ActiveMapping(dict):
            def __init__(self, *args, **kwargs) -> None:
                dict.__init__(self, *args, **kwargs)
                self.touched = False

            def _touch(self):
                self.touched = True
                raise AssertionError("rejected mapping hook must not execute")

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
                "current_target": "block:chapter",
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

    def test_active_progress_field_keys_are_rejected_before_hash_or_equality(self) -> None:
        touched: list[str] = []

        class ActiveKey(str):
            def __hash__(self):
                touched.append("hash")
                return str.__hash__(self)

            def __eq__(self, other):
                touched.append("eq")
                return str.__eq__(self, other)

        snapshot_key = ActiveKey("schema_version")
        snapshot = {
            snapshot_key: 2,
            "current_target": "block:chapter",
            "return_points": {},
            "fallback_digests": {},
        }
        touched.clear()
        with self.assertRaises(BookProgressStoreError) as snapshot_error:
            _snapshot_copy(snapshot)
        self.assertEqual(
            snapshot_error.exception.code,
            BookProgressStoreErrorCode.CORRUPT_STORE,
        )
        self.assertEqual(touched, [])

        root_key = ActiveKey("schema_version")
        root = {root_key: 2, "generation": 0, "entries": {}}
        touched.clear()
        with self.assertRaises(BookProgressStoreError) as root_error:
            _validate_payload(root)
        self.assertEqual(
            root_error.exception.code,
            BookProgressStoreErrorCode.CORRUPT_STORE,
        )
        self.assertEqual(touched, [])

    def test_v2_payload_missing_generation_fails_closed_with_store_error(self) -> None:
        with self.assertRaises(BookProgressStoreError) as raised:
            _validate_payload({"schema_version": 2, "entries": {}})

        self.assertEqual(
            raised.exception.code,
            BookProgressStoreErrorCode.CORRUPT_STORE,
        )
        self.assertIn("generation is missing", str(raised.exception))

    def test_snapshot_nested_active_mappings_are_rejected_before_json_hooks(self) -> None:
        class ActiveNestedDict(dict):
            touched = False

            def _touch(self):
                type(self).touched = True
                raise AssertionError("nested mapping JSON hook must not execute")

            def items(self):
                return self._touch()

            def __iter__(self):
                return self._touch()

            def __len__(self):
                return self._touch()

            def __getitem__(self, key):
                return self._touch()

        for field in ("return_points", "fallback_digests"):
            with self.subTest(field=field):
                ActiveNestedDict.touched = False
                snapshot = {
                    "schema_version": 2,
                    "current_target": "block:chapter",
                    "return_points": {},
                    "fallback_digests": {},
                }
                snapshot[field] = ActiveNestedDict({})
                with self.assertRaises(BookProgressStoreError) as raised:
                    _snapshot_copy(snapshot)
                self.assertEqual(
                    raised.exception.code,
                    BookProgressStoreErrorCode.CORRUPT_STORE,
                )
                self.assertFalse(ActiveNestedDict.touched)

    def test_exact_reader_and_document_keep_round_trip_semantics(self) -> None:
        document = self._document()
        reader = BookReader(document)
        saved = self.store.save("book:exact", reader)

        self.assertEqual(saved["current_target"], "block:chapter")
        restored = self.store.restore("book:exact", self._document())
        self.assertEqual(restored.location().block_id, "chapter")


if __name__ == "__main__":
    unittest.main()
