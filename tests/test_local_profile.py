from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
import threading
import traceback
import unittest
from pathlib import Path
from unittest import mock

from acs.local_profile import (
    LocalProfileConflict,
    LocalProfileError,
    LocalProfileStore,
    MAX_DISPLAY_NAME_CHARS,
    MAX_PROFILE_BYTES,
    UnsupportedLocalProfileSchema,
    new_local_profile,
    parse_local_profile_bytes,
    serialize_local_profile,
)


def _hold_profile_mutation_lock(
    profile_path: str,
    ready,
    release,
) -> None:
    store = LocalProfileStore(profile_path)
    with store._mutation_lock():
        ready.set()
        if not release.wait(10):
            raise RuntimeError("timed out waiting to release cross-process profile lock")


def _acquire_profile_mutation_lock(
    profile_path: str,
    attempting,
    acquired,
) -> None:
    store = LocalProfileStore(profile_path)
    attempting.set()
    with store._mutation_lock():
        acquired.set()


class LocalProfileContractTests(unittest.TestCase):
    def test_identity_workflow_qualifies_current_product_merge(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "local-profile-identity.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("Prove current Product merge and exact identity scope", workflow)
        self.assertIn("HEAD^1", workflow)
        self.assertIn("HEAD^2", workflow)
        self.assertIn("PR_BASE_SHA", workflow)
        self.assertIn("PR_HEAD_SHA", workflow)
        self.assertIn("EXACT_THREE_PATHS", workflow)
        self.assertNotIn("live_base", workflow)

    def test_explicit_unicode_name_round_trips(self) -> None:
        profile = new_local_profile("  Олексій   Шахіст  ")
        self.assertEqual(profile.display_name, "Олексій Шахіст")
        self.assertFalse(profile.generated_alias)
        restored = parse_local_profile_bytes(serialize_local_profile(profile))
        self.assertEqual(restored, profile)

    def test_skip_alias_is_random_only_and_does_not_leak_os_identity(self) -> None:
        leaked_markers = {
            "USERNAME": "SECRET-WINDOWS-USER",
            "USER": "SECRET-POSIX-USER",
            "COMPUTERNAME": "SECRET-PC-NAME",
        }
        with mock.patch.dict(os.environ, leaked_markers, clear=False):
            profile = new_local_profile(None)
        self.assertRegex(profile.display_name, r"^Player-[0-9A-F]{8}$")
        self.assertTrue(profile.generated_alias)
        serialized = serialize_local_profile(profile).decode("utf-8")
        for marker in leaked_markers.values():
            self.assertNotIn(marker, serialized)

    def test_duplicate_authority_field_is_rejected(self) -> None:
        profile = new_local_profile("Alex")
        payload = serialize_local_profile(profile).decode("utf-8").strip()
        payload = payload[:-1] + ',"revision":99}'
        with self.assertRaisesRegex(LocalProfileError, "duplicate profile field"):
            parse_local_profile_bytes(payload.encode("utf-8"))

    def test_unknown_and_missing_fields_are_rejected(self) -> None:
        profile = new_local_profile("Alex")
        payload = json.loads(serialize_local_profile(profile))
        payload["unexpected"] = True
        with self.assertRaisesRegex(LocalProfileError, "profile fields are invalid"):
            parse_local_profile_bytes(json.dumps(payload).encode("utf-8"))
        del payload["unexpected"]
        del payload["revision"]
        with self.assertRaisesRegex(LocalProfileError, "profile fields are invalid"):
            parse_local_profile_bytes(json.dumps(payload).encode("utf-8"))

    def test_malformed_utf8_and_oversized_payload_fail_closed(self) -> None:
        with self.assertRaisesRegex(LocalProfileError, "valid UTF-8"):
            parse_local_profile_bytes(b"\xff\xfe\x00")
        with self.assertRaisesRegex(LocalProfileError, "too large"):
            parse_local_profile_bytes(b"{" + b" " * MAX_PROFILE_BYTES + b"}")

    def test_display_name_bounds_and_controls(self) -> None:
        profile = new_local_profile("x" * MAX_DISPLAY_NAME_CHARS)
        self.assertEqual(len(profile.display_name), MAX_DISPLAY_NAME_CHARS)
        with self.assertRaisesRegex(LocalProfileError, "too long"):
            new_local_profile("x" * (MAX_DISPLAY_NAME_CHARS + 1))
        with self.assertRaisesRegex(LocalProfileError, "control"):
            new_local_profile("Alex\nAdmin")


class LocalProfileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = LocalProfileStore(self.root / "profile.json")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _symlink_or_skip(self, target: Path, link: Path) -> None:
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are not permitted in this environment")

    def test_create_skip_persists_same_alias_and_identifier(self) -> None:
        created = self.store.create(None)
        reopened = LocalProfileStore(self.store.path).load()
        self.assertEqual(reopened, created)
        self.assertRegex(created.profile_id, r"^[0-9a-f]{32}$")
        self.assertTrue(created.generated_alias)

    def test_create_refuses_to_replace_existing_identity(self) -> None:
        first = self.store.create("Alice")
        before = self.store.path.read_bytes()
        with self.assertRaises(LocalProfileConflict):
            self.store.create("Bob")
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.store.load(), first)

    def test_rename_preserves_identity_creates_exact_backup_and_increments_revision(self) -> None:
        original = self.store.create(None)
        original_bytes = self.store.path.read_bytes()
        renamed = self.store.rename(original, "  Alice   Coach ")
        self.assertEqual(renamed.profile_id, original.profile_id)
        self.assertEqual(renamed.display_name, "Alice Coach")
        self.assertFalse(renamed.generated_alias)
        self.assertEqual(renamed.revision, original.revision + 1)
        self.assertEqual(self.store.backup_path.read_bytes(), original_bytes)
        self.assertEqual(self.store.load(), renamed)

    def test_stale_rename_cannot_clobber_newer_state(self) -> None:
        original = self.store.create("Alice")
        current = self.store.rename(original, "Alice Two")
        before = self.store.path.read_bytes()
        with self.assertRaises(LocalProfileConflict):
            self.store.rename(original, "Stale Writer")
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.store.load(), current)

        # A rejected writer must release the process lock for the next valid
        # mutation instead of stranding the profile in a locally deadlocked state.
        final = self.store.rename(current, "Alice Three")
        self.assertEqual(final.revision, current.revision + 1)
        self.assertEqual(self.store.load(), final)

    def test_concurrent_renames_serialize_before_revision_check(self) -> None:
        original = self.store.create("Alice")
        first_publish_entered = threading.Event()
        release_first_publish = threading.Event()
        overlapping_publish = threading.Event()
        counter_guard = threading.Lock()
        result_guard = threading.Lock()
        active_backup_writers = 0
        results: list[tuple[str, object]] = []

        class CoordinatedStore(LocalProfileStore):
            def _atomic_replace_bytes(inner_self, target: Path, payload: bytes) -> None:
                nonlocal active_backup_writers
                if target != inner_self.backup_path:
                    return super()._atomic_replace_bytes(target, payload)

                with counter_guard:
                    active_backup_writers += 1
                    is_first = active_backup_writers == 1
                    if is_first:
                        first_publish_entered.set()
                    else:
                        overlapping_publish.set()
                try:
                    if is_first and not release_first_publish.wait(5):
                        raise RuntimeError("timed out waiting to release first profile writer")
                    return super()._atomic_replace_bytes(target, payload)
                finally:
                    with counter_guard:
                        active_backup_writers -= 1

        first_store = CoordinatedStore(self.store.path)
        second_store = CoordinatedStore(self.store.path)

        def rename(store: LocalProfileStore, display_name: str) -> None:
            try:
                outcome: tuple[str, object] = ("ok", store.rename(original, display_name))
            except Exception as exc:  # Capture worker result for the main test thread.
                outcome = ("error", exc)
            with result_guard:
                results.append(outcome)

        first = threading.Thread(target=rename, args=(first_store, "First Writer"), daemon=True)
        second = threading.Thread(target=rename, args=(second_store, "Second Writer"), daemon=True)
        first.start()
        self.assertTrue(first_publish_entered.wait(5), "first writer never reached publication")
        second.start()

        # The second writer must remain outside publication while the first
        # writer owns the stable sibling mutation lock.
        self.assertFalse(
            overlapping_publish.wait(0.25),
            "concurrent profile writers reached publication at the same time",
        )
        release_first_publish.set()
        first.join(5)
        second.join(5)
        self.assertFalse(first.is_alive(), "first profile writer did not finish")
        self.assertFalse(second.is_alive(), "second profile writer did not finish")

        successes = [value for kind, value in results if kind == "ok"]
        errors = [value for kind, value in results if kind == "error"]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], LocalProfileConflict)
        durable = self.store.load()
        self.assertEqual(durable, successes[0])
        self.assertEqual(durable.revision, original.revision + 1)

    def test_mutation_lock_contains_no_profile_identity_data(self) -> None:
        profile = self.store.create("Private Name")
        self.assertTrue(self.store.lock_path.exists())
        self.assertEqual(self.store.lock_path.read_bytes(), b"")
        lock_bytes = self.store.lock_path.read_bytes()
        self.assertNotIn(profile.profile_id.encode("ascii"), lock_bytes)
        self.assertNotIn(profile.display_name.encode("utf-8"), lock_bytes)

    def test_mutation_lock_serializes_independent_processes(self) -> None:
        self.store.create("Alice")
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        release = context.Event()
        attempting = context.Event()
        acquired = context.Event()
        holder = context.Process(
            target=_hold_profile_mutation_lock,
            args=(str(self.store.path), ready, release),
        )
        waiter = context.Process(
            target=_acquire_profile_mutation_lock,
            args=(str(self.store.path), attempting, acquired),
        )
        try:
            holder.start()
            self.assertTrue(ready.wait(10), "holder process did not acquire profile lock")
            waiter.start()
            self.assertTrue(attempting.wait(10), "waiter process did not start lock attempt")
            self.assertFalse(
                acquired.wait(0.35),
                "independent process entered profile mutation lock before release",
            )
            release.set()
            self.assertTrue(acquired.wait(10), "waiter process never acquired released profile lock")
        finally:
            release.set()
            holder.join(10)
            waiter.join(10)
            if holder.is_alive():
                holder.terminate()
                holder.join(5)
            if waiter.is_alive():
                waiter.terminate()
                waiter.join(5)
        self.assertEqual(holder.exitcode, 0)
        self.assertEqual(waiter.exitcode, 0)

    def test_corrupt_primary_recovers_from_verified_backup_without_rewriting(self) -> None:
        original = self.store.create("Alice")
        renamed = self.store.rename(original, "Alice Two")
        backup_before = self.store.backup_path.read_bytes()
        corrupt = b"{not-json"
        self.store.path.write_bytes(corrupt)
        recovered = self.store.load()
        self.assertEqual(recovered, original)
        self.assertNotEqual(recovered, renamed)
        self.assertEqual(self.store.path.read_bytes(), corrupt)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)

    def test_missing_primary_recovers_from_backup_instead_of_fabricating_identity(self) -> None:
        original = self.store.create("Alice")
        self.store.rename(original, "Alice Two")
        self.store.path.unlink()
        recovered = self.store.load()
        self.assertEqual(recovered, original)
        with self.assertRaises(LocalProfileConflict):
            self.store.create("Replacement")
        self.assertFalse(self.store.path.exists())

    def test_explicit_repair_restores_missing_primary_then_allows_rename(self) -> None:
        original = self.store.create("Alice")
        self.store.rename(original, "Alice Two")
        backup_before = self.store.backup_path.read_bytes()
        self.store.path.unlink()

        repaired = self.store.repair_from_backup()
        self.assertEqual(repaired, original)
        self.assertEqual(self.store.path.read_bytes(), backup_before)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)

        renamed = self.store.rename(repaired, "Alice Recovered")
        self.assertEqual(renamed.profile_id, original.profile_id)
        self.assertEqual(renamed.display_name, "Alice Recovered")
        self.assertEqual(renamed.revision, original.revision + 1)

    def test_explicit_repair_replaces_corrupt_primary_only_from_verified_backup(self) -> None:
        original = self.store.create("Alice")
        self.store.rename(original, "Alice Two")
        backup_before = self.store.backup_path.read_bytes()
        self.store.path.write_bytes(b"corrupt-primary")

        repaired = self.store.repair_from_backup()
        self.assertEqual(repaired, original)
        self.assertEqual(self.store.path.read_bytes(), backup_before)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)

    def test_both_unreadable_refuse_fresh_identity_and_preserve_bytes(self) -> None:
        original = self.store.create("Alice")
        self.store.rename(original, "Alice Two")
        self.store.path.write_bytes(b"bad-primary")
        self.store.backup_path.write_bytes(b"bad-backup")
        primary_before = self.store.path.read_bytes()
        backup_before = self.store.backup_path.read_bytes()
        with self.assertRaises(LocalProfileError):
            self.store.load()
        with self.assertRaises(LocalProfileError):
            self.store.create("Replacement")
        with self.assertRaises(LocalProfileError):
            self.store.repair_from_backup()
        self.assertEqual(self.store.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)

    def test_future_primary_never_downgrades_to_older_backup(self) -> None:
        original = self.store.create("Alice")
        self.store.rename(original, "Alice Two")
        future = json.loads(self.store.path.read_text(encoding="utf-8"))
        future["schema_version"] = 2
        future_bytes = (json.dumps(future, separators=(",", ":")) + "\n").encode("utf-8")
        self.store.path.write_bytes(future_bytes)
        backup_before = self.store.backup_path.read_bytes()
        with self.assertRaises(UnsupportedLocalProfileSchema):
            self.store.load()
        with self.assertRaises(UnsupportedLocalProfileSchema):
            self.store.create("Replacement")
        with self.assertRaises(UnsupportedLocalProfileSchema):
            self.store.repair_from_backup()
        self.assertEqual(self.store.path.read_bytes(), future_bytes)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)

    def test_unreadable_primary_is_not_overwritten_even_with_good_backup(self) -> None:
        original = self.store.create("Alice")
        current = self.store.rename(original, "Alice Two")
        self.store.path.write_bytes(b"corrupt")
        primary_before = self.store.path.read_bytes()
        backup_before = self.store.backup_path.read_bytes()
        with self.assertRaises(LocalProfileError):
            self.store.rename(current, "Alice Three")
        self.assertEqual(self.store.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)

    def test_primary_replace_failure_keeps_previous_identity_and_verified_backup(self) -> None:
        original = self.store.create("Alice")
        real_replace = os.replace

        def fail_primary_replace(source: str, target: str | os.PathLike[str]) -> None:
            if Path(target) == self.store.path:
                raise OSError("injected write failure")
            real_replace(source, target)

        with mock.patch("acs.local_profile.os.replace", side_effect=fail_primary_replace):
            with self.assertRaisesRegex(LocalProfileError, "could not be saved") as caught:
                self.store.rename(original, "Alice Two")
        self.assertIsNone(caught.exception.__cause__)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn("injected write failure", rendered)
        self.assertEqual(self.store.load(), original)
        self.assertEqual(parse_local_profile_bytes(self.store.backup_path.read_bytes()), original)

    def test_lock_open_failure_is_sanitized_before_any_profile_publication(self) -> None:
        with mock.patch(
            "acs.local_profile.os.open",
            side_effect=OSError(r"SECRET-PROFILE-PATH C:\\Users\\private\\profile.lock"),
        ):
            with self.assertRaisesRegex(
                LocalProfileError,
                "^local profile mutation lock is unavailable$",
            ) as caught:
                self.store.create("Alice")

        self.assertIsNone(caught.exception.__cause__)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn("SECRET-PROFILE-PATH", rendered)
        self.assertNotIn("Users", rendered)
        self.assertFalse(self.store.path.exists())
        self.assertFalse(self.store.backup_path.exists())

    def test_lock_seek_failure_is_sanitized_and_releases_open_descriptor(self) -> None:
        with mock.patch(
            "acs.local_profile.os.lseek",
            side_effect=OSError("SECRET-LOCK-SEEK"),
        ):
            with self.assertRaisesRegex(
                LocalProfileError,
                "^local profile mutation lock is unavailable$",
            ) as caught:
                self.store.create("Alice")

        self.assertIsNone(caught.exception.__cause__)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn("SECRET-LOCK-SEEK", rendered)
        self.assertFalse(self.store.path.exists())

    def test_lock_close_failure_after_commit_does_not_falsify_success(self) -> None:
        original = self.store.create("Alice")
        real_close = os.close
        close_calls = []

        def close_then_fail(fd: int) -> None:
            close_calls.append(fd)
            real_close(fd)
            raise OSError("SECRET-POST-COMMIT-CLOSE")

        with mock.patch("acs.local_profile.os.close", side_effect=close_then_fail):
            renamed = self.store.rename(original, "Alice Two")

        self.assertTrue(close_calls)
        self.assertEqual(renamed.display_name, "Alice Two")
        self.assertEqual(renamed.revision, original.revision + 1)
        self.assertEqual(self.store.load(), renamed)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_mutation_lock_symlink_is_rejected_without_touching_target(self) -> None:
        original = self.store.create("Alice")
        primary_before = self.store.path.read_bytes()
        self.store.lock_path.unlink()
        target = self.root / "hostile-lock-target.bin"
        target.write_bytes(b"do-not-touch")
        target_before = target.read_bytes()
        self._symlink_or_skip(target, self.store.lock_path)

        with self.assertRaisesRegex(LocalProfileError, "symbolic link"):
            self.store.rename(original, "Alice Two")

        self.assertEqual(self.store.path.read_bytes(), primary_before)
        self.assertEqual(target.read_bytes(), target_before)
        self.assertTrue(self.store.lock_path.is_symlink())

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_existing_symlink_profile_is_rejected(self) -> None:
        target = self.root / "target.json"
        target.write_bytes(serialize_local_profile(new_local_profile("Target")))
        link = self.root / "link.json"
        self._symlink_or_skip(target, link)
        linked_store = LocalProfileStore(link)
        with self.assertRaisesRegex(LocalProfileError, "symbolic link"):
            linked_store.load()

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_primary_symlink_never_falls_back_to_valid_backup(self) -> None:
        original = self.store.create("Alice")
        self.store.rename(original, "Alice Two")
        backup_before = self.store.backup_path.read_bytes()
        target = self.root / "hostile-primary-target.json"
        target.write_bytes(serialize_local_profile(new_local_profile("Target")))
        target_before = target.read_bytes()
        self.store.path.unlink()
        self._symlink_or_skip(target, self.store.path)

        with self.assertRaisesRegex(LocalProfileError, "symbolic link"):
            self.store.load()
        with self.assertRaisesRegex(LocalProfileError, "symbolic link"):
            self.store.repair_from_backup()

        self.assertTrue(self.store.path.is_symlink())
        self.assertEqual(target.read_bytes(), target_before)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_backup_symlink_is_not_accepted_as_recovery_authority(self) -> None:
        original = self.store.create("Alice")
        self.store.rename(original, "Alice Two")
        self.store.path.unlink()
        self.store.backup_path.unlink()
        target = self.root / "hostile-backup-target.json"
        target.write_bytes(serialize_local_profile(new_local_profile("Target")))
        target_before = target.read_bytes()
        self._symlink_or_skip(target, self.store.backup_path)

        with self.assertRaisesRegex(LocalProfileError, "symbolic link"):
            self.store.load()
        with self.assertRaisesRegex(LocalProfileError, "symbolic link"):
            self.store.repair_from_backup()
        with self.assertRaisesRegex(LocalProfileError, "symbolic link"):
            self.store.create("Replacement")

        self.assertFalse(self.store.path.exists())
        self.assertTrue(self.store.backup_path.is_symlink())
        self.assertEqual(target.read_bytes(), target_before)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_broken_backup_symlink_cannot_be_replaced_during_publish(self) -> None:
        original = self.store.create("Alice")
        primary_before = self.store.path.read_bytes()
        missing_target = self.root / "missing-target.json"
        self._symlink_or_skip(missing_target, self.store.backup_path)
        self.assertTrue(self.store.backup_path.is_symlink())
        self.assertFalse(self.store.backup_path.exists())

        with self.assertRaisesRegex(LocalProfileError, "symbolic link"):
            self.store.rename(original, "Alice Two")

        self.assertEqual(self.store.path.read_bytes(), primary_before)
        self.assertTrue(self.store.backup_path.is_symlink())
        self.assertFalse(missing_target.exists())


if __name__ == "__main__":
    unittest.main()
