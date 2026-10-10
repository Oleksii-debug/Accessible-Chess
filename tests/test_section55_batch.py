"""Synthetic local-only Section-55 bounded batch and crash-replay tests."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from acs.bookdocument import BookDocument, Paragraph
from acs.chess_braille_factory import BrailleFactoryError
from tools.section55_batch import process_batch


class FakeLouis(types.ModuleType):
    ucBrl = 1
    dotsIO = 2

    @staticmethod
    def translateString(tables, source, mode):
        if mode != 3 or not tables:
            raise ValueError("Invalid synthetic Liblouis call")
        return "\u2801" * len(source)


def setup_queue(root: Path, count: int = 2) -> Path:
    table = root / "synthetic.ctb"
    table.write_text("# synthetic fake table\n", encoding="utf-8")
    src = root / "input.json"
    src.write_text(json.dumps(BookDocument(
        title="Chess", blocks=[Paragraph(text="Knight")]
    ).as_dict()), encoding="utf-8")
    jobs = [{
        "id": "book-" + str(index + 1),
        "book_json": str(src),
        "table_file": str(table),
        "table_version": "fixture-v1",
        "language": "en",
        "device_model": "NOT-QUALIFIED",
        "cells_per_line": 20,
        "lines_per_page": 10,
        "rights_confirmed": True,
        "rights_basis": "Synthetic author-owned test fixture",
        "emit_brf": True,
    } for index in range(count)]
    manifest = root / "queue.json"
    manifest.write_text(json.dumps({"schema_version": 1, "jobs": jobs}), encoding="utf-8")
    return manifest


class TestSection55LocalBatch(unittest.TestCase):
    def test_batch_one_per_run_restarts_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = setup_queue(root)
            with patch.dict("sys.modules", {"louis": FakeLouis("louis")}):
                first = process_batch(manifest, root, max_per_run=1)
                self.assertEqual(first, (1, 1))
                original = (root / "book-1" / "chess-book-unverified.pef").read_bytes()
                second = process_batch(manifest, root, max_per_run=1)
                self.assertEqual(second, (1, 0))
                third = process_batch(manifest, root, max_per_run=1)
                self.assertEqual(third, (0, 0))
            self.assertEqual(original, (root / "book-1" / "chess-book-unverified.pef").read_bytes())
            self.assertFalse((root / ".section55-batch.lock").exists())
            journal = json.loads((root / ".section55-batch-journal.json").read_text("utf-8"))
            self.assertEqual(set(journal["completed"]), {"book-1", "book-2"})

    def test_optional_html_is_fingerprinted_and_crash_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = setup_queue(root, count=1)
            raw = json.loads(manifest.read_text("utf-8"))
            raw["jobs"][0]["emit_html"] = True
            manifest.write_text(json.dumps(raw), encoding="utf-8")
            with patch.dict("sys.modules", {"louis": FakeLouis("louis")}):
                self.assertEqual(process_batch(manifest, root, max_per_run=1), (1, 0))
                html_path = root / "book-1" / "chess-book-unverified.html"
                self.assertTrue(html_path.is_file())
                data = html_path.read_bytes()
                self.assertIn(b"Original accessible book text", data)
                self.assertEqual(process_batch(manifest, root, max_per_run=1), (0, 0))
                html_path.write_bytes(data + b"altered")
                with self.assertRaises(BrailleFactoryError):
                    process_batch(manifest, root, max_per_run=1)

    def test_crash_after_publish_before_journal_replays_verified_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = setup_queue(root, count=1)
            with patch.dict("sys.modules", {"louis": FakeLouis("louis")}):
                self.assertEqual(process_batch(manifest, root, max_per_run=1), (1, 0))
                (root / ".section55-batch-journal.json").unlink()
                self.assertEqual(process_batch(manifest, root, max_per_run=1), (0, 0))

    def test_tampered_package_refused_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = setup_queue(root, count=1)
            with patch.dict("sys.modules", {"louis": FakeLouis("louis")}):
                self.assertEqual(process_batch(manifest, root, max_per_run=1), (1, 0))
                target = root / "book-1" / "chess-book-unverified.pef"
                target.write_bytes(target.read_bytes() + b"corrupted")
                with self.assertRaises(BrailleFactoryError):
                    process_batch(manifest, root, max_per_run=1)
            self.assertTrue(target.read_bytes().endswith(b"corrupted"))

    def test_changed_queue_revision_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = setup_queue(root, count=1)
            with patch.dict("sys.modules", {"louis": FakeLouis("louis")}):
                self.assertEqual(process_batch(manifest, root, max_per_run=1), (1, 0))
                payload = json.loads(manifest.read_text("utf-8"))
                payload["jobs"][0]["rights_basis"] = "Changed revision"
                manifest.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(BrailleFactoryError):
                    process_batch(manifest, root, max_per_run=1)

    def test_forged_journal_completion_is_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = setup_queue(root, count=1)
            with patch.dict("sys.modules", {"louis": FakeLouis("louis")}):
                self.assertEqual(process_batch(manifest, root, max_per_run=1), (1, 0))
            journal_path = root / ".section55-batch-journal.json"
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            journal["completed"]["foreign"] = {
                "source_sha256": "a" * 64,
                "pef_sha256": "b" * 64,
                "brf_sha256": None,
            }
            journal_path.write_text(json.dumps(journal), encoding="utf-8")
            with self.assertRaises(BrailleFactoryError):
                process_batch(manifest, root, max_per_run=1)
            self.assertFalse((root / ".section55-batch.lock").exists())

    def test_stale_lock_requires_review_and_preserves_other_worker_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = setup_queue(root, count=1)
            lock = root / ".section55-batch.lock"
            lock.write_text("another worker")
            with self.assertRaises(BrailleFactoryError):
                process_batch(manifest, root, max_per_run=1)
            self.assertEqual(lock.read_text(), "another worker")

    def test_unsafe_id_and_unbounded_job_count_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = setup_queue(root, count=1)
            content = json.loads(manifest.read_text("utf-8"))
            content["jobs"][0]["id"] = "../escape"
            manifest.write_text(json.dumps(content), encoding="utf-8")
            with self.assertRaises(BrailleFactoryError):
                process_batch(manifest, root, max_per_run=1)
            self.assertFalse((root / ".section55-batch.lock").exists())

    def test_bounded_run_limit_cannot_be_bypassed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = setup_queue(root, count=1)
            for invalid in (0, 5, True, -1):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(BrailleFactoryError):
                        process_batch(manifest, root, max_per_run=invalid)


if __name__ == "__main__":
    unittest.main()
