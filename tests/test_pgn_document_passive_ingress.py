from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.gametree_navigation import GameTreeCursor, VariationStep
from acs.import_contract import SourceFingerprint
from acs.pgn_document import (
    PgnDocumentContext,
    PgnDocumentError,
    PgnDocumentErrorCode,
    PgnDocumentSession,
)
from acs.pgn_workspace import PgnWorkspace
from acs.position_editor import standard_position


PGN = '''[Event "Passive ingress"]
[Site "?"]
[Date "????.??.??"]
[Round "?"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 *
'''


class GuardedText(str):
    """String subclass whose active hooks prove the boundary stayed passive."""

    def __new__(cls, value: str) -> "GuardedText":
        instance = super().__new__(cls, value)
        instance.armed = False
        return instance

    def _guard(self, operation: str) -> None:
        if self.armed:
            raise AssertionError(f"active text hook executed: {operation}")

    def __hash__(self) -> int:
        self._guard("hash")
        return super().__hash__()

    def __eq__(self, other: object) -> bool:
        self._guard("eq")
        return super().__eq__(other)

    def __len__(self) -> int:
        self._guard("len")
        return super().__len__()

    def strip(self, *args: object, **kwargs: object) -> str:
        self._guard("strip")
        return super().strip(*args, **kwargs)

    def __format__(self, format_spec: str) -> str:
        self._guard("format")
        return super().__format__(format_spec)


class ActiveMapping(dict[str, str]):
    def __iter__(self):  # type: ignore[override]
        raise AssertionError("active mapping iteration executed")

    def keys(self):  # type: ignore[override]
        raise AssertionError("active mapping keys executed")

    def items(self):  # type: ignore[override]
        raise AssertionError("active mapping items executed")

    def __len__(self) -> int:
        raise AssertionError("active mapping length executed")

    def __getitem__(self, key: str) -> str:
        raise AssertionError("active mapping item lookup executed")


class ActiveBool:
    def __bool__(self) -> bool:
        raise AssertionError("active boolean hook executed")


class AlternateWorkspace(PgnWorkspace):
    pass


class AlternateCursor(GameTreeCursor):
    pass


class ActiveVariationStep(VariationStep):
    def __getattribute__(self, name: str):
        if name in {"parent_move_index", "variation_index"}:
            armed = object.__getattribute__(self, "__dict__").get("armed", False)
            if armed:
                raise AssertionError("active variation-step attribute hook executed")
        return super().__getattribute__(name)


class ActivePath(tuple):
    def __iter__(self):
        raise AssertionError("active variation-path iteration executed")


class ActiveContext(PgnDocumentContext):
    def __getattribute__(self, name: str):
        if name in {"content_digest", "selected_game_index", "cursor"}:
            raise AssertionError("active context attribute hook executed")
        return super().__getattribute__(name)


