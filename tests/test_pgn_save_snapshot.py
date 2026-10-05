from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.import_contract import SourceFingerprint
from acs.gametree_annotations import MoveAnnotationPatch, move_annotation_target
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
from acs.pgn_workspace import PgnWorkspace


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


class _ExplodingSessionRef:
    def __call__(self):
        raise AssertionError("tampered session reference executed")


class _ExplodingTruth:
    def __bool__(self):
        raise AssertionError("active overwrite truthiness executed")


class _ExplodingWorkspace(PgnWorkspace):
    def view(self):
        raise AssertionError("workspace subclass behavior executed")


class PgnSaveSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_document(self, name: str = "source.pgn", text: str = DOCUMENT) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def test_workspace_subclass_is_rejected_before_active_behavior(self) -> None:
        workspace = _ExplodingWorkspace.from_text(DOCUMENT)

        with self.assertRaises(TypeError):
            PgnDocumentSession(workspace, saved_digest=workspace.content_digest)

    def test_active_overwrite_control_is_rejected_without_truthiness_or_io(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "active-overwrite.pgn"

        with self.assertRaises(TypeError):
            publish_pgn_save_snapshot(
                snapshot,
                path=target,
                overwrite=_ExplodingTruth(),  # type: ignore[arg-type]
            )

        self.assertFalse(target.exists())
        self.assertIsNone(session.source)
        self.assertTrue(session.dirty)

    def test_capture_rejects_active_saved_digest_before_worker_handoff(self) -> None:
        class ActiveText(str):
            def __len__(self):
                raise AssertionError("active saved digest length executed")

            def __eq__(self, other):
                raise AssertionError("active saved digest equality executed")

        session = PgnDocumentSession.from_text(DOCUMENT)
        session._saved_digest = ActiveText("0" * 64)

        with self.assertRaises(TypeError):
            capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)

    def test_capture_rejects_active_workspace_revision_before_comparison(self) -> None:
        class ActiveInt(int):
            def __lt__(self, other):
                raise AssertionError("active workspace revision ordering executed")

            def __ne__(self, other):
                raise AssertionError("active workspace revision comparison executed")

        session = PgnDocumentSession.from_text(DOCUMENT)
        session.workspace._content_revision = ActiveInt(
            session.workspace.content_revision
        )

        with self.assertRaises(TypeError):
            capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)

    def test_capture_rejects_active_workspace_digest_before_worker_handoff(self) -> None:
        class ActiveText(str):
            def __len__(self):
                raise AssertionError("active workspace digest length executed")

            def __eq__(self, other):
                raise AssertionError("active workspace digest equality executed")

        session = PgnDocumentSession.from_text(DOCUMENT)
        session.workspace._content_digest = ActiveText(
            session.workspace.content_digest
        )

        with self.assertRaises(TypeError):
            capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)

    def test_capture_rejects_saved_baseline_change_during_detach(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        workspace = session.workspace
        session._saved_digest = workspace.content_digest
        real_games = PgnWorkspace.games

        def racing_games(bound_workspace):
            games = real_games(bound_workspace)
            if bound_workspace is workspace:
                session._saved_digest = "f" * 64
            return games

        with patch.object(PgnWorkspace, "games", autospec=True, side_effect=racing_games):
            with self.assertRaises(PgnDocumentError) as caught:
                capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)

        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.CONTEXT_STALE)

    def test_capture_does_not_materialize_document_presentation_view(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)

        with patch.object(
            PgnDocumentSession,
            "view",
            autospec=True,
            side_effect=AssertionError("snapshot capture must not build presentation view"),
        ):
            snapshot = capture_pgn_save_snapshot(
                session,
                mode=PgnSaveMode.SAVE_AS,
            )

        self.assertEqual(snapshot.mode, PgnSaveMode.SAVE_AS)
        self.assertEqual(len(snapshot.games), 1)
        self.assertEqual(snapshot.document_revision, session.document_revision)
        self.assertIsNone(snapshot.source_before)
        self.assertTrue(session.dirty)

    def test_capture_rejects_same_workspace_edit_during_detach(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        workspace = session.workspace
        real_games = PgnWorkspace.games
        changed = False

        def racing_games(bound_workspace):
            nonlocal changed
            games = real_games(bound_workspace)
            if bound_workspace is workspace and not changed:
                changed = True
                game = workspace.current_game()
                target = move_annotation_target(game, (), 0)
                workspace.edit_move_annotations(
                    target,
                    MoveAnnotationPatch(nags=("!",)),
                )
            return games

        with patch.object(
            PgnWorkspace,
            "games",
            autospec=True,
            side_effect=racing_games,
        ):
            with self.assertRaises(PgnDocumentError) as caught:
                capture_pgn_save_snapshot(
                    session,
                    mode=PgnSaveMode.SAVE_AS,
                )

        self.assertTrue(changed)
        self.assertEqual(
            caught.exception.code,
            PgnDocumentErrorCode.CONTEXT_STALE,
        )
        self.assertEqual(workspace.content_revision, 1)
        self.assertTrue(session.dirty)

    def test_capture_rejects_document_edit_during_detach(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        workspace = session.workspace
        real_games = PgnWorkspace.games
        changed = False

        def racing_games(bound_workspace):
            nonlocal changed
            games = real_games(bound_workspace)
            if bound_workspace is workspace and not changed:
                changed = True
                session.edit_tag("Event", "Reentrant edit during detach")
            return games

        with patch.object(
            PgnWorkspace,
            "games",
            autospec=True,
            side_effect=racing_games,
        ):
            with self.assertRaises(PgnDocumentError) as caught:
                capture_pgn_save_snapshot(
                    session,
                    mode=PgnSaveMode.SAVE_AS,
                )

        self.assertTrue(changed)
        self.assertEqual(
            caught.exception.code,
            PgnDocumentErrorCode.CONTEXT_STALE,
        )
        self.assertIn("Reentrant edit during detach", session.copy_pgn())

    def test_capture_rejects_provenance_rebind_during_detach(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        workspace = session.workspace
        real_games = PgnWorkspace.games
        rebound = SourceFingerprint(
            path=str(self.root / "rebound.pgn"),
            size=0,
            sha256="0" * 64,
            suffix=".pgn",
        )
        changed = False

        def racing_games(bound_workspace):
            nonlocal changed
            games = real_games(bound_workspace)
            if bound_workspace is workspace and not changed:
                changed = True
                session._source = rebound
            return games

        with patch.object(
            PgnWorkspace,
            "games",
            autospec=True,
            side_effect=racing_games,
        ):
            with self.assertRaises(PgnDocumentError) as caught:
                capture_pgn_save_snapshot(
                    session,
                    mode=PgnSaveMode.SAVE_AS,
                )

        self.assertTrue(changed)
        self.assertEqual(
            caught.exception.code,
            PgnDocumentErrorCode.CONTEXT_STALE,
        )

    def test_capture_requires_exact_save_mode_enum(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)

        with self.assertRaises(TypeError):
            capture_pgn_save_snapshot(session, mode="save_as")  # type: ignore[arg-type]

        self.assertIsNone(session.source)
        self.assertTrue(session.dirty)

    def test_capture_defers_detached_round_trip_off_owner_thread(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        expected_digest = session.workspace.content_digest

        with (
            patch(
                "acs.pgn_workspace.serialize_pgn_text",
                side_effect=AssertionError(
                    "save snapshot capture must not serialize the full PGN"
                ),
            ),
            patch(
                "acs.pgn_save_snapshot._canonical_detached_games",
                side_effect=AssertionError(
                    "save snapshot capture must defer canonical detached validation"
                ),
            ) as canonical,
        ):
            snapshot = capture_pgn_save_snapshot(
                session,
                mode=PgnSaveMode.SAVE_AS,
            )

        canonical.assert_not_called()
        self.assertEqual(snapshot.content_digest, expected_digest)
        self.assertEqual(len(snapshot.games), 1)
        self.assertIsNone(session.source)
        self.assertTrue(session.dirty)

        # The worker half still performs exact canonical validation before any
        # filesystem publication and can therefore consume the captured lease.
        target = self.root / "deferred-round-trip.pgn"
        publication = publish_pgn_save_snapshot(snapshot, path=target)
        commit_pgn_save_publication(session, publication)
        self.assertTrue(target.exists())
        self.assertFalse(session.dirty)

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

    def test_older_save_snapshot_rebases_workspace_to_published_generation(self) -> None:
        source = self.write_document("older-save-baseline.pgn")
        session = PgnDocumentSession.open(source)
        session.edit_tag("Event", "Persisted Snapshot")
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE)

        session.edit_tag("Event", "Newer In Memory")
        publication = publish_pgn_save_snapshot(snapshot)
        commit_pgn_save_publication(session, publication)

        self.assertTrue(session.dirty)
        self.assertTrue(session.workspace.dirty)
        self.assertEqual(session.workspace._baseline_digest, snapshot.content_digest)

        reverted = session.edit_tag("Event", "Persisted Snapshot")
        self.assertEqual(session.workspace.content_digest, snapshot.content_digest)
        self.assertFalse(reverted.dirty)
        self.assertFalse(session.workspace.dirty)
        self.assertFalse(session.dirty)

    def test_older_save_as_snapshot_rebases_workspace_to_published_generation(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        session.edit_tag("Event", "Persisted Save As Snapshot")
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)

        session.edit_tag("Event", "Newer Save As Edit")
        target = self.root / "older-save-as-baseline.pgn"
        publication = publish_pgn_save_snapshot(snapshot, path=target)
        commit_pgn_save_publication(session, publication)

        self.assertTrue(session.dirty)
        self.assertTrue(session.workspace.dirty)
        self.assertEqual(session.workspace._baseline_digest, snapshot.content_digest)

        reverted = session.edit_tag("Event", "Persisted Save As Snapshot")
        self.assertEqual(session.workspace.content_digest, snapshot.content_digest)
        self.assertFalse(reverted.dirty)
        self.assertFalse(session.workspace.dirty)
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

    def test_commit_rejects_active_live_source_field_before_equality(self) -> None:
        source = self.write_document("active-live-source.pgn")
        session = PgnDocumentSession.open(source)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "active-live-source-destination.pgn"
        publication = publish_pgn_save_snapshot(snapshot, path=target)
        live_source = session._source
        assert live_source is not None
        touched: list[str] = []

        class ActiveText(str):
            def __eq__(self, other):
                touched.append("eq")
                raise AssertionError("active live source equality executed")

            def __ne__(self, other):
                touched.append("ne")
                raise AssertionError("active live source inequality executed")

        object.__setattr__(
            live_source,
            "sha256",
            ActiveText(live_source.sha256),
        )

        with self.assertRaises(TypeError):
            commit_pgn_save_publication(session, publication)

        self.assertEqual([], touched)
        self.assertTrue(target.exists())
        self.assertEqual(Path(session.source.path), source)

    def test_commit_rejects_active_live_saved_digest_before_equality(self) -> None:
        source = self.write_document("active-live-saved-digest.pgn")
        session = PgnDocumentSession.open(source)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "active-live-saved-digest-destination.pgn"
        publication = publish_pgn_save_snapshot(snapshot, path=target)
        saved_digest = session._saved_digest
        assert type(saved_digest) is str
        touched: list[str] = []

        class ActiveText(str):
            def __eq__(self, other):
                touched.append("eq")
                raise AssertionError("active live saved digest equality executed")

            def __ne__(self, other):
                touched.append("ne")
                raise AssertionError("active live saved digest inequality executed")

        session._saved_digest = ActiveText(saved_digest)

        with self.assertRaises(TypeError):
            commit_pgn_save_publication(session, publication)

        self.assertEqual([], touched)
        self.assertTrue(target.exists())
        self.assertEqual(Path(session.source.path), source)

    def test_commit_rejects_changed_live_source_safety_before_rebind(self) -> None:
        source = self.write_document("source-safety-generation.pgn")
        session = PgnDocumentSession.open(source)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "source-safety-generation-destination.pgn"
        publication = publish_pgn_save_snapshot(snapshot, path=target)
        source_before = session.source
        saved_digest_before = session._saved_digest
        revision_before = session.document_revision

        # Simulate a newer owner-thread recovery decision made while worker I/O
        # was in flight.  The old durable Save As must not erase that safety
        # generation or clear its warning when its completion arrives later.
        session._source_overwrite_safe = False
        session._global_warnings = ("newer recovery safety decision",)

        with self.assertRaises(PgnDocumentError) as caught:
            commit_pgn_save_publication(session, publication)

        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.CONTEXT_STALE)
        self.assertTrue(target.exists())
        self.assertEqual(session.source, source_before)
        self.assertEqual(session._saved_digest, saved_digest_before)
        self.assertEqual(session.document_revision, revision_before)
        self.assertFalse(session.view().source_overwrite_safe)
        self.assertEqual(
            session.view().global_warnings,
            ("newer recovery safety decision",),
        )

    def test_commit_rejects_malformed_live_source_safety_before_rebind(self) -> None:
        source = self.write_document("malformed-source-safety.pgn")
        session = PgnDocumentSession.open(source)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "malformed-source-safety-destination.pgn"
        publication = publish_pgn_save_snapshot(snapshot, path=target)
        source_before = session.source
        saved_digest_before = session._saved_digest

        session._source_overwrite_safe = 1  # type: ignore[assignment]

        with self.assertRaises(TypeError):
            commit_pgn_save_publication(session, publication)

        self.assertTrue(target.exists())
        self.assertEqual(session.source, source_before)
        self.assertEqual(session._saved_digest, saved_digest_before)
        self.assertEqual(session._source_overwrite_safe, 1)

    def test_commit_rejects_active_live_workspace_digest_before_rebind(self) -> None:
        source = self.write_document("active-live-workspace-digest.pgn")
        session = PgnDocumentSession.open(source)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "active-live-workspace-digest-destination.pgn"
        publication = publish_pgn_save_snapshot(snapshot, path=target)
        workspace = session.workspace
        original_source = session.source
        original_saved_digest = session._saved_digest
        touched: list[str] = []

        class ActiveText(str):
            def __eq__(self, other):
                touched.append("eq")
                raise AssertionError("active workspace digest equality executed")

            def __ne__(self, other):
                touched.append("ne")
                raise AssertionError("active workspace digest inequality executed")

        workspace._content_digest = ActiveText(workspace.content_digest)

        with self.assertRaises(TypeError):
            commit_pgn_save_publication(session, publication)

        self.assertEqual([], touched)
        self.assertTrue(target.exists())
        self.assertIs(session.source, original_source)
        self.assertEqual(session._saved_digest, original_saved_digest)
        self.assertEqual(Path(session.source.path), source)

    def test_commit_checkpoint_failure_does_not_partially_rebind_session(self) -> None:
        source = self.write_document("checkpoint-failure.pgn")
        session = PgnDocumentSession.open(source)
        session.edit_tag("Event", "Durably published before checkpoint failure")
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE)
        source_before = session.source
        saved_digest_before = session._saved_digest
        revision_before = session.document_revision
        publication = publish_pgn_save_snapshot(snapshot)

        self.assertIn(
            "Durably published before checkpoint failure",
            source.read_text(encoding="utf-8"),
        )
        class CheckpointAbort(BaseException):
            pass

        with patch.object(
            PgnWorkspace,
            "mark_saved",
            autospec=True,
            side_effect=CheckpointAbort("workspace checkpoint unavailable"),
        ):
            with self.assertRaises(PgnDocumentError) as caught:
                commit_pgn_save_publication(session, publication)

        self.assertEqual(
            caught.exception.code,
            PgnDocumentErrorCode.SAVE_COMMIT_FAILED,
        )
        self.assertEqual(session.source, source_before)
        self.assertEqual(session._saved_digest, saved_digest_before)
        self.assertEqual(session.document_revision, revision_before)
        self.assertTrue(session.dirty)

    def test_commit_rejects_malformed_cursor_before_checkpoint_mutation(self) -> None:
        source = self.write_document("malformed-cursor-after-publication.pgn")
        session = PgnDocumentSession.open(source)
        session.edit_tag("Event", "Durable malformed cursor generation")
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE)
        source_before = session.source
        saved_digest_before = session._saved_digest
        revision_before = session.document_revision
        baseline_before = session.workspace._baseline_digest
        dirty_before = session.workspace.dirty
        publication = publish_pgn_save_snapshot(snapshot)

        self.assertIn(
            "Durable malformed cursor generation",
            source.read_text(encoding="utf-8"),
        )
        session.workspace._cursor = object()  # type: ignore[assignment]

        with self.assertRaises(PgnDocumentError) as caught:
            commit_pgn_save_publication(session, publication)

        self.assertEqual(
            caught.exception.code,
            PgnDocumentErrorCode.SAVE_COMMIT_FAILED,
        )
        self.assertEqual(session.source, source_before)
        self.assertEqual(session._saved_digest, saved_digest_before)
        self.assertEqual(session.document_revision, revision_before)
        self.assertEqual(session.workspace._baseline_digest, baseline_before)
        self.assertEqual(session.workspace.dirty, dirty_before)

    def test_commit_rejects_malformed_live_warnings_before_checkpoint_mutation(self) -> None:
        source = self.write_document("malformed-warnings-after-publication.pgn")
        session = PgnDocumentSession.open(source)
        session.edit_tag("Event", "Durable malformed warnings generation")
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE)
        source_before = session.source
        saved_digest_before = session._saved_digest
        revision_before = session.document_revision
        baseline_before = session.workspace._baseline_digest
        dirty_before = session.workspace.dirty
        publication = publish_pgn_save_snapshot(snapshot)

        self.assertIn(
            "Durable malformed warnings generation",
            source.read_text(encoding="utf-8"),
        )
        session._global_warnings = ("valid warning", object())  # type: ignore[assignment]

        with self.assertRaises(PgnDocumentError) as caught:
            commit_pgn_save_publication(session, publication)

        self.assertEqual(
            caught.exception.code,
            PgnDocumentErrorCode.SAVE_COMMIT_FAILED,
        )
        self.assertEqual(session.source, source_before)
        self.assertEqual(session._saved_digest, saved_digest_before)
        self.assertEqual(session.document_revision, revision_before)
        self.assertEqual(session.workspace._baseline_digest, baseline_before)
        self.assertEqual(session.workspace.dirty, dirty_before)

    def test_commit_does_not_rebuild_view_after_provenance_mutation(self) -> None:
        source = self.write_document("no-post-mutation-view.pgn")
        session = PgnDocumentSession.open(source)
        source_before = session.source
        session.edit_tag("Event", "Prepared final view")
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE)
        publication = publish_pgn_save_snapshot(snapshot)
        real_view = PgnDocumentSession.view
        observed_sources = []

        def guarded_view(bound_session):
            observed_sources.append(bound_session.source)
            if bound_session.source != source_before:
                raise AssertionError(
                    "document presentation rebuilt after provenance mutation"
                )
            return real_view(bound_session)

        with patch.object(
            PgnDocumentSession,
            "view",
            autospec=True,
            side_effect=guarded_view,
        ):
            committed = commit_pgn_save_publication(session, publication)

        self.assertEqual(len(observed_sources), 1)
        self.assertNotEqual(session.source, source_before)
        self.assertFalse(session.dirty)
        self.assertFalse(committed.dirty)
        self.assertEqual(committed.document_revision, session.document_revision)
        self.assertEqual(committed.source_path, session.source.path)
        self.assertEqual(committed.source_sha256, session.source.sha256)
        self.assertEqual(committed, session.view())

    def test_commit_rejects_active_live_document_revision_before_increment(self) -> None:
        source = self.write_document("active-live-revision.pgn")
        session = PgnDocumentSession.open(source)
        session.edit_tag("Event", "Published before active revision")
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE)
        source_before = session.source
        saved_digest_before = session._saved_digest
        publication = publish_pgn_save_snapshot(snapshot)
        touched: list[str] = []

        class ActiveInt(int):
            def __add__(self, other):
                touched.append("add")
                raise AssertionError("active revision addition executed")

        session._document_revision = ActiveInt(session.document_revision)

        with self.assertRaises(TypeError):
            commit_pgn_save_publication(session, publication)

        self.assertEqual([], touched)
        self.assertEqual(session.source, source_before)
        self.assertEqual(session._saved_digest, saved_digest_before)
        self.assertTrue(session.dirty)

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

    def test_noncanonical_publication_provenance_fails_before_session_rebind(self) -> None:
        cases = (
            ("sha256", "f" * 63),
            ("sha256", "F" * 64),
            ("size", -1),
            ("suffix", ".txt"),
            ("path", ""),
        )
        for field_name, invalid_value in cases:
            with self.subTest(field=field_name):
                session = PgnDocumentSession.from_text(DOCUMENT)
                snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
                target = self.root / f"noncanonical-{field_name}.pgn"
                publication = publish_pgn_save_snapshot(snapshot, path=target)
                object.__setattr__(publication.saved, field_name, invalid_value)

                with self.assertRaises(ValueError):
                    commit_pgn_save_publication(session, publication)

                self.assertIsNone(session.source)
                self.assertTrue(session.dirty)
                self.assertTrue(target.exists())

    def test_valid_shape_publication_provenance_tamper_fails_before_session_rebind(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "valid-shape-tamper.pgn"
        publication = publish_pgn_save_snapshot(snapshot, path=target)
        object.__setattr__(publication.saved, "sha256", "e" * 64)

        with self.assertRaises(PgnDocumentError) as caught:
            commit_pgn_save_publication(session, publication)

        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.CONTEXT_STALE)
        self.assertIsNone(session.source)
        self.assertTrue(session.dirty)
        self.assertTrue(target.exists())

    def test_publication_snapshot_swap_cannot_commit_a_different_generation(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        older = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "snapshot-swap.pgn"
        publication = publish_pgn_save_snapshot(older, path=target)
        session.edit_tag("Event", "Newer In Memory")
        newer = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        object.__setattr__(publication, "snapshot", newer)

        with self.assertRaises(PgnDocumentError) as caught:
            commit_pgn_save_publication(session, publication)

        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.CONTEXT_STALE)
        self.assertIsNone(session.source)
        self.assertTrue(session.dirty)
        self.assertIn("Snapshot Base", target.read_text(encoding="utf-8"))
        self.assertIn("Newer In Memory", session.copy_pgn())

    def test_snapshot_metadata_tamper_after_publication_cannot_change_commit_baseline(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "snapshot-metadata-tamper.pgn"
        publication = publish_pgn_save_snapshot(snapshot, path=target)
        object.__setattr__(snapshot, "content_digest", "0" * 64)

        with self.assertRaises(PgnDocumentError) as caught:
            commit_pgn_save_publication(session, publication)

        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.CONTEXT_STALE)
        self.assertIsNone(session.source)
        self.assertTrue(session.dirty)
        self.assertTrue(target.exists())

    def test_valid_shape_snapshot_source_swap_fails_before_save_io(self) -> None:
        source = self.write_document("captured-source.pgn", DOCUMENT)
        other = self.write_document("other-source.pgn", SECOND_DOCUMENT)
        session = PgnDocumentSession.open(source)
        other_session = PgnDocumentSession.open(other)
        session.edit_tag("Event", "Pending Save")
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE)
        other_before = other.read_bytes()
        object.__setattr__(snapshot, "source_before", other_session.source)

        with self.assertRaises(PgnDocumentError) as caught:
            publish_pgn_save_snapshot(snapshot)

        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.CONTEXT_STALE)
        self.assertEqual(other.read_bytes(), other_before)
        self.assertTrue(session.dirty)
        self.assertIn("Pending Save", session.copy_pgn())

    def test_snapshot_mode_swap_cannot_redirect_save_to_save_as(self) -> None:
        source = self.write_document("mode-source.pgn", DOCUMENT)
        session = PgnDocumentSession.open(source)
        session.edit_tag("Event", "Pending Save")
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE)
        target = self.root / "redirected-save-as.pgn"
        object.__setattr__(snapshot, "mode", PgnSaveMode.SAVE_AS)

        with self.assertRaises(PgnDocumentError) as caught:
            publish_pgn_save_snapshot(snapshot, path=target)

        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.CONTEXT_STALE)
        self.assertFalse(target.exists())
        self.assertTrue(session.dirty)

    def test_noncanonical_snapshot_source_provenance_fails_before_save_io(self) -> None:
        source = self.write_document("source-provenance.pgn")
        session = PgnDocumentSession.open(source)
        session.edit_tag("Event", "Pending Save")
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE)
        assert snapshot.source_before is not None
        source_bytes = source.read_bytes()
        object.__setattr__(snapshot.source_before, "sha256", "0" * 63)

        with self.assertRaises(ValueError):
            publish_pgn_save_snapshot(snapshot)

        self.assertEqual(source.read_bytes(), source_bytes)
        self.assertTrue(session.dirty)
        self.assertIn("Pending Save", session.copy_pgn())

    def test_tampered_snapshot_session_reference_is_rejected_before_callback(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "tampered-session-ref.pgn"
        publication = publish_pgn_save_snapshot(snapshot, path=target)
        object.__setattr__(snapshot, "_session_ref", _ExplodingSessionRef())

        with self.assertRaises(TypeError):
            commit_pgn_save_publication(session, publication)

        self.assertIsNone(session.source)
        self.assertTrue(session.dirty)
        self.assertTrue(target.exists())

    def test_tampered_snapshot_scalar_metadata_fails_closed(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        object.__setattr__(snapshot, "content_digest", object())

        with self.assertRaises(TypeError):
            publish_pgn_save_snapshot(
                snapshot,
                path=self.root / "must-not-publish-invalid-metadata.pgn",
            )

        self.assertFalse((self.root / "must-not-publish-invalid-metadata.pgn").exists())
        self.assertIsNone(session.source)
        self.assertTrue(session.dirty)

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

    def test_save_as_same_source_keeps_captured_source_cas_authority(self) -> None:
        source = self.write_document("same-source-save-as.pgn", DOCUMENT)
        session = PgnDocumentSession.open(source)
        source_before = session.source
        assert source_before is not None
        session.edit_tag("Event", "Local Save As Snapshot")
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)

        external = DOCUMENT.replace("Snapshot Base", "External Save As Generation")
        source.write_text(external, encoding="utf-8", newline="\n")
        fresh_destination = expected_pgn_destination_sha256(source)
        self.assertIsNotNone(fresh_destination)
        self.assertNotEqual(fresh_destination, source_before.sha256)

        with self.assertRaises(PgnConcurrentWriteError):
            publish_pgn_save_snapshot(
                snapshot,
                path=source,
                overwrite=True,
                expected_sha256=fresh_destination,
            )

        self.assertEqual(session.source, source_before)
        self.assertTrue(session.dirty)
        self.assertIn("Local Save As Snapshot", session.copy_pgn())
        disk_text = source.read_text(encoding="utf-8")
        self.assertIn("External Save As Generation", disk_text)
        self.assertNotIn("Local Save As Snapshot", disk_text)

    def test_session_save_as_same_source_rejects_fresh_external_hash(self) -> None:
        source = self.write_document("session-same-source-save-as.pgn", DOCUMENT)
        session = PgnDocumentSession.open(source)
        source_before = session.source
        assert source_before is not None
        session.edit_tag("Event", "Session Local Save As")

        external = DOCUMENT.replace("Snapshot Base", "Session External Save As")
        source.write_text(external, encoding="utf-8", newline="\n")
        fresh_destination = expected_pgn_destination_sha256(source)
        self.assertIsNotNone(fresh_destination)
        self.assertNotEqual(fresh_destination, source_before.sha256)

        with self.assertRaises(PgnConcurrentWriteError):
            session.save_as(
                source,
                overwrite=True,
                expected_sha256=fresh_destination,
            )

        self.assertEqual(session.source, source_before)
        self.assertTrue(session.dirty)
        self.assertIn("Session Local Save As", session.copy_pgn())
        disk_text = source.read_text(encoding="utf-8")
        self.assertIn("Session External Save As", disk_text)
        self.assertNotIn("Session Local Save As", disk_text)

    def test_same_source_save_as_rejects_noncanonical_expected_digest(self) -> None:
        source = self.write_document("same-source-invalid-expected.pgn", DOCUMENT)
        session = PgnDocumentSession.open(source)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        before = source.read_bytes()

        with self.assertRaises(ValueError):
            session.save_as(
                source,
                overwrite=True,
                expected_sha256="F" * 64,
            )
        with self.assertRaises(ValueError):
            publish_pgn_save_snapshot(
                snapshot,
                path=source,
                overwrite=True,
                expected_sha256="F" * 64,
            )

        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(Path(session.source.path), source)
        self.assertFalse(session.dirty)

    def test_session_recovery_source_requires_different_save_as_path(self) -> None:
        source = self.root / "recovery-session-source.pgn"
        raw = DOCUMENT.encode("utf-8") + b"\n{broken byte: \xff}\n"
        source.write_bytes(raw)
        session = PgnDocumentSession.open(source)
        self.assertFalse(session.view().source_overwrite_safe)
        expected = expected_pgn_destination_sha256(source)
        self.assertIsNotNone(expected)

        with self.assertRaises(PgnDocumentError) as caught:
            session.save_as(
                source,
                overwrite=True,
                expected_sha256=expected,
            )

        self.assertEqual(
            caught.exception.code,
            PgnDocumentErrorCode.RECOVERY_SOURCE_REQUIRES_DIFFERENT_DESTINATION,
        )
        self.assertEqual(source.read_bytes(), raw)
        self.assertTrue(session.dirty)

    def test_snapshot_recovery_source_requires_different_save_as_path(self) -> None:
        source = self.root / "recovery-snapshot-source.pgn"
        raw = DOCUMENT.encode("utf-8") + b"\n{broken byte: \xff}\n"
        source.write_bytes(raw)
        session = PgnDocumentSession.open(source)
        self.assertFalse(session.view().source_overwrite_safe)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        expected = expected_pgn_destination_sha256(source)
        self.assertIsNotNone(expected)

        with self.assertRaises(PgnDocumentError) as caught:
            publish_pgn_save_snapshot(
                snapshot,
                path=source,
                overwrite=True,
                expected_sha256=expected,
            )

        self.assertEqual(
            caught.exception.code,
            PgnDocumentErrorCode.RECOVERY_SOURCE_REQUIRES_DIFFERENT_DESTINATION,
        )
        self.assertEqual(source.read_bytes(), raw)
        self.assertTrue(session.dirty)

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

        def writer(
            path,
            games,
            *,
            overwrite=False,
            expected_sha256=None,
            pre_publish_check=None,
        ):
            self.assertIsNot(games, snapshot.games)
            # Mutating the caller-retained public snapshot after the validation
            # point must not affect the graph being consumed by the writer.
            snapshot.games[0].tags["Event"] = "Late Caller Mutation"
            return canonical_save_pgn_atomic(
                path,
                games,
                overwrite=overwrite,
                expected_sha256=expected_sha256,
                pre_publish_check=pre_publish_check,
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

    def test_absent_save_as_target_rejects_overwrite_without_generation_before_writer(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "absent-overwrite.pgn"
        self.assertFalse(target.exists())

        with patch("acs.pgn_save_snapshot.save_pgn_atomic") as writer:
            with self.assertRaises(PgnDocumentError) as caught:
                publish_pgn_save_snapshot(snapshot, path=target, overwrite=True)

        self.assertEqual(
            caught.exception.code,
            PgnDocumentErrorCode.DESTINATION_VERSION_REQUIRED,
        )
        writer.assert_not_called()
        self.assertFalse(target.exists())
        self.assertIsNone(session.source)
        self.assertTrue(session.dirty)

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

    def test_duplicate_completion_after_new_edit_does_not_mark_edit_clean(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        publication = publish_pgn_save_snapshot(
            snapshot,
            path=self.root / "duplicate-after-edit.pgn",
        )
        first = commit_pgn_save_publication(session, publication)

        session.edit_tag("Event", "Edited After Save")
        edit_revision = session.document_revision
        self.assertTrue(session.dirty)

        replay = commit_pgn_save_publication(session, publication)

        self.assertEqual(replay.document_revision, edit_revision)
        self.assertEqual(first.source_sha256, replay.source_sha256)
        self.assertTrue(replay.dirty)
        self.assertTrue(session.dirty)
        self.assertIn("Edited After Save", session.copy_pgn())


if __name__ == "__main__":
    unittest.main()
