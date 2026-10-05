from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.import_contract import SourceFingerprint
from acs.pgn_document import (
    PgnConcurrentWriteError,
    PgnDocumentError,
    PgnDocumentErrorCode,
    PgnDocumentSession,
)
from acs.pgn_save_snapshot import (
    PgnSaveMode,
    capture_pgn_save_snapshot,
    commit_pgn_save_publication,
    expected_pgn_destination_sha256,
    publish_pgn_save_snapshot,
)
from acs.pgn_service import save_pgn_atomic as canonical_save_pgn_atomic


DOCUMENT = '''[Event "Snapshot Base"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 1-0
'''

SECOND_DOCUMENT = '''[Event "Second Session"]
[White "Gamma"]
[Black "Delta"]
[Result "*"]

1. d4 d5 *
'''


class PgnSaveSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_document(self, name: str = "source.pgn", text: str = DOCUMENT) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def test_save_of_older_snapshot_advances_source_but_keeps_newer_edit_dirty(self) -> None:
        source = self.write_document()
        session = PgnDocumentSession.open(source)
        session.edit_tag("Event", "Snapshot Generation")
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE)

        session.edit_tag("Event", "Newer In Memory")
        publication = publish_pgn_save_snapshot(snapshot)
        committed = commit_pgn_save_publication(session, publication)

        self.assertIn("Snapshot Generation", source.read_text(encoding="utf-8"))
        self.assertNotIn("Newer In Memory", source.read_text(encoding="utf-8"))
        self.assertIn("Newer In Memory", session.copy_pgn())
        self.assertTrue(committed.dirty)
        self.assertTrue(session.dirty)
        self.assertEqual(session.source, publication.saved)

        # The next Save must compare against the generation just published by
        # the worker, not the stale pre-worker source fingerprint.
        second = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE)
        second_publication = publish_pgn_save_snapshot(second)
        commit_pgn_save_publication(session, second_publication)
        self.assertIn("Newer In Memory", source.read_text(encoding="utf-8"))
        self.assertFalse(session.dirty)

    def test_capture_detaches_source_provenance_from_snapshot_mutation(self) -> None:
        source = self.write_document()
        session = PgnDocumentSession.open(source)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE)
        source_before = session.source

        self.assertIsNotNone(snapshot.source_before)
        self.assertEqual(snapshot.source_before, source_before)
        assert snapshot.source_before is not None
        object.__setattr__(snapshot.source_before, "sha256", "f" * 64)
        object.__setattr__(snapshot.source_before, "path", "attacker-snapshot.pgn")

        self.assertEqual(session.source, source_before)
        self.assertEqual(Path(session.source.path), source)

    def test_committed_publication_does_not_alias_worker_fingerprint(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "detached-publication.pgn"
        publication = publish_pgn_save_snapshot(snapshot, path=target)
        published_identity = SourceFingerprint(
            path=publication.saved.path,
            size=publication.saved.size,
            sha256=publication.saved.sha256,
            suffix=publication.saved.suffix,
        )

        commit_pgn_save_publication(session, publication)
        self.assertEqual(session.source, published_identity)

        object.__setattr__(publication.saved, "sha256", "e" * 64)
        object.__setattr__(publication.saved, "path", "attacker-publication.pgn")
        self.assertEqual(session.source, published_identity)
        self.assertEqual(Path(session.source.path), target)

    def test_malformed_publication_provenance_fails_before_session_rebind(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "malformed-publication.pgn"
        publication = publish_pgn_save_snapshot(snapshot, path=target)
        object.__setattr__(publication.saved, "sha256", object())

        with self.assertRaises(TypeError):
            commit_pgn_save_publication(session, publication)

        self.assertIsNone(session.source)
        self.assertTrue(session.dirty)
        self.assertTrue(target.exists())

    def test_save_source_cas_failure_does_not_mutate_live_session(self) -> None:
        source = self.write_document()
        session = PgnDocumentSession.open(source)
        session.edit_tag("Event", "Local Pending")
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE)
        source_before = session.source

        external = DOCUMENT.replace("Snapshot Base", "External Newer Generation")
        source.write_text(external, encoding="utf-8", newline="\n")

        with self.assertRaises(PgnConcurrentWriteError):
            publish_pgn_save_snapshot(snapshot)
        self.assertEqual(session.source, source_before)
        self.assertTrue(session.dirty)
        self.assertIn("Local Pending", session.copy_pgn())
        self.assertIn("External Newer Generation", source.read_text(encoding="utf-8"))

    def test_save_as_of_older_snapshot_keeps_newer_edit_dirty(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        session.edit_tag("Event", "Edited During Save As")

        target = self.root / "saved-as.pgn"
        publication = publish_pgn_save_snapshot(snapshot, path=target)
        commit_pgn_save_publication(session, publication)

        self.assertIn("Snapshot Base", target.read_text(encoding="utf-8"))
        self.assertIn("Edited During Save As", session.copy_pgn())
        self.assertEqual(Path(session.source.path), Path(publication.saved.path))
        self.assertTrue(session.view().source_overwrite_safe)
        self.assertTrue(session.dirty)

    def test_save_as_destination_cas_failure_does_not_publish_or_rebind_session(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.write_document("existing-race.pgn", SECOND_DOCUMENT)
        expected = expected_pgn_destination_sha256(target)

        external = SECOND_DOCUMENT.replace("Second Session", "External Replacement")
        target.write_text(external, encoding="utf-8", newline="\n")

        with self.assertRaises(PgnConcurrentWriteError):
            publish_pgn_save_snapshot(
                snapshot,
                path=target,
                overwrite=True,
                expected_sha256=expected,
            )
        self.assertIsNone(session.source)
        self.assertTrue(session.dirty)
        self.assertIn("External Replacement", target.read_text(encoding="utf-8"))

    def test_stale_save_as_completion_cannot_replace_newer_source(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        older = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        newer = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)

        old_publication = publish_pgn_save_snapshot(older, path=self.root / "old.pgn")
        new_publication = publish_pgn_save_snapshot(newer, path=self.root / "new.pgn")
        commit_pgn_save_publication(session, new_publication)

        with self.assertRaises(PgnDocumentError) as caught:
            commit_pgn_save_publication(session, old_publication)
        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.CONTEXT_STALE)
        self.assertEqual(session.source, new_publication.saved)

    def test_publication_cannot_commit_to_a_different_session(self) -> None:
        first = PgnDocumentSession.from_text(DOCUMENT)
        second = PgnDocumentSession.from_text(SECOND_DOCUMENT)
        snapshot = capture_pgn_save_snapshot(first, mode=PgnSaveMode.SAVE_AS)
        publication = publish_pgn_save_snapshot(snapshot, path=self.root / "first.pgn")

        with self.assertRaises(PgnDocumentError) as caught:
            commit_pgn_save_publication(second, publication)
        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.CONTEXT_STALE)
        self.assertIsNone(second.source)
        self.assertIn("Second Session", second.copy_pgn())

    def test_mutated_detached_snapshot_fails_before_publication(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        # PgnGame DTOs are mutable by design.  A worker boundary therefore
        # revalidates the detached graph against its captured canonical digest.
        snapshot.games[0].tags["Event"] = "Tampered Snapshot"
        target = self.root / "must-not-exist.pgn"

        with self.assertRaises(PgnDocumentError) as caught:
            publish_pgn_save_snapshot(snapshot, path=target)
        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.CONTEXT_STALE)
        self.assertFalse(target.exists())

    def test_worker_writer_receives_private_copy_not_public_snapshot_graph(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "private-copy.pgn"

        def writer(path, games, *, overwrite=False, expected_sha256=None):
            self.assertIsNot(games, snapshot.games)
            # Mutating the caller-retained public snapshot after the validation
            # point must not affect the graph being consumed by the writer.
            snapshot.games[0].tags["Event"] = "Late Caller Mutation"
            return canonical_save_pgn_atomic(
                path,
                games,
                overwrite=overwrite,
                expected_sha256=expected_sha256,
            )

        with patch("acs.pgn_save_snapshot.save_pgn_atomic", side_effect=writer):
            publication = publish_pgn_save_snapshot(snapshot, path=target)
        commit_pgn_save_publication(session, publication)

        text = target.read_text(encoding="utf-8")
        self.assertIn("Snapshot Base", text)
        self.assertNotIn("Late Caller Mutation", text)

    def test_existing_save_as_target_requires_worker_computed_generation(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.write_document("existing.pgn", SECOND_DOCUMENT)

        with self.assertRaises(PgnDocumentError) as caught:
            publish_pgn_save_snapshot(snapshot, path=target, overwrite=True)
        self.assertEqual(
            caught.exception.code,
            PgnDocumentErrorCode.DESTINATION_VERSION_REQUIRED,
        )
        self.assertIn("Second Session", target.read_text(encoding="utf-8"))

        expected = expected_pgn_destination_sha256(target)
        publication = publish_pgn_save_snapshot(
            snapshot,
            path=target,
            overwrite=True,
            expected_sha256=expected,
        )
        commit_pgn_save_publication(session, publication)
        self.assertIn("Snapshot Base", target.read_text(encoding="utf-8"))
        self.assertFalse(session.dirty)

    def test_recovered_source_cannot_snapshot_save_but_save_as_clears_provenance_warning(self) -> None:
        source = self.root / "legacy-cp1251.pgn"
        legacy = DOCUMENT.replace("Snapshot Base", "Русская шахматная книга")
        source.write_bytes(legacy.encode("cp1251"))
        session = PgnDocumentSession.open(source)
        self.assertFalse(session.view().source_overwrite_safe)
        self.assertTrue(session.view().global_warnings)

        with self.assertRaises(PgnDocumentError) as caught:
            capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE)
        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.SOURCE_REQUIRES_SAVE_AS)

        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "recovered-utf8.pgn"
        publication = publish_pgn_save_snapshot(snapshot, path=target)
        commit_pgn_save_publication(session, publication)
        self.assertTrue(session.view().source_overwrite_safe)
        self.assertFalse(session.view().global_warnings)
        self.assertFalse(session.dirty)
        self.assertIn("Русская шахматная книга", target.read_text(encoding="utf-8"))

    def test_exact_commit_replay_is_idempotent(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        publication = publish_pgn_save_snapshot(snapshot, path=self.root / "saved.pgn")

        first = commit_pgn_save_publication(session, publication)
        revision = first.document_revision
        second = commit_pgn_save_publication(session, publication)
        self.assertEqual(second.document_revision, revision)
        self.assertFalse(second.dirty)


if __name__ == "__main__":
    unittest.main()
