from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from acs.user_data_portability import (
    BundleKind, DomainAdapter, DomainSnapshot,
    UserDataPortabilityCoordinator, UserDataPortabilityError,
)
from acs.user_data_portability_host import UserDataPortabilityHost


class _Owner:
    IsDisposed = False
    Disposing = False
    InvokeRequired = False


class _Dialogs:
    def __init__(self, save=None, open_=None):
        self.save = save
        self.open = open_
        self.calls = []

    def save_bundle(self, action):
        self.calls.append(("save", action))
        return self.save

    def open_bundle(self, action):
        self.calls.append(("open", action))
        return self.open


def _coordinator():
    state = {"settings": b'{"language":"uk"}', "local-account-secret": b"redacted"}
    adapters = []
    for name in ("settings", "local-account-secret"):
        def snapshot(domain=name):
            return DomainSnapshot(domain, 1, state[domain])
        def prepare(value):
            return value
        def restore(value, domain=name):
            state[domain] = value.payload
        adapters.append(DomainAdapter(
            name, snapshot, prepare, restore,
            portable=name == "settings",
        ))
    return UserDataPortabilityCoordinator(tuple(adapters)), state


class Section37ProductionHostTests(unittest.TestCase):
    def test_backup_writes_exclusive_verified_archive_without_returning_path(self):
        coordinator, _ = _coordinator()
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "mine.acbackup"
            dialogs = _Dialogs(save=target)
            host = UserDataPortabilityHost(
                coordinator, owner=lambda: _Owner(), dialogs=dialogs,
            )
            result = host("data.backup", {})
            self.assertTrue(result["ok"])
            self.assertEqual(result["sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
            self.assertEqual(result["domains"], ("local-account-secret", "settings"))
            self.assertNotIn(str(target), repr(result))
            self.assertEqual(dialogs.calls, [("save", "data.backup")])

    def test_export_excludes_nonportable_account_domain(self):
        coordinator, _ = _coordinator()
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "mine.acexport"
            result = UserDataPortabilityHost(
                coordinator, owner=lambda: _Owner(), dialogs=_Dialogs(save=target),
            )("data.export", {})
            self.assertTrue(result["ok"])
            self.assertEqual(result["domains"], ("settings",))
            self.assertNotIn(b"redacted", target.read_bytes())

    def test_no_overwrite_of_existing_user_document(self):
        coordinator, _ = _coordinator()
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "existing.acbackup"
            target.write_bytes(b"DO-NOT-CHANGE")
            host = UserDataPortabilityHost(
                coordinator, owner=lambda: _Owner(), dialogs=_Dialogs(save=target),
            )
            with self.assertRaisesRegex(UserDataPortabilityError, "already exists"):
                host("data.backup", {})
            self.assertEqual(target.read_bytes(), b"DO-NOT-CHANGE")

    def test_fsync_failure_removes_only_owned_partial_archive(self):
        coordinator, _ = _coordinator()
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "partial.acbackup"
            host = UserDataPortabilityHost(
                coordinator, owner=lambda: _Owner(), dialogs=_Dialogs(save=target),
            )
            with patch("acs.user_data_portability_host.os.fsync", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    host("data.backup", {})
            self.assertFalse(target.exists())

    def test_browser_paths_never_reach_native_dialog(self):
        coordinator, _ = _coordinator()
        dialogs = _Dialogs()
        host = UserDataPortabilityHost(
            coordinator, owner=lambda: _Owner(), dialogs=dialogs,
        )
        with self.assertRaisesRegex(UserDataPortabilityError, "no paths"):
            host("data.backup", {"path": "C:\\secret"})
        self.assertEqual(dialogs.calls, [])

    def test_stage_restore_is_verified_and_does_not_mutate_live_owner(self):
        coordinator, state = _coordinator()
        raw, _ = coordinator.create_backup()
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "backup.acbackup"
            target.write_bytes(raw)
            staged = []
            host = UserDataPortabilityHost(
                coordinator, owner=lambda: _Owner(), dialogs=_Dialogs(open_=target),
                stage_for_restart=lambda kind, data: staged.append((kind, data)) or True,
            )
            before = dict(state)
            result = host("data.restore", {})
            self.assertTrue(result["restart_required"])
            self.assertEqual(staged, [(BundleKind.BACKUP, raw)])
            self.assertEqual(state, before)

    def test_corrupt_or_wrong_kind_never_stages(self):
        coordinator, state = _coordinator()
        raw, _ = coordinator.export_user_data()
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "fake.acbackup"
            target.write_bytes(raw)
            staged = []
            host = UserDataPortabilityHost(
                coordinator, owner=lambda: _Owner(), dialogs=_Dialogs(open_=target),
                stage_for_restart=lambda kind, data: staged.append(data) or True,
            )
            with self.assertRaisesRegex(UserDataPortabilityError, "wrong kind"):
                host("data.restore", {})
            target.write_bytes(raw[:-4] + b"oops")
            with self.assertRaises(UserDataPortabilityError):
                host("data.import", {})
            self.assertEqual(staged, [])
            self.assertEqual(state["settings"], b'{"language":"uk"}')

    def test_restore_cannot_be_offered_without_startup_transaction_authority(self):
        coordinator, _ = _coordinator()
        dialogs = _Dialogs()
        host = UserDataPortabilityHost(
            coordinator, owner=lambda: _Owner(), dialogs=dialogs,
        )
        with self.assertRaisesRegex(UserDataPortabilityError, "not configured"):
            host("data.restore", {})
        self.assertEqual(dialogs.calls, [])

    def test_native_owner_thread_affinity_is_enforced(self):
        coordinator, _ = _coordinator()
        dialogs = _Dialogs()
        host = UserDataPortabilityHost(
            coordinator, owner=lambda: _Owner(), dialogs=dialogs,
        )
        errors = []
        def worker():
            try:
                host("data.backup", {})
            except BaseException as exc:
                errors.append(str(exc))
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(len(errors), 1)
        self.assertIn("UI thread", errors[0])
        self.assertEqual(dialogs.calls, [])

    def test_cancel_is_nonmutating(self):
        coordinator, state = _coordinator()
        host = UserDataPortabilityHost(
            coordinator, owner=lambda: _Owner(), dialogs=_Dialogs(save=None),
        )
        before = dict(state)
        result = host("data.backup", {})
        self.assertTrue(result["cancelled"])
        self.assertEqual(before, state)


if __name__ == "__main__":
    unittest.main()
