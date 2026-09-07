from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from acs.keybindings import ActionRegistry
from acs.version2_profile import build_version2_action_registry
from acs.version2_release_app import (
    _install_close_guard_or_shutdown,
    _install_host_confirmed_document,
    _install_unsaved_pgn_close_guard,
    _prepare_version2_user_data,
    _share_v2_action_registry,
    _version2_user_data_layout,
)


class _Application:
    def __init__(self) -> None:
        self.confirm_calls = 0
        self.installed = []

        def original_confirmation() -> bool:
            self.confirm_calls += 1
            return False

        self.confirm_document_replace = original_confirmation

    def set_document(self, session):
        if not self.confirm_document_replace():
            raise RuntimeError("replacement was not host-confirmed")
        self.installed.append(session)
        return session


class _FormClosingEvent:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self, event) -> None:
        for handler in tuple(self.handlers):
            handler(None, event)


class _OwnerForm:
    def __init__(self) -> None:
        self.FormClosing = _FormClosingEvent()


class _ExitDialogs:
    def __init__(self, result=True, *, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def confirm_discard_unsaved_pgn_on_exit(self) -> bool:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class _CloseTrackedRuntime:
    def __init__(self, *, result: bool = True, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class Version2ReleaseAppTests(unittest.TestCase):
    def test_trusted_host_confirmation_is_not_requested_twice(self) -> None:
        application = _Application()
        original = application.confirm_document_replace
        session = object()

        result = _install_host_confirmed_document(application, session)

        self.assertIs(result, session)
        self.assertEqual(application.installed, [session])
        self.assertEqual(application.confirm_calls, 0)
        self.assertIs(application.confirm_document_replace, original)

    def test_confirmation_callback_is_restored_after_install_failure(self) -> None:
        application = _Application()
        original = application.confirm_document_replace

        def failing_set_document(_session):
            self.assertTrue(application.confirm_document_replace())
            raise ValueError("synthetic install failure")

        application.set_document = failing_set_document
        with self.assertRaisesRegex(ValueError, "synthetic install failure"):
            _install_host_confirmed_document(application, object())

        self.assertIs(application.confirm_document_replace, original)
        self.assertEqual(application.confirm_calls, 0)

    def test_native_close_guard_does_not_prompt_for_clean_pgn(self) -> None:
        application = SimpleNamespace(session=SimpleNamespace(dirty=False))
        owner = _OwnerForm()
        dialogs = _ExitDialogs(False)
        event = SimpleNamespace(Cancel=False)

        _install_unsaved_pgn_close_guard(application, owner, dialogs)
        owner.FormClosing.fire(event)

        self.assertFalse(event.Cancel)
        self.assertEqual(dialogs.calls, 0)

    def test_native_close_guard_cancels_dirty_exit_when_user_refuses(self) -> None:
        application = SimpleNamespace(session=SimpleNamespace(dirty=True))
        owner = _OwnerForm()
        dialogs = _ExitDialogs(False)
        event = SimpleNamespace(Cancel=False)

        _install_unsaved_pgn_close_guard(application, owner, dialogs)
        owner.FormClosing.fire(event)

        self.assertTrue(event.Cancel)
        self.assertEqual(dialogs.calls, 1)

    def test_native_close_guard_allows_explicit_dirty_discard(self) -> None:
        application = SimpleNamespace(session=SimpleNamespace(dirty=True))
        owner = _OwnerForm()
        dialogs = _ExitDialogs(True)
        event = SimpleNamespace(Cancel=False)

        _install_unsaved_pgn_close_guard(application, owner, dialogs)
        owner.FormClosing.fire(event)

        self.assertFalse(event.Cancel)
        self.assertEqual(dialogs.calls, 1)

    def test_native_close_guard_fails_closed_when_confirmation_fails(self) -> None:
        application = SimpleNamespace(session=SimpleNamespace(dirty=True))
        owner = _OwnerForm()
        dialogs = _ExitDialogs(error=RuntimeError("synthetic dialog failure"))
        event = SimpleNamespace(Cancel=False)

        _install_unsaved_pgn_close_guard(application, owner, dialogs)
        owner.FormClosing.fire(event)

        self.assertTrue(event.Cancel)
        self.assertEqual(dialogs.calls, 1)

    def test_native_close_guard_rejects_duplicate_installation(self) -> None:
        application = SimpleNamespace(session=None)
        owner = _OwnerForm()
        dialogs = _ExitDialogs(True)

        _install_unsaved_pgn_close_guard(application, owner, dialogs)
        with self.assertRaisesRegex(RuntimeError, "already installed"):
            _install_unsaved_pgn_close_guard(application, owner, dialogs)
        self.assertEqual(len(owner.FormClosing.handlers), 1)

    def test_unbound_file_runtime_is_closed_when_close_guard_installation_fails(self) -> None:
        application = SimpleNamespace(session=None)
        runtime = _CloseTrackedRuntime()
        dialogs = _ExitDialogs(True)

        with self.assertRaisesRegex(RuntimeError, "does not expose FormClosing"):
            _install_close_guard_or_shutdown(runtime, application, object(), dialogs)

        self.assertEqual(runtime.shutdown_calls, 1)

    def test_close_guard_failure_never_hides_unbound_runtime_cleanup_failure(self) -> None:
        application = SimpleNamespace(session=None)
        runtime = _CloseTrackedRuntime(result=False)
        dialogs = _ExitDialogs(True)

        with self.assertRaisesRegex(RuntimeError, "unbound native runtime cleanup failed"):
            _install_close_guard_or_shutdown(runtime, application, object(), dialogs)

        self.assertEqual(runtime.shutdown_calls, 1)

    def test_shared_v2_registry_preserves_stage1_user_remaps(self) -> None:
        stage1 = ActionRegistry()
        stage1.set_binding("board.current", "Ctrl+F12")
        stage1.set_alias("move.undo", "back")
        api = SimpleNamespace(
            keymap_service=SimpleNamespace(editor=SimpleNamespace(registry=stage1))
        )
        v2 = build_version2_action_registry()
        application = SimpleNamespace(adapter=SimpleNamespace(registry=v2))

        shared = _share_v2_action_registry(api, application)

        self.assertIs(shared, v2)
        self.assertIs(api.keymap_service.editor.registry, v2)
        self.assertEqual(v2.get_binding("board.current"), "Ctrl+F12")
        self.assertEqual(v2.get_alias("move.undo"), "back")
        self.assertIsNotNone(v2.definition("screen.library"))

    def test_custom_settings_and_library_share_one_v2_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "userdata"
            layout = _version2_user_data_layout(
                data_root=root,
                settings_path=root / "preferences.json",
            )

        self.assertEqual(layout.root, root)
        self.assertEqual(layout.settings_path, root / "preferences.json")
        self.assertEqual(layout.library_path, root / "library.acsdb")
        self.assertEqual(layout.lock_path.parent, root)

    def test_settings_path_cannot_split_v2_persistent_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "userdata"
            other = Path(temp) / "other" / "settings.json"
            with self.assertRaisesRegex(ValueError, "must belong"):
                _version2_user_data_layout(data_root=root, settings_path=other)

    def test_prepare_user_data_runs_upgrade_before_returning_layout(self) -> None:
        events = []

        class Coordinator:
            def __init__(self, layout):
                events.append(("construct", layout))
                self.layout = layout

            def run(self):
                events.append(("run", self.layout))

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "userdata"
            layout = _prepare_version2_user_data(
                data_root=root,
                coordinator_factory=Coordinator,
            )

        self.assertEqual([kind for kind, _ in events], ["construct", "run"])
        self.assertIs(events[0][1], layout)
        self.assertIs(events[1][1], layout)
        self.assertEqual(layout.root, root)

    def test_clean_install_passes_real_upgrade_coordinator(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "clean-v2"
            layout = _prepare_version2_user_data(data_root=root)
            self.assertTrue(root.is_dir())
            self.assertEqual(layout.settings_path, root / "settings.json")
            self.assertEqual(layout.library_path, root / "library.acsdb")
            self.assertFalse(layout.journal_path.exists())

    def test_prepare_user_data_rejects_invalid_coordinator_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(TypeError, "must expose run"):
                _prepare_version2_user_data(
                    data_root=Path(temp) / "userdata",
                    coordinator_factory=lambda layout: object(),
                )


if __name__ == "__main__":
    unittest.main()
