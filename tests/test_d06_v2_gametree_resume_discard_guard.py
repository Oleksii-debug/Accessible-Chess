from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import acs.version2_gametree_resume as resume_module
from acs.gametree_navigation import GameTreeCursor
from acs.gametree_resume import GameTreeResumeCode, GameTreeResumeError, GameTreeResumeStore
from acs.pgn_document import PgnDocumentSession
from acs.pgn_roundtrip import parse_pgn_text
from acs.pgn_workspace import PgnWorkspace
from acs.version2_gametree_resume import Version2GameTreeResumeCoordinator


PGN = '''[Event "D06 discard guard"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 *
'''


class _Application:
    def __init__(self) -> None:
        self.session = None
        self.installed = []

    def set_document(self, session) -> None:
        self.session = session
        self.installed.append(session)


class D06GameTreeResumeDiscardGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.resume_path = self.root / "gametree-resume.json"
        self.guard_dir = self.root / ".gametree-resume-discard"
        self.game = parse_pgn_text(PGN, strict=True)[0]

    def _clean_session(self, cursor: GameTreeCursor) -> PgnDocumentSession:
        workspace = PgnWorkspace((self.game,))
        workspace.set_cursor(cursor)
        return PgnDocumentSession(workspace, saved_digest=workspace.content_digest)

    def _state_file(
        self,
        name: str,
        cursor: GameTreeCursor,
    ) -> tuple[Path, str, bytes]:
        path = self.root / name
        state = GameTreeResumeStore(path).save(self.game, cursor)
        return path, state.token, path.read_bytes()

    def test_confirmed_discard_leaves_no_canonical_or_guard_state(self) -> None:
        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)
        application.session = self._clean_session(GameTreeCursor((), 1))
        coordinator.prepare_shutdown(application)
        self.assertTrue(self.resume_path.exists())

        application.session = PgnDocumentSession.from_text(PGN)
        coordinator.prepare_shutdown(application)

        self.assertFalse(self.resume_path.exists())
        self.assertFalse(self.guard_dir.exists())
        self.assertIsNone(coordinator.token)

    def test_crash_left_exact_claimed_guard_completes_confirmed_discard(self) -> None:
        state = GameTreeResumeStore(self.resume_path).save(
            self.game,
            GameTreeCursor((), 1),
        )
        self.guard_dir.mkdir()
        guard = self.guard_dir / f"{state.token}.guard"
        os.replace(self.resume_path, guard)

        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertFalse(coordinator.restore(application))
        self.assertFalse(self.resume_path.exists())
        self.assertFalse(self.guard_dir.exists())
        self.assertEqual(application.installed, [])

    def test_crash_left_raced_newer_guard_is_restored_and_loaded(self) -> None:
        store = GameTreeResumeStore(self.resume_path)
        old = store.save(self.game, GameTreeCursor((), 1))
        newer = store.save(
            self.game,
            GameTreeCursor((), 3),
            expected_token=old.token,
        )
        newer_bytes = self.resume_path.read_bytes()

        self.guard_dir.mkdir()
        guard = self.guard_dir / f"{old.token}.guard"
        os.replace(self.resume_path, guard)

        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertTrue(coordinator.restore(application))
        self.assertEqual(coordinator.token, newer.token)
        self.assertEqual(
            application.session.workspace.cursor,
            GameTreeCursor((), 3),
        )
        self.assertEqual(self.resume_path.read_bytes(), newer_bytes)
        self.assertFalse(self.guard_dir.exists())

    def test_crash_after_restore_link_cleans_duplicate_guard(self) -> None:
        old_path, old_token, _ = self._state_file(
            "old.json",
            GameTreeCursor((), 1),
        )
        newer_path, newer_token, newer_bytes = self._state_file(
            "newer.json",
            GameTreeCursor((), 3),
        )
        self.guard_dir.mkdir()
        guard = self.guard_dir / f"{old_token}.guard"
        os.replace(newer_path, guard)
        os.link(guard, self.resume_path)

        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertTrue(coordinator.restore(application))
        self.assertEqual(coordinator.token, newer_token)
        self.assertEqual(self.resume_path.read_bytes(), newer_bytes)
        self.assertFalse(self.guard_dir.exists())
        self.assertTrue(old_path.exists())

    def test_new_canonical_after_claimed_guard_is_preserved(self) -> None:
        old = GameTreeResumeStore(self.resume_path).save(
            self.game,
            GameTreeCursor((), 1),
        )
        newer_path, newer_token, newer_bytes = self._state_file(
            "newer.json",
            GameTreeCursor((), 3),
        )
        self.guard_dir.mkdir()
        guard = self.guard_dir / f"{old.token}.guard"
        os.replace(self.resume_path, guard)
        os.replace(newer_path, self.resume_path)

        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertTrue(coordinator.restore(application))
        self.assertEqual(coordinator.token, newer_token)
        self.assertEqual(self.resume_path.read_bytes(), newer_bytes)
        self.assertFalse(self.guard_dir.exists())

    def test_divergent_canonical_and_raced_guard_fail_closed_with_both_preserved(self) -> None:
        old_path, old_token, _ = self._state_file(
            "old.json",
            GameTreeCursor((), 1),
        )
        raced_path, _, raced_bytes = self._state_file(
            "raced.json",
            GameTreeCursor((), 2),
        )
        canonical_path, _, canonical_bytes = self._state_file(
            "canonical.json",
            GameTreeCursor((), 3),
        )
        self.guard_dir.mkdir()
        guard = self.guard_dir / f"{old_token}.guard"
        os.replace(raced_path, guard)
        os.replace(canonical_path, self.resume_path)

        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertFalse(coordinator.restore(application))
        self.assertTrue(coordinator.disabled)
        self.assertIsInstance(coordinator.error, GameTreeResumeError)
        self.assertEqual(
            coordinator.error.code,
            GameTreeResumeCode.STALE_WRITER,
        )
        self.assertEqual(self.resume_path.read_bytes(), canonical_bytes)
        self.assertEqual(guard.read_bytes(), raced_bytes)
        self.assertTrue(old_path.exists())

    def test_duplicate_claimed_state_at_guard_and_canonical_fails_closed(self) -> None:
        state = GameTreeResumeStore(self.resume_path).save(
            self.game,
            GameTreeCursor((), 1),
        )
        original = self.resume_path.read_bytes()
        self.guard_dir.mkdir()
        guard = self.guard_dir / f"{state.token}.guard"
        guard.write_bytes(original)

        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertFalse(coordinator.restore(application))
        self.assertTrue(coordinator.disabled)
        self.assertEqual(
            coordinator.error.code,
            GameTreeResumeCode.STALE_WRITER,
        )
        self.assertEqual(self.resume_path.read_bytes(), original)
        self.assertEqual(guard.read_bytes(), original)

    def test_race_before_atomic_move_restores_newer_state_and_rejects_discard(self) -> None:
        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)
        application.session = self._clean_session(GameTreeCursor((), 1))
        coordinator.prepare_shutdown(application)
        claimed = coordinator.token
        self.assertIsNotNone(claimed)

        newer_path, newer_token, newer_bytes = self._state_file(
            "newer.json",
            GameTreeCursor((), 3),
        )
        application.session = PgnDocumentSession.from_text(PGN)
        original_replace = resume_module.os.replace
        raced = False

        def replace_with_race(source, destination):
            nonlocal raced
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                not raced
                and source_path == self.resume_path
                and destination_path.parent == self.guard_dir
            ):
                raced = True
                original_replace(newer_path, self.resume_path)
            return original_replace(source, destination)

        with mock.patch.object(
            resume_module.os,
            "replace",
            side_effect=replace_with_race,
        ):
            with self.assertRaises(GameTreeResumeError) as caught:
                coordinator.prepare_shutdown(application)

        self.assertTrue(raced)
        self.assertEqual(caught.exception.code, GameTreeResumeCode.STALE_WRITER)
        authoritative = GameTreeResumeStore(self.resume_path).load()
        self.assertEqual(authoritative.token, newer_token)
        self.assertEqual(self.resume_path.read_bytes(), newer_bytes)
        self.assertFalse(self.guard_dir.exists())

    def test_new_writer_after_atomic_move_survives_claimed_discard(self) -> None:
        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)
        application.session = self._clean_session(GameTreeCursor((), 1))
        coordinator.prepare_shutdown(application)

        newer_path, newer_token, newer_bytes = self._state_file(
            "newer.json",
            GameTreeCursor((), 3),
        )
        application.session = PgnDocumentSession.from_text(PGN)
        original_replace = resume_module.os.replace
        published = False

        def replace_then_publish(source, destination):
            nonlocal published
            result = original_replace(source, destination)
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                not published
                and source_path == self.resume_path
                and destination_path.parent == self.guard_dir
            ):
                published = True
                original_replace(newer_path, self.resume_path)
            return result

        with mock.patch.object(
            resume_module.os,
            "replace",
            side_effect=replace_then_publish,
        ):
            with self.assertRaises(GameTreeResumeError) as caught:
                coordinator.prepare_shutdown(application)

        self.assertTrue(published)
        self.assertEqual(caught.exception.code, GameTreeResumeCode.STALE_WRITER)
        authoritative = GameTreeResumeStore(self.resume_path).load()
        self.assertEqual(authoritative.token, newer_token)
        self.assertEqual(self.resume_path.read_bytes(), newer_bytes)
        self.assertFalse(self.guard_dir.exists())

    def test_reservation_marker_survives_forced_short_writes_exactly(self) -> None:
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)
        self.guard_dir.mkdir()
        guard = self.guard_dir / f"{'a' * 64}.guard"
        original_write = resume_module.os.write

        def short_write(descriptor: int, payload: bytes) -> int:
            return original_write(descriptor, payload[:3])

        with mock.patch.object(
            resume_module.os,
            "write",
            side_effect=short_write,
        ):
            coordinator._reserve_discard_guard_locked(guard)

        self.assertEqual(
            guard.read_bytes(),
            resume_module._DISCARD_GUARD_RESERVATION,
        )

    def test_crash_left_reservation_marker_is_removed_only_with_canonical_state(self) -> None:
        state = GameTreeResumeStore(self.resume_path).save(
            self.game,
            GameTreeCursor((), 1),
        )
        original = self.resume_path.read_bytes()
        self.guard_dir.mkdir()
        guard = self.guard_dir / f"{state.token}.guard"
        guard.write_bytes(resume_module._DISCARD_GUARD_RESERVATION)

        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertTrue(coordinator.restore(application))
        self.assertEqual(coordinator.token, state.token)
        self.assertEqual(self.resume_path.read_bytes(), original)
        self.assertFalse(self.guard_dir.exists())

    def test_reservation_marker_without_canonical_state_fails_closed(self) -> None:
        old_path, old_token, _ = self._state_file(
            "old.json",
            GameTreeCursor((), 1),
        )
        old_path.unlink()
        self.guard_dir.mkdir()
        guard = self.guard_dir / f"{old_token}.guard"
        guard.write_bytes(resume_module._DISCARD_GUARD_RESERVATION)

        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertFalse(coordinator.restore(application))
        self.assertTrue(coordinator.disabled)
        self.assertEqual(
            coordinator.error.code,
            GameTreeResumeCode.IO_FAILURE,
        )
        self.assertEqual(
            guard.read_bytes(),
            resume_module._DISCARD_GUARD_RESERVATION,
        )

    def test_competing_guard_creation_before_reservation_never_clobbers_it(self) -> None:
        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)
        application.session = self._clean_session(GameTreeCursor((), 1))
        coordinator.prepare_shutdown(application)
        claimed = coordinator.token
        self.assertIsNotNone(claimed)
        application.session = PgnDocumentSession.from_text(PGN)

        guard = self.guard_dir / f"{claimed}.guard"
        original_open = resume_module.os.open
        injected = False

        def create_competitor_then_open(path, flags, mode=0o777):
            nonlocal injected
            candidate = Path(path)
            if not injected and candidate == guard and flags & os.O_EXCL:
                injected = True
                candidate.write_bytes(b"competing-control-state")
            return original_open(path, flags, mode)

        with mock.patch.object(
            resume_module.os,
            "open",
            side_effect=create_competitor_then_open,
        ):
            with self.assertRaises(GameTreeResumeError) as caught:
                coordinator.prepare_shutdown(application)

        self.assertTrue(injected)
        self.assertEqual(caught.exception.code, GameTreeResumeCode.STALE_WRITER)
        self.assertTrue(self.resume_path.exists())
        self.assertEqual(guard.read_bytes(), b"competing-control-state")

    def test_regular_file_at_guard_root_fails_closed_and_is_preserved(self) -> None:
        self.guard_dir.write_bytes(b"not-a-control-directory")
        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertFalse(coordinator.restore(application))
        self.assertTrue(coordinator.disabled)
        self.assertEqual(
            coordinator.error.code,
            GameTreeResumeCode.IO_FAILURE,
        )
        self.assertEqual(
            self.guard_dir.read_bytes(),
            b"not-a-control-directory",
        )

    def test_unknown_guard_entry_fails_closed_and_is_preserved(self) -> None:
        self.guard_dir.mkdir()
        unknown = self.guard_dir / "unknown.guard"
        unknown.write_bytes(b"do-not-delete")
        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertFalse(coordinator.restore(application))
        self.assertTrue(coordinator.disabled)
        self.assertEqual(
            coordinator.error.code,
            GameTreeResumeCode.IO_FAILURE,
        )
        self.assertEqual(unknown.read_bytes(), b"do-not-delete")

    def test_multiple_guard_entries_fail_closed_without_choosing_a_winner(self) -> None:
        first_path, first_token, first_bytes = self._state_file(
            "first.json",
            GameTreeCursor((), 1),
        )
        second_path, second_token, second_bytes = self._state_file(
            "second.json",
            GameTreeCursor((), 2),
        )
        self.guard_dir.mkdir()
        first_guard = self.guard_dir / f"{first_token}.guard"
        second_guard = self.guard_dir / f"{second_token}.guard"
        os.replace(first_path, first_guard)
        os.replace(second_path, second_guard)

        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertFalse(coordinator.restore(application))
        self.assertTrue(coordinator.disabled)
        self.assertEqual(
            coordinator.error.code,
            GameTreeResumeCode.STALE_WRITER,
        )
        self.assertEqual(first_guard.read_bytes(), first_bytes)
        self.assertEqual(second_guard.read_bytes(), second_bytes)

    def test_concurrent_guard_appearing_during_empty_cleanup_fails_closed(self) -> None:
        self.guard_dir.mkdir()
        newcomer = self.guard_dir / f"{'d' * 64}.guard"
        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)
        original_iterdir = Path.iterdir
        guard_dir_reads = 0

        def iterdir_with_race(path: Path):
            nonlocal guard_dir_reads
            if path == self.guard_dir:
                guard_dir_reads += 1
                if guard_dir_reads == 2:
                    newcomer.write_bytes(b"concurrent-control-state")
            return original_iterdir(path)

        with mock.patch.object(Path, "iterdir", new=iterdir_with_race):
            self.assertFalse(coordinator.restore(application))

        self.assertEqual(guard_dir_reads, 2)
        self.assertTrue(coordinator.disabled)
        self.assertEqual(
            coordinator.error.code,
            GameTreeResumeCode.STALE_WRITER,
        )
        self.assertEqual(newcomer.read_bytes(), b"concurrent-control-state")

    def test_concurrent_guard_appearing_after_claimed_guard_removal_fails_closed(self) -> None:
        state = GameTreeResumeStore(self.resume_path).save(
            self.game,
            GameTreeCursor((), 1),
        )
        self.guard_dir.mkdir()
        claimed_guard = self.guard_dir / f"{state.token}.guard"
        os.replace(self.resume_path, claimed_guard)
        newcomer = self.guard_dir / f"{'e' * 64}.guard"
        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)
        original_iterdir = Path.iterdir
        guard_dir_reads = 0

        def iterdir_with_race(path: Path):
            nonlocal guard_dir_reads
            if path == self.guard_dir:
                guard_dir_reads += 1
                if guard_dir_reads == 2:
                    newcomer.write_bytes(b"new-control-state")
            return original_iterdir(path)

        with mock.patch.object(Path, "iterdir", new=iterdir_with_race):
            self.assertFalse(coordinator.restore(application))

        self.assertEqual(guard_dir_reads, 2)
        self.assertTrue(coordinator.disabled)
        self.assertEqual(
            coordinator.error.code,
            GameTreeResumeCode.STALE_WRITER,
        )
        self.assertFalse(claimed_guard.exists())
        self.assertEqual(newcomer.read_bytes(), b"new-control-state")

    def test_guard_replaced_during_quarantine_is_preserved_and_rejected(self) -> None:
        state = GameTreeResumeStore(self.resume_path).save(
            self.game,
            GameTreeCursor((), 1),
        )
        claimed_bytes = self.resume_path.read_bytes()
        competing_path, _, competing_bytes = self._state_file(
            "competing.json",
            GameTreeCursor((), 3),
        )
        self.guard_dir.mkdir()
        guard = self.guard_dir / f"{state.token}.guard"
        os.replace(self.resume_path, guard)
        displaced = self.root / "displaced-claimed.guard"

        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)
        original_replace = resume_module.os.replace
        swapped = False

        def replace_with_guard_swap(source, destination):
            nonlocal swapped
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                not swapped
                and source_path == guard
                and destination_path.name.endswith(
                    resume_module._DISCARD_TOMBSTONE_SUFFIX
                )
            ):
                swapped = True
                original_replace(guard, displaced)
                original_replace(competing_path, guard)
            return original_replace(source, destination)

        with mock.patch.object(
            resume_module.os,
            "replace",
            side_effect=replace_with_guard_swap,
        ):
            self.assertFalse(coordinator.restore(application))

        self.assertTrue(swapped)
        self.assertTrue(coordinator.disabled)
        self.assertEqual(
            coordinator.error.code,
            GameTreeResumeCode.STALE_WRITER,
        )
        self.assertEqual(displaced.read_bytes(), claimed_bytes)
        tombstones = tuple(self.guard_dir.iterdir())
        self.assertEqual(len(tombstones), 1)
        self.assertTrue(
            tombstones[0].name.endswith(resume_module._DISCARD_TOMBSTONE_SUFFIX)
        )
        self.assertEqual(tombstones[0].read_bytes(), competing_bytes)

    def test_crash_left_claimed_tombstone_completes_confirmed_discard(self) -> None:
        state = GameTreeResumeStore(self.resume_path).save(
            self.game,
            GameTreeCursor((), 1),
        )
        self.guard_dir.mkdir()
        tombstone = self.guard_dir / (
            f"{state.token}.{'a' * resume_module._DISCARD_TOMBSTONE_NONCE_HEX}"
            f"{resume_module._DISCARD_TOMBSTONE_SUFFIX}"
        )
        os.replace(self.resume_path, tombstone)

        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertFalse(coordinator.restore(application))
        self.assertFalse(coordinator.disabled)
        self.assertFalse(self.resume_path.exists())
        self.assertFalse(self.guard_dir.exists())

    def test_crash_left_raced_tombstone_is_restored_and_loaded(self) -> None:
        old_path, old_token, _ = self._state_file(
            "old.json",
            GameTreeCursor((), 1),
        )
        old_path.unlink()
        newer_path, newer_token, newer_bytes = self._state_file(
            "newer.json",
            GameTreeCursor((), 3),
        )
        self.guard_dir.mkdir()
        tombstone = self.guard_dir / (
            f"{old_token}.{'b' * resume_module._DISCARD_TOMBSTONE_NONCE_HEX}"
            f"{resume_module._DISCARD_TOMBSTONE_SUFFIX}"
        )
        os.replace(newer_path, tombstone)

        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertTrue(coordinator.restore(application))
        self.assertFalse(coordinator.disabled)
        self.assertEqual(coordinator.token, newer_token)
        self.assertEqual(self.resume_path.read_bytes(), newer_bytes)
        self.assertFalse(self.guard_dir.exists())

    def test_republished_identical_canonical_survives_claimed_tombstone_cleanup(self) -> None:
        state = GameTreeResumeStore(self.resume_path).save(
            self.game,
            GameTreeCursor((), 1),
        )
        original = self.resume_path.read_bytes()
        self.guard_dir.mkdir()
        tombstone = self.guard_dir / (
            f"{state.token}.{'c' * resume_module._DISCARD_TOMBSTONE_NONCE_HEX}"
            f"{resume_module._DISCARD_TOMBSTONE_SUFFIX}"
        )
        tombstone.write_bytes(original)

        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertTrue(coordinator.restore(application))
        self.assertFalse(coordinator.disabled)
        self.assertEqual(coordinator.token, state.token)
        self.assertEqual(self.resume_path.read_bytes(), original)
        self.assertFalse(self.guard_dir.exists())

    def test_empty_guard_directory_is_cleaned_without_creating_resume(self) -> None:
        self.guard_dir.mkdir()
        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)

        self.assertFalse(coordinator.restore(application))
        self.assertFalse(coordinator.disabled)
        self.assertFalse(self.guard_dir.exists())
        self.assertFalse(self.resume_path.exists())

    @unittest.skipIf(os.name == "nt", "POSIX guard-root symlink regression")
    def test_redirected_guard_root_fails_closed(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        self.guard_dir.symlink_to(outside, target_is_directory=True)
        state = GameTreeResumeStore(self.resume_path).save(
            self.game,
            GameTreeCursor((), 1),
        )
        application = _Application()
        coordinator = Version2GameTreeResumeCoordinator(self.resume_path)
        coordinator._token = state.token
        application.session = PgnDocumentSession.from_text(PGN)

        with self.assertRaises(GameTreeResumeError) as caught:
            coordinator.prepare_shutdown(application)

        self.assertEqual(caught.exception.code, GameTreeResumeCode.IO_FAILURE)
        self.assertTrue(self.resume_path.exists())
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
