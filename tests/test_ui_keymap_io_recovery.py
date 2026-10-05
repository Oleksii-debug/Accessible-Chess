import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import acs.ui_keymap_service as keymap_module
from acs.keybindings import ActionRegistry
from acs.ui_keymap_service import KeymapService
from acs.version2_final_product_profile import build_final_product_action_registry


class KeymapPersistedReadIORecoveryTests(unittest.TestCase):
    def test_initial_read_io_failure_blocks_incremental_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keymap.json"
            profile = ActionRegistry().to_profile()
            profile["bindings"]["history.go_to_move"] = "Alt+J"
            original = (json.dumps(profile, sort_keys=True) + "\n").encode("utf-8")
            path.write_bytes(original)

            with patch.object(
                keymap_module,
                "_read_user_keymap_profile",
                side_effect=PermissionError("sharing violation"),
            ):
                service = KeymapService(path, lang="en")

            snapshot = service.snapshot()
            self.assertTrue(snapshot["writeBlocked"])
            self.assertEqual(snapshot["recoveryMessage"], "unreadable keymap profile")

            blocked = service.save("history.go_to_move", "Alt+K")
            self.assertFalse(blocked["ok"])
            self.assertIn("could not be read", blocked["message"])
            self.assertEqual(path.read_bytes(), original)

            # The documented explicit replacement path remains available once the
            # filesystem itself is writable; this is intentionally not an
            # incremental mutation of an unreadable authority file.
            replaced = service.reset_all()
            self.assertTrue(replaced["ok"])
            self.assertFalse(service.snapshot()["writeBlocked"])
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["bindings"]["history.go_to_move"], "Ctrl+G")

    def test_product_registry_adoption_read_failure_blocks_later_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keymap.json"
            profile = ActionRegistry().to_profile()
            profile["bindings"]["history.go_to_move"] = "Alt+J"
            path.write_text(json.dumps(profile), encoding="utf-8")
            original = path.read_bytes()

            service = KeymapService(path, lang="en")
            self.assertFalse(service.snapshot()["writeBlocked"])
            self.assertEqual(
                service.editor.registry.get_binding("history.go_to_move"),
                "Alt+J",
            )

            with patch.object(
                keymap_module,
                "_read_user_keymap_profile",
                side_effect=OSError("device unavailable"),
            ):
                shared = service.adopt_registry(build_final_product_action_registry())

            snapshot = service.snapshot()
            self.assertTrue(snapshot["writeBlocked"])
            self.assertEqual(snapshot["recoveryMessage"], "unreadable keymap profile")
            # The already loaded narrow values remain usable in memory, while the
            # wider registry is still adopted for application dispatch.
            self.assertEqual(shared.get_binding("history.go_to_move"), "Alt+J")

            blocked = service.save("library.open_game", "F8")
            self.assertFalse(blocked["ok"])
            self.assertEqual(path.read_bytes(), original)

    def test_structurally_invalid_profile_is_preserved_until_explicit_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keymap.json"
            original = b'{"schema_version": 1, "bindings": [}'
            path.write_bytes(original)

            service = KeymapService(path, lang="en")

            snapshot = service.snapshot()
            self.assertEqual(snapshot["recoveryMessage"], "invalid keymap profile")
            self.assertTrue(snapshot["writeBlocked"])
            blocked = service.save("history.go_to_move", "Alt+J")
            self.assertFalse(blocked["ok"])
            self.assertIn("invalid", blocked["message"].lower())
            self.assertEqual(path.read_bytes(), original)

            replaced = service.reset_all()
            self.assertTrue(replaced["ok"])
            self.assertFalse(service.snapshot()["writeBlocked"])
            self.assertIsNone(service.snapshot()["recoveryMessage"])
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["bindings"]["history.go_to_move"], "Ctrl+G")

    def test_profile_becoming_invalid_during_product_adoption_is_protected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keymap.json"
            profile = ActionRegistry().to_profile()
            profile["bindings"]["history.go_to_move"] = "Alt+J"
            path.write_text(json.dumps(profile), encoding="utf-8")
            original = path.read_bytes()
            service = KeymapService(path, lang="en")

            with patch.object(
                keymap_module,
                "_read_user_keymap_profile",
                side_effect=ValueError("profile changed into malformed content"),
            ):
                shared = service.adopt_registry(build_final_product_action_registry())

            snapshot = service.snapshot()
            self.assertTrue(snapshot["writeBlocked"])
            self.assertEqual(snapshot["recoveryMessage"], "invalid keymap profile")
            self.assertEqual(shared.get_binding("history.go_to_move"), "Alt+J")
            blocked = service.save("library.open_game", "F8")
            self.assertFalse(blocked["ok"])
            self.assertIn("invalid", blocked["message"].lower())
            self.assertEqual(path.read_bytes(), original)

    def test_incremental_write_failure_rolls_back_live_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keymap.json"
            service = KeymapService(path, lang="en")
            authority = service.editor.registry

            with patch.object(
                ActionRegistry,
                "save",
                side_effect=PermissionError("disk is read-only"),
            ):
                result = service.save("history.go_to_move", "Alt+J")

            self.assertFalse(result["ok"])
            self.assertIn("previous settings remain active", result["message"])
            self.assertIs(service.editor.registry, authority)
            self.assertEqual(authority.get_binding("history.go_to_move"), "Ctrl+G")
            self.assertFalse(path.exists())

    def test_reset_write_failure_restores_live_and_persisted_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keymap.json"
            service = KeymapService(path, lang="en")
            saved = service.save("history.go_to_move", "Alt+J")
            self.assertTrue(saved["ok"])
            original = path.read_bytes()
            authority = service.editor.registry

            with patch.object(
                ActionRegistry,
                "save",
                side_effect=OSError("device unavailable"),
            ):
                result = service.reset_action("history.go_to_move")

            self.assertFalse(result["ok"])
            self.assertIs(service.editor.registry, authority)
            self.assertEqual(authority.get_binding("history.go_to_move"), "Alt+J")
            self.assertEqual(path.read_bytes(), original)

    def test_import_write_failure_restores_shared_registry_identity_and_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keymap.json"
            service = KeymapService(path, lang="en")
            self.assertTrue(service.save("history.go_to_move", "Alt+J")["ok"])
            original = path.read_bytes()
            authority = service.editor.registry
            imported = json.loads(service.export_profile())
            imported["bindings"]["history.go_to_move"] = "Alt+K"

            with patch.object(
                ActionRegistry,
                "save",
                side_effect=PermissionError("write denied"),
            ) as persist:
                result = service.import_profile(json.dumps(imported), allow_warnings=True)
                persist.assert_called_once()

            self.assertFalse(result["ok"])
            self.assertIn("previous settings remain active", result["message"])
            self.assertIs(service.editor.registry, authority)
            self.assertEqual(authority.get_binding("history.go_to_move"), "Alt+J")
            self.assertEqual(path.read_bytes(), original)

    def test_successful_import_keeps_shared_registry_object_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keymap.json"
            service = KeymapService(path, lang="en")
            authority = service.editor.registry
            imported = json.loads(service.export_profile())
            imported["bindings"]["history.go_to_move"] = "Alt+J"

            result = service.import_profile(json.dumps(imported))

            self.assertFalse(result["ok"])
            self.assertTrue(result["requiresConfirmation"])
            self.assertIs(service.editor.registry, authority)
            self.assertFalse(path.exists())
            result = service.import_profile(json.dumps(imported), allow_warnings=True)

            self.assertTrue(result["ok"])
            self.assertIs(service.editor.registry, authority)
            self.assertEqual(authority.get_binding("history.go_to_move"), "Alt+J")
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["bindings"]["history.go_to_move"], "Alt+J")


if __name__ == "__main__":
    unittest.main()
