from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from acs.keybindings import ActionRegistry
from acs.ui_keymap_service import KeymapService
from acs.version2_profile import build_version2_action_registry
from acs.version2_release_app import (
    _install_host_confirmed_document,
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
        with tempfile.TemporaryDirectory() as temp:
            service = KeymapService(Path(temp) / "keymap.json")
            service.editor.registry.set_binding("board.current", "Ctrl+F12")
            service.editor.registry.set_alias("move.undo", "back")
            api = SimpleNamespace(keymap_service=service)
            v2 = build_version2_action_registry()
            application = SimpleNamespace(adapter=SimpleNamespace(registry=v2))

            shared = _share_v2_action_registry(api, application)

            self.assertIs(shared, v2)
            self.assertIs(api.keymap_service.editor.registry, v2)
            self.assertEqual(v2.get_binding("board.current"), "Ctrl+F12")
            self.assertEqual(v2.get_alias("move.undo"), "back")
            self.assertIsNotNone(v2.definition("screen.library"))

    def test_full_product_keymap_remap_survives_release_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "keymap.json"

            first_service = KeymapService(profile)
            first_v2 = build_version2_action_registry()
            _share_v2_action_registry(
                SimpleNamespace(keymap_service=first_service),
                SimpleNamespace(adapter=SimpleNamespace(registry=first_v2)),
            )
            self.assertTrue(first_service.save("pgn.next_item", "J")["ok"])
            self.assertEqual(first_v2.get_binding("pgn.next_item"), "J")

            restarted_service = KeymapService(profile)
            restarted_v2 = build_version2_action_registry()
            shared = _share_v2_action_registry(
                SimpleNamespace(keymap_service=restarted_service),
                SimpleNamespace(adapter=SimpleNamespace(registry=restarted_v2)),
            )

            self.assertIs(shared, restarted_v2)
            self.assertEqual(restarted_v2.get_binding("pgn.next_item"), "J")
            self.assertIsNone(
                restarted_v2.resolve_binding(
                    restarted_v2.definition("pgn.next_item").context,
                    "Down",
                )
            )
            snapshot = restarted_service.snapshot()
            rows = {item["id"]: item for item in snapshot["actions"]}
            self.assertEqual(rows["pgn.next_item"]["binding"], "J")
            self.assertEqual(rows["pgn.next_item"]["context"], "pgn_tree")

    def test_full_product_keymap_swap_rebind_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "keymap.json"
            source = build_version2_action_registry()
            payload = source.to_profile()
            payload["bindings"]["pgn.previous_item"] = "Down"
            payload["bindings"]["pgn.next_item"] = "Up"
            profile.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            restarted_service = KeymapService(profile)
            restarted_v2 = build_version2_action_registry()
            shared = _share_v2_action_registry(
                SimpleNamespace(keymap_service=restarted_service),
                SimpleNamespace(adapter=SimpleNamespace(registry=restarted_v2)),
            )

            self.assertIs(shared, restarted_v2)
            context = restarted_v2.definition("pgn.previous_item").context
            self.assertEqual(
                restarted_v2.resolve_binding(context, "Down").action_id,
                "pgn.previous_item",
            )
            self.assertEqual(
                restarted_v2.resolve_binding(context, "Up").action_id,
                "pgn.next_item",
            )

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
