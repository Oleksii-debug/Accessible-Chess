from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest

from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument, Heading, Paragraph
from acs.bookreader import BookReader


class V2AuditBBookProgressMultiwriterTests(unittest.TestCase):
    @staticmethod
    def _reader(index: int) -> BookReader:
        document = BookDocument(
            "Concurrent progress",
            blocks=[
                Heading(text="Chapter", level=1, block_id="chapter"),
                Paragraph(text="One", block_id="one"),
                Paragraph(text="Two", block_id="two"),
            ],
        )
        reader = BookReader(document)
        reader.go_to(index)
        return reader

    def test_two_successful_store_instances_must_not_silently_lose_one_update(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "state" / "book-progress.json"
            first = BookProgressStore(path)
            second = BookProgressStore(path)
            barrier = threading.Barrier(2)
            failures: list[BaseException] = []

            def gate_load(store: BookProgressStore) -> None:
                original = store._load_payload_unlocked

                def synchronized_load():
                    payload = original()
                    barrier.wait(timeout=10)
                    return payload

                store._load_payload_unlocked = synchronized_load  # type: ignore[method-assign]

            gate_load(first)
            gate_load(second)

            def save(store: BookProgressStore, key: str, index: int) -> None:
                try:
                    store.save(key, self._reader(index))
                except BaseException as exc:  # evidence collects either worker failure
                    failures.append(exc)

            left = threading.Thread(target=save, args=(first, "book:first", 1))
            right = threading.Thread(target=save, args=(second, "book:second", 2))
            left.start()
            right.start()
            left.join(15)
            right.join(15)

            self.assertFalse(left.is_alive() or right.is_alive(), "audit workers must terminate")
            self.assertEqual(failures, [], "both independent saves are reported successful")

            persisted = json.loads(path.read_text(encoding="utf-8"))
            entries = persisted["entries"]
            self.assertEqual(
                set(entries),
                {"book:first", "book:second"},
                "AB-V2-011: two successful BookProgressStore instances can read the same base and last os.replace silently discards the other committed update",
            )


if __name__ == "__main__":
    unittest.main()
