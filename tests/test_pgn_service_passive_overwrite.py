from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.gametree import parse_games
from acs.pgn_document import (
    PgnDocumentError,
    PgnDocumentErrorCode,
    PgnDocumentSession,
)
from acs.pgn_service import (
    PgnPublicationUnverifiedError,
    export_game_atomic,
    save_pgn_atomic,
)


PGN = '''[Event "Passive overwrite"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 *
'''


class ActiveBool:
    def __bool__(self) -> bool:
        raise AssertionError("active overwrite truthiness executed")


class PgnServicePassiveOverwriteTests(unittest.TestCase):
    def games(self):
        return tuple(parse_games(PGN))

    def test_new_destination_rejects_active_overwrite_before_temp_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "new.pgn"

            with self.assertRaises(TypeError):
                save_pgn_atomic(target, self.games(), overwrite=ActiveBool())  # type: ignore[arg-type]

            self.assertFalse(target.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_existing_destination_rejects_active_overwrite_before_read_or_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing.pgn"
            original = b"preserve exactly\n"
            target.write_bytes(original)

            with self.assertRaises(TypeError):
                save_pgn_atomic(target, self.games(), overwrite=ActiveBool())  # type: ignore[arg-type]

            self.assertEqual(target.read_bytes(), original)

    def test_export_wrapper_inherits_same_passive_overwrite_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "export.pgn"

            with self.assertRaises(TypeError):
                export_game_atomic(target, self.games()[0], overwrite=ActiveBool())  # type: ignore[arg-type]

            self.assertFalse(target.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_exact_boolean_controls_retain_normal_save_and_replace_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "normal.pgn"
            first = save_pgn_atomic(target, self.games(), overwrite=False)
            before = target.read_bytes()
            second = save_pgn_atomic(target, self.games(), overwrite=True)

            self.assertEqual(first.sha256, second.sha256)
            self.assertEqual(target.read_bytes(), before)

    def test_document_save_as_absent_target_rejects_unversioned_overwrite(self) -> None:
        session = PgnDocumentSession.from_text(PGN)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "absent-save-as.pgn"

            with self.assertRaises(PgnDocumentError) as caught:
                session.save_as(target, overwrite=True)

            self.assertEqual(
                caught.exception.code,
                PgnDocumentErrorCode.DESTINATION_VERSION_REQUIRED,
            )
            self.assertFalse(target.exists())
            self.assertIsNone(session.source)
            self.assertTrue(session.dirty)

    def test_document_export_absent_target_rejects_unversioned_overwrite(self) -> None:
        session = PgnDocumentSession.from_text(PGN)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "absent-export.pgn"

            with self.assertRaises(PgnDocumentError) as caught:
                session.export_selected(target, overwrite=True)

            self.assertEqual(
                caught.exception.code,
                PgnDocumentErrorCode.DESTINATION_VERSION_REQUIRED,
            )
            self.assertFalse(target.exists())

    def test_document_guard_rejects_active_overwrite_without_truthiness(self) -> None:
        session = PgnDocumentSession.from_text(PGN)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing-document.pgn"
            original = b"preserve exactly\n"
            target.write_bytes(original)

            with self.assertRaises(TypeError):
                session.save_as(target, overwrite=ActiveBool())  # type: ignore[arg-type]

            self.assertEqual(target.read_bytes(), original)
            self.assertIsNone(session.source)
            self.assertTrue(session.dirty)

    def test_document_new_target_uses_no_clobber_create_path(self) -> None:
        session = PgnDocumentSession.from_text(PGN)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "new-document.pgn"

            saved = session.save_as(target, overwrite=False)

            self.assertTrue(target.exists())
            self.assertEqual(saved.path, str(target))
            self.assertFalse(session.dirty)


    def test_post_publication_fingerprint_failure_has_distinct_terminal_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "published-but-unverified.pgn"

            with mock.patch(
                "acs.pgn_service.fingerprint",
                side_effect=OSError("private post-publication verification failure"),
            ):
                with self.assertRaises(PgnPublicationUnverifiedError) as caught:
                    save_pgn_atomic(target, self.games(), overwrite=False)

            # The no-clobber publication already crossed its commit boundary
            # before final provenance verification failed. Callers must know
            # that a blind retry could now clobber bytes which are already
            # visible at the selected destination.
            self.assertTrue(target.exists())
            self.assertIn('[Event "Passive overwrite"]', target.read_text(encoding="utf-8"))
            self.assertNotIn("private post-publication", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
