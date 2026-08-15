import json
import tempfile
import unittest
from pathlib import Path

from acs.keybindings import ActionRegistry
from acs.ui_keymap_service import KeymapService


def profile_with_reserved_shortcut(service: KeymapService) -> str:
    payload = json.loads(service.export_profile())
    payload["bindings"]["history.go_to_move"] = "Ctrl+L"
    return json.dumps(payload)


class KeymapImportWarningConfirmationIntegrationTests(unittest.TestCase):
    def test_risky_profile_import_requires_confirmation_and_is_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keymap.json"
            service = KeymapService(path, lang="en")
            self.assertTrue(service.save("board.current", "F6")["ok"])
            before = path.read_text(encoding="utf-8")
            result = service.import_profile(profile_with_reserved_shortcut(service))
            self.assertFalse(result["ok"])
            self.assertTrue(result["requiresConfirmation"])
            self.assertTrue(any(item["severity"] == "warning" for item in result["conflicts"]))
            self.assertEqual(path.read_text(encoding="utf-8"), before)
            self.assertEqual(service.editor.registry.get_binding("history.go_to_move"), "Ctrl+G")

    def test_risky_profile_import_applies_only_after_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keymap.json"
            service = KeymapService(path, lang="uk")
            profile = profile_with_reserved_shortcut(service)
            blocked = service.import_profile(profile)
            accepted = service.import_profile(profile, allow_warnings=True)
            self.assertFalse(blocked["ok"])
            self.assertTrue(blocked["requiresConfirmation"])
            self.assertTrue(accepted["ok"])
            registry, recovery = ActionRegistry.load(path)
            self.assertIsNone(recovery)
            self.assertEqual(registry.get_binding("history.go_to_move"), "Ctrl+L")

    def test_profile_with_blocking_conflict_cannot_be_forced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keymap.json"
            service = KeymapService(path)
            payload = json.loads(service.export_profile())
            payload["bindings"]["history.previous"] = "Shift+D"
            result = service.import_profile(json.dumps(payload), allow_warnings=True)
            self.assertFalse(result["ok"])
            self.assertFalse(result["requiresConfirmation"])
            self.assertTrue(any(item["severity"] == "error" for item in result["conflicts"]))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