class PgnDocumentPassiveIngressTests(unittest.TestCase):
    def session(self) -> PgnDocumentSession:
        return PgnDocumentSession.from_text(PGN)

    def assert_document_error(
        self,
        code: PgnDocumentErrorCode,
        callback,
    ) -> None:
        with self.assertRaises(PgnDocumentError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_document_digest_reads_remain_passive_after_validation(self) -> None:
        session = self.session()
        digest = session.workspace.content_digest

        with patch(
            "acs.pgn_workspace.serialize_pgn_text",
            side_effect=AssertionError(
                "document digest reads must not reserialize the canonical PGN"
            ),
        ) as serializer:
            self.assertTrue(session.dirty)
            self.assertEqual(session.view().document_revision, 0)
            self.assertEqual(session.bookmark().content_digest, digest)

        serializer.assert_not_called()

        session.edit_tag("Event", "Digest cache mutation")
        self.assertNotEqual(session.workspace.content_digest, digest)
        self.assertTrue(session.dirty)

    def test_new_game_rejects_active_mapping_before_mapping_hooks(self) -> None:
        self.assert_document_error(
            PgnDocumentErrorCode.INVALID_TAG,
            lambda: PgnDocumentSession.new_game(ActiveMapping({"Event": "X"})),
        )

    def test_new_game_rejects_active_key_before_hash_or_comparison(self) -> None:
        key = GuardedText("Event")
        tags = {key: "X"}
        key.armed = True
        self.assert_document_error(
            PgnDocumentErrorCode.INVALID_TAG,
            lambda: PgnDocumentSession.new_game(tags),
        )

    def test_new_game_rejects_active_value_before_string_hooks(self) -> None:
        value = GuardedText("X")
        value.armed = True
        self.assert_document_error(
            PgnDocumentErrorCode.INVALID_TAG,
            lambda: PgnDocumentSession.new_game({"Event": value}),
        )

    def test_new_game_from_position_rejects_tampered_nested_text_before_format_hook(self) -> None:
        position = standard_position()
        castling = GuardedText("KQkq")
        castling.armed = True
        object.__setattr__(position, "castling", castling)
        self.assert_document_error(
            PgnDocumentErrorCode.INVALID_POSITION,
            lambda: PgnDocumentSession.new_game_from_position(position),
        )

    def test_edit_tag_rejects_active_name_before_hash_or_equality(self) -> None:
        session = self.session()
        name = GuardedText("Event")
        name.armed = True
        self.assert_document_error(
            PgnDocumentErrorCode.INVALID_TAG,
            lambda: session.edit_tag(name, "X"),
        )

    def test_edit_tag_rejects_active_value_before_canonical_rebuild(self) -> None:
        session = self.session()
        value = GuardedText("X")
        value.armed = True
        self.assert_document_error(
            PgnDocumentErrorCode.INVALID_TAG,
            lambda: session.edit_tag("Event", value),
        )

    def test_edit_rejects_active_revision_before_document_replacement(self) -> None:
        class ActiveInt(int):
            def __add__(self, other):
                raise AssertionError("active document revision arithmetic executed")

            def __lt__(self, other):
                raise AssertionError("active document revision ordering executed")

        session = self.session()
        workspace_before = session.workspace
        text_before = session.copy_pgn()
        session._document_revision = ActiveInt(0)

        with self.assertRaises(TypeError):
            session.edit_tag("Event", "Must not commit")

        self.assertIs(session.workspace, workspace_before)
        self.assertEqual(session.copy_pgn(), text_before)

    def test_edit_projection_abort_cannot_publish_replacement_workspace(self) -> None:
        class ProjectionAbort(BaseException):
            pass

        session = self.session()
        workspace_before = session.workspace
        text_before = session.copy_pgn()
        revision_before = session.document_revision
        real_view = PgnWorkspace.view

        def guarded_view(workspace):
            if workspace is workspace_before:
                return real_view(workspace)
            raise ProjectionAbort("candidate workspace projection aborted")

        with patch.object(PgnWorkspace, "view", autospec=True, side_effect=guarded_view):
            with self.assertRaises(ProjectionAbort):
                session.edit_tag("Event", "Must not commit")

        self.assertIs(session.workspace, workspace_before)
        self.assertEqual(session.copy_pgn(), text_before)
        self.assertEqual(session.document_revision, revision_before)

    def test_delete_tag_rejects_active_name_before_comparison(self) -> None:
        session = self.session()
        name = GuardedText("Annotator")
        name.armed = True
        self.assert_document_error(
            PgnDocumentErrorCode.INVALID_TAG,
            lambda: session.delete_tag(name),
        )

    def test_result_rejects_active_text_before_result_set_membership(self) -> None:
        session = self.session()
        result = GuardedText("1-0")
        result.armed = True
        self.assert_document_error(
            PgnDocumentErrorCode.INVALID_RESULT,
            lambda: session.set_result(result),
        )

    def test_session_rejects_alternate_workspace_root(self) -> None:
        workspace = AlternateWorkspace.from_text(PGN)
        with self.assertRaises(TypeError):
            PgnDocumentSession(workspace)

    def test_session_rejects_active_boolean_before_bool_coercion(self) -> None:
        workspace = PgnWorkspace.from_text(PGN)
        with self.assertRaises(TypeError):
            PgnDocumentSession(workspace, source_overwrite_safe=ActiveBool())  # type: ignore[arg-type]

    def test_direct_save_rejects_active_internal_source_without_text_hooks(self) -> None:
        workspace = PgnWorkspace.from_text(PGN)
        source = SourceFingerprint(
            path="source.pgn",
            size=100,
            sha256="0" * 64,
            suffix=".pgn",
        )
        session = PgnDocumentSession(
            workspace,
            source=source,
            saved_digest=workspace.content_digest,
        )
        internal = session._source
        assert internal is not None
        digest = GuardedText(internal.sha256)
        digest.armed = True
        object.__setattr__(internal, "sha256", digest)

        with patch("acs.pgn_document.save_pgn_atomic") as writer:
            with self.assertRaises(TypeError):
                session.save()

        writer.assert_not_called()

    def test_direct_save_as_rejects_active_internal_source_without_text_hooks(self) -> None:
        workspace = PgnWorkspace.from_text(PGN)
        source = SourceFingerprint(
            path="source.pgn",
            size=100,
            sha256="0" * 64,
            suffix=".pgn",
        )
        session = PgnDocumentSession(
            workspace,
            source=source,
            saved_digest=workspace.content_digest,
        )
        internal = session._source
        assert internal is not None
        path = GuardedText(internal.path)
        path.armed = True
        object.__setattr__(internal, "path", path)

        with patch("acs.pgn_document.save_pgn_atomic") as writer:
            with self.assertRaises(TypeError):
                session.save_as("other.pgn")

        writer.assert_not_called()

    def test_direct_save_rejects_active_source_safety_without_truthiness(self) -> None:
        workspace = PgnWorkspace.from_text(PGN)
        source = SourceFingerprint(
            path="source.pgn",
            size=100,
            sha256="0" * 64,
            suffix=".pgn",
        )
        session = PgnDocumentSession(
            workspace,
            source=source,
            saved_digest=workspace.content_digest,
        )
        session._source_overwrite_safe = ActiveBool()  # type: ignore[assignment]

        with patch("acs.pgn_document.save_pgn_atomic") as writer:
            with self.assertRaises(TypeError):
                session.save()

        writer.assert_not_called()

    def test_direct_save_as_rejects_active_source_safety_without_truthiness(self) -> None:
        workspace = PgnWorkspace.from_text(PGN)
        source = SourceFingerprint(
            path="source.pgn",
            size=100,
            sha256="0" * 64,
            suffix=".pgn",
        )
        session = PgnDocumentSession(
            workspace,
            source=source,
            saved_digest=workspace.content_digest,
        )
        session._source_overwrite_safe = ActiveBool()  # type: ignore[assignment]

        with patch("acs.pgn_document.save_pgn_atomic") as writer:
            with self.assertRaises(TypeError):
                session.save_as("other.pgn")

        writer.assert_not_called()

    def test_session_rejects_active_warning_and_saved_digest_scalars(self) -> None:
        workspace = PgnWorkspace.from_text(PGN)
        warning = GuardedText("warning")
        warning.armed = True
        with self.assertRaises(TypeError):
            PgnDocumentSession(workspace, global_warnings=(warning,))

        digest = GuardedText(workspace.content_digest)
        digest.armed = True
        with self.assertRaises(TypeError):
            PgnDocumentSession(workspace, saved_digest=digest)

    def test_session_rejects_noncanonical_saved_digest_at_ingress(self) -> None:
        workspace = PgnWorkspace.from_text(PGN)
        invalid = (
            "",
            "0" * 63,
            "0" * 65,
            "A" * 64,
            "z" * 64,
        )
        for digest in invalid:
            with self.subTest(digest=digest):
                with self.assertRaises(ValueError):
                    PgnDocumentSession(workspace, saved_digest=digest)

    def test_session_rejects_nonpassive_source_fingerprint_fields(self) -> None:
        workspace = PgnWorkspace.from_text(PGN)
        path = GuardedText("source.pgn")
        path.armed = True
        source = SourceFingerprint(
            path=path,
            size=1,
            sha256="0" * 64,
            suffix=".pgn",
        )
        with self.assertRaises(TypeError):
            PgnDocumentSession(workspace, source=source)

    def test_session_rejects_noncanonical_source_fingerprint_values(self) -> None:
        workspace = PgnWorkspace.from_text(PGN)
        invalid_sources = (
            SourceFingerprint(path="", size=1, sha256="0" * 64, suffix=""),
            SourceFingerprint(path="source.pgn", size=-1, sha256="0" * 64, suffix=".pgn"),
            SourceFingerprint(path="source.pgn", size=1, sha256="not-a-digest", suffix=".pgn"),
            SourceFingerprint(path="source.pgn", size=1, sha256="A" * 64, suffix=".pgn"),
            SourceFingerprint(path="source.pgn", size=1, sha256="0" * 64, suffix=".txt"),
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    PgnDocumentSession(
                        workspace,
                        source=source,
                        saved_digest=workspace.content_digest,
                    )

    def test_session_detaches_valid_source_fingerprint_from_caller_mutation(self) -> None:
        workspace = PgnWorkspace.from_text(PGN)
        source = SourceFingerprint(
            path="source.pgn",
            size=123,
            sha256="0" * 64,
            suffix=".pgn",
        )
        session = PgnDocumentSession(
            workspace,
            source=source,
            saved_digest=workspace.content_digest,
        )
        accepted = session.source
        self.assertIsNotNone(accepted)
        self.assertIsNot(accepted, source)
        self.assertEqual(accepted, source)

        object.__setattr__(source, "path", "attacker-replaced.pgn")
        object.__setattr__(source, "sha256", "f" * 64)
        object.__setattr__(source, "size", 999999)

        self.assertEqual(session.source, accepted)
        view = session.view()
        self.assertEqual(view.source_path, "source.pgn")
        self.assertEqual(view.source_sha256, "0" * 64)
        self.assertEqual(session.document_revision, 0)
        self.assertFalse(session.dirty)

        assert accepted is not None
        object.__setattr__(accepted, "path", "mutated-returned-source.pgn")
        object.__setattr__(accepted, "sha256", "e" * 64)
        exposed_again = session.source
        self.assertIsNotNone(exposed_again)
        self.assertEqual(exposed_again.path, "source.pgn")
        self.assertEqual(exposed_again.sha256, "0" * 64)
        self.assertEqual(session.document_revision, 0)

    def test_dirty_rejects_active_saved_digest_before_comparison(self) -> None:
        session = self.session()
        digest = GuardedText(session.workspace.content_digest)
        digest.armed = True
        session._saved_digest = digest

        with self.assertRaises(TypeError):
            _ = session.dirty

    def test_dirty_rejects_active_workspace_digest_before_comparison(self) -> None:
        session = self.session()
        canonical = session.workspace.content_digest
        session._saved_digest = canonical
        digest = GuardedText(canonical)
        digest.armed = True
        session.workspace._content_digest = digest

        with self.assertRaises(TypeError):
            _ = session.dirty

    def test_source_rejects_active_internal_provenance_before_text_hooks(self) -> None:
        workspace = PgnWorkspace.from_text(PGN)
        source = SourceFingerprint(
            path="source.pgn",
            size=100,
            sha256="0" * 64,
            suffix=".pgn",
        )
        session = PgnDocumentSession(
            workspace,
            source=source,
            saved_digest=workspace.content_digest,
        )
        internal = session._source
        assert internal is not None
        digest = GuardedText(internal.sha256)
        digest.armed = True
        object.__setattr__(internal, "sha256", digest)

        with self.assertRaises(TypeError):
            _ = session.source

    def test_view_rejects_active_recovery_scalars_before_hooks(self) -> None:
        session = self.session()
        warning = GuardedText("recovery warning")
        warning.armed = True
        session._global_warnings = (warning,)
        session._source_overwrite_safe = ActiveBool()  # type: ignore[assignment]

        with self.assertRaises(TypeError):
            session.view()

    def test_document_revision_rejects_active_int_before_arithmetic_hooks(self) -> None:
        class ActiveInt(int):
            def __lt__(self, other):
                raise AssertionError("active revision ordering executed")

            def __add__(self, other):
                raise AssertionError("active revision arithmetic executed")

        session = self.session()
        session._document_revision = ActiveInt(0)

        with self.assertRaises(TypeError):
            _ = session.document_revision
        with self.assertRaises(TypeError):
            session.view()

    def test_view_and_bookmark_detach_cursor_from_live_workspace(self) -> None:
        session = self.session()
        live_cursor = session.workspace.cursor
        view = session.view()
        bookmark = session.bookmark()

        self.assertEqual(view.cursor, live_cursor)
        self.assertEqual(bookmark.cursor, live_cursor)
        self.assertIsNot(view.cursor, live_cursor)
        self.assertIsNot(bookmark.cursor, live_cursor)
        self.assertIsNot(view.cursor, bookmark.cursor)

        object.__setattr__(view.cursor, "next_move_index", 999)
        object.__setattr__(bookmark.cursor, "line_path", (VariationStep(0, 0),))

        self.assertEqual(session.workspace.cursor, live_cursor)
        self.assertEqual(session.workspace.cursor.next_move_index, 0)
        self.assertEqual(session.workspace.cursor.line_path, ())

    def test_save_returned_fingerprint_cannot_mutate_session_provenance(self) -> None:
        workspace = PgnWorkspace.from_text(PGN)
        source = SourceFingerprint(
            path="source.pgn",
            size=100,
            sha256="0" * 64,
            suffix=".pgn",
        )
        session = PgnDocumentSession(
            workspace,
            source=source,
            saved_digest=workspace.content_digest,
        )
        session.edit_tag("Event", "Changed")
        published = SourceFingerprint(
            path="source.pgn",
            size=101,
            sha256="1" * 64,
            suffix=".pgn",
        )
        with patch("acs.pgn_document.save_pgn_atomic", return_value=published):
            returned = session.save()

        self.assertIs(returned, published)
        self.assertEqual(session.source, published)
        object.__setattr__(returned, "sha256", "f" * 64)
        object.__setattr__(returned, "path", "attacker-save.pgn")
        retained = session.source
        self.assertIsNotNone(retained)
        self.assertEqual(retained.path, "source.pgn")
        self.assertEqual(retained.sha256, "1" * 64)
        self.assertFalse(session.dirty)

    def test_save_as_returned_fingerprint_cannot_mutate_session_provenance(self) -> None:
        session = self.session()
        published = SourceFingerprint(
            path="fresh-passive-save-as.pgn",
            size=101,
            sha256="2" * 64,
            suffix=".pgn",
        )
        with patch("acs.pgn_document.save_pgn_atomic", return_value=published):
            returned = session.save_as("fresh-passive-save-as.pgn")

        self.assertIs(returned, published)
        self.assertEqual(session.source, published)
        object.__setattr__(returned, "sha256", "e" * 64)
        object.__setattr__(returned, "path", "attacker-save-as.pgn")
        retained = session.source
        self.assertIsNotNone(retained)
        self.assertEqual(retained.path, "fresh-passive-save-as.pgn")
        self.assertEqual(retained.sha256, "2" * 64)
        self.assertFalse(session.dirty)

    def test_save_checkpoint_failure_preserves_precommit_session_state(self) -> None:
        workspace = PgnWorkspace.from_text(PGN)
        source = SourceFingerprint(
            path="source.pgn",
            size=100,
            sha256="0" * 64,
            suffix=".pgn",
        )
        session = PgnDocumentSession(
            workspace,
            source=source,
            saved_digest=workspace.content_digest,
        )
        session.edit_tag("Event", "Durably written direct Save")
        source_before = session.source
        digest_before = session._saved_digest
        revision_before = session.document_revision
        published = SourceFingerprint(
            path="source.pgn",
            size=101,
            sha256="1" * 64,
            suffix=".pgn",
        )

        with (
            patch("acs.pgn_document.save_pgn_atomic", return_value=published),
            patch.object(
                PgnWorkspace,
                "mark_saved",
                autospec=True,
                side_effect=RuntimeError("checkpoint unavailable"),
            ),
        ):
            self.assert_document_error(
                PgnDocumentErrorCode.SAVE_COMMIT_FAILED,
                session.save,
            )

        self.assertEqual(session.source, source_before)
        self.assertEqual(session._saved_digest, digest_before)
        self.assertEqual(session.document_revision, revision_before)
        self.assertTrue(session.dirty)

    def test_save_as_checkpoint_failure_preserves_recovery_metadata(self) -> None:
        workspace = PgnWorkspace.from_text(PGN)
        session = PgnDocumentSession(
            workspace,
            global_warnings=("recovery warning",),
            source_overwrite_safe=False,
            saved_digest=None,
        )
        revision_before = session.document_revision
        published = SourceFingerprint(
            path="fresh-save-as.pgn",
            size=101,
            sha256="2" * 64,
            suffix=".pgn",
        )

        with (
            patch("acs.pgn_document.save_pgn_atomic", return_value=published),
            patch.object(
                PgnWorkspace,
                "mark_saved",
                autospec=True,
                side_effect=RuntimeError("checkpoint unavailable"),
            ),
        ):
            self.assert_document_error(
                PgnDocumentErrorCode.SAVE_COMMIT_FAILED,
                lambda: session.save_as("fresh-save-as.pgn"),
            )

        self.assertIsNone(session.source)
        self.assertIsNone(session._saved_digest)
        self.assertEqual(session._global_warnings, ("recovery warning",))
        self.assertFalse(session._source_overwrite_safe)
        self.assertEqual(session.document_revision, revision_before)
        self.assertTrue(session.dirty)

    def test_save_rejects_active_returned_provenance_without_string_hooks(self) -> None:
        workspace = PgnWorkspace.from_text(PGN)
        source = SourceFingerprint(
            path="source.pgn",
            size=100,
            sha256="0" * 64,
            suffix=".pgn",
        )
        session = PgnDocumentSession(
            workspace,
            source=source,
            saved_digest=workspace.content_digest,
        )
        session.edit_tag("Event", "Pending direct Save")
        active_path = GuardedText("source.pgn")
        active_path.armed = True
        published = SourceFingerprint(
            path=active_path,
            size=101,
            sha256="1" * 64,
            suffix=".pgn",
        )

        with patch("acs.pgn_document.save_pgn_atomic", return_value=published):
            self.assert_document_error(
                PgnDocumentErrorCode.SAVE_COMMIT_FAILED,
                session.save,
            )

        self.assertEqual(session.source, source)
        self.assertTrue(session.dirty)

    def test_bookmark_rejects_active_live_workspace_digest_before_hooks(self) -> None:
        session = self.session()
        digest = GuardedText(session.workspace.content_digest)
        digest.armed = True
        session.workspace._content_digest = digest

        with self.assertRaises(TypeError):
            session.bookmark()

    def test_restore_rejects_active_live_workspace_digest_before_comparison(self) -> None:
        session = self.session()
        context = session.bookmark()
        digest = GuardedText(session.workspace.content_digest)
        digest.armed = True
        session.workspace._content_digest = digest

        self.assert_document_error(
            PgnDocumentErrorCode.CONTEXT_STALE,
            lambda: session.restore_context(context),
        )

    def test_restore_rejects_context_subclass_before_attribute_hooks(self) -> None:
        session = self.session()
        bookmark = session.bookmark()
        hostile = ActiveContext(
            bookmark.content_digest,
            bookmark.selected_game_index,
            bookmark.cursor,
        )
        with self.assertRaises(TypeError):
            session.restore_context(hostile)

    def test_restore_rejects_active_digest_without_comparison_hook(self) -> None:
        session = self.session()
        digest = GuardedText(session.workspace.content_digest)
        digest.armed = True
        context = PgnDocumentContext(digest, 0, GameTreeCursor())
        self.assert_document_error(
            PgnDocumentErrorCode.CONTEXT_STALE,
            lambda: session.restore_context(context),
        )

    def test_restore_rejects_noncanonical_cursor_root(self) -> None:
        session = self.session()
        context = PgnDocumentContext(
            session.workspace.content_digest,
            0,
            AlternateCursor(),
        )
        self.assert_document_error(
            PgnDocumentErrorCode.CONTEXT_STALE,
            lambda: session.restore_context(context),
        )

    def test_restore_rejects_nested_variation_step_subclass_before_attribute_hooks(self) -> None:
        session = self.session()
        step = ActiveVariationStep(0, 0)
        step.armed = True
        cursor = GameTreeCursor(line_path=(step,), next_move_index=0)
        context = PgnDocumentContext(
            session.workspace.content_digest,
            0,
            cursor,
        )
        self.assert_document_error(
            PgnDocumentErrorCode.CONTEXT_STALE,
            lambda: session.restore_context(context),
        )

    def test_restore_rejects_tampered_path_container_before_iteration_hook(self) -> None:
        session = self.session()
        cursor = GameTreeCursor()
        object.__setattr__(
            cursor,
            "line_path",
            ActivePath((VariationStep(0, 0),)),
        )
        context = PgnDocumentContext(
            session.workspace.content_digest,
            0,
            cursor,
        )
        self.assert_document_error(
            PgnDocumentErrorCode.CONTEXT_STALE,
            lambda: session.restore_context(context),
        )

    def test_exact_builtin_inputs_retain_normal_document_behavior(self) -> None:
        session = PgnDocumentSession.new_game({"White": "Ada", "Black": "Boris"})
        session.edit_tag("Event", "Final")
        session.edit_tag("Annotator", "Accessible Chess")
        session.delete_tag("Annotator")
        session.set_result("1-0")
        bookmark = session.bookmark()
        session.workspace.document_end()
        restored = session.restore_context(bookmark)

        game = session.workspace.current_game()
        self.assertEqual(game.tags["Event"], "Final")
        self.assertEqual(game.tags["Result"], "1-0")
        self.assertEqual(game.line.result, "1-0")
        self.assertEqual(restored.cursor, bookmark.cursor)

    def test_save_checkpoint_base_exception_preserves_durable_truth(self) -> None:
        class CheckpointAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint-abort.pgn"
            path.write_text(PGN, encoding="utf-8", newline="\n")
            session = PgnDocumentSession.open(path)
            source_before = session.source
            session.edit_tag("Event", "Durably Written")
            revision_after_edit = session.document_revision
            published_text = session.copy_pgn()

            with patch.object(
                PgnWorkspace,
                "mark_saved",
                autospec=True,
                side_effect=CheckpointAbort("workspace checkpoint aborted"),
            ):
                with self.assertRaises(PgnDocumentError) as caught:
                    session.save()

            self.assertEqual(
                caught.exception.code,
                PgnDocumentErrorCode.SAVE_COMMIT_FAILED,
            )
            self.assertEqual(path.read_text(encoding="utf-8"), published_text)
            self.assertEqual(session.source, source_before)
            self.assertEqual(session.document_revision, revision_after_edit)
            self.assertTrue(session.dirty)


if __name__ == "__main__":
    unittest.main()
