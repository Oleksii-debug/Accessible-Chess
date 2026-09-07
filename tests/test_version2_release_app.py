from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from acs.keybindings import ActionRegistry
from acs.version2_profile import build_version2_action_registry
from acs.version2_release_app import (
    _install_host_confirmed_document,
    _packaged_legacy_executable,
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

    def test_explicit_v1_bridge_runs_before_upgrade(self) -> None:
        events = []

        class Bridge:
            def __init__(self, layout, executable):
                events.append(("bridge-construct", layout, Path(executable)))
                self.layout = layout

            def run(self):
                events.append(("bridge-run", self.layout, None))

        class Coordinator:
            def __init__(self, layout):
                events.append(("upgrade-construct", layout, None))
                self.layout = layout

            def run(self):
                events.append(("upgrade-run", self.layout, None))

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            executable = base / "legacy" / "AccessibleChess.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"stub")
            layout = _prepare_version2_user_data(
                data_root=base / "v2",
                legacy_executable=executable,
                bridge_factory=Bridge,
                coordinator_factory=Coordinator,
            )

        self.assertEqual(
            [event[0] for event in events],
            ["bridge-construct", "bridge-run", "upgrade-construct", "upgrade-run"],
        )
        self.assertEqual(events[0][2], executable)
        self.assertTrue(all(event[1] is layout for event in events))

    def test_bridge_failure_prevents_upgrade_from_opening(self) -> None:
        events = []

        class Bridge:
            def __init__(self, layout, executable):
                events.append("bridge-construct")

            def run(self):
                events.append("bridge-run")
                raise RuntimeError("synthetic bridge failure")

        def upgrade_factory(_layout):
            events.append("upgrade-construct")
            return object()

        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "AccessibleChess.exe"
            executable.write_bytes(b"stub")
            with self.assertRaisesRegex(RuntimeError, "synthetic bridge failure"):
                _prepare_version2_user_data(
                    data_root=Path(temp) / "v2",
                    legacy_executable=executable,
                    bridge_factory=Bridge,
                    coordinator_factory=upgrade_factory,
                )

        self.assertEqual(events, ["bridge-construct", "bridge-run"])

    def test_source_mode_does_not_probe_python_install_for_v1_data(self) -> None:
        class Upgrade:
            def __init__(self, _layout):
                pass

            def run(self):
                pass

        def bridge_factory(_layout, _executable):
            raise AssertionError("source mode must not construct the legacy bridge")

        self.assertIsNone(_packaged_legacy_executable())
        with tempfile.TemporaryDirectory() as temp:
            _prepare_version2_user_data(
                data_root=Path(temp) / "v2",
                bridge_factory=bridge_factory,
                coordinator_factory=Upgrade,
            )

    def test_clean_install_passes_real_bridge_and_upgrade_coordinators(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            executable = base / "package" / "AccessibleChess.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"stub")
            root = base / "clean-v2"
            layout = _prepare_version2_user_data(
                data_root=root,
                legacy_executable=executable,
            )
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

    def test_prepare_user_data_rejects_invalid_bridge_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "AccessibleChess.exe"
            executable.write_bytes(b"stub")
            with self.assertRaisesRegex(TypeError, "bridge coordinator must expose run"):
                _prepare_version2_user_data(
                    data_root=Path(temp) / "userdata",
                    legacy_executable=executable,
                    bridge_factory=lambda layout, path: object(),
                )


if __name__ == "__main__":
    unittest.main()
