from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.ui_keymap_service import KeymapService


class KeymapCorruptionSecurityTests(unittest.TestCase):
    def test_saved_profile_rejects_coercive_schema_and_recovers_defaults(self) -> None:
        for schema in (True, False, 1.0, 1.5, "1", None, -1):
            with self.subTest(schema=schema):
                with tempfile.TemporaryDirectory() as td:
                    path = Path(td) / "keymap.json"
                    path.write_text(json.dumps({
                        "schema_version": schema,
                        "bindings": {"history.go_to_move": "Alt+J"},
                        "aliases": {},
                    }), encoding="utf-8")
                    service = KeymapService(path)
                    snap = service.snapshot()
                    by_id = {item["id"]: item for item in snap["actions"]}
                    self.assertEqual(by_id["history.go_to_move"]["binding"], "Ctrl+G")
                    self.assertTrue(snap["recoveryMessage"])

    def test_import_rejects_non_object_containers_and_preserves_file_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "keymap.json"
            service = KeymapService(path, lang="en")
            self.assertTrue(service.save("history.go_to_move", "Alt+J")["ok"])
            baseline = path.read_bytes()
            for payload in (
                {"schema_version": 1, "bindings": [["history.go_to_move", "Ctrl+Q"]], "aliases": {}},
                {"schema_version": 1, "bindings": {}, "aliases": []},
                {"schema_version": True, "bindings": {}, "aliases": {}},
                {"schema_version": "1", "bindings": {}, "aliases": {}},
            ):
                with self.subTest(payload=payload):
                    result = service.import_profile(json.dumps(payload))
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["message"], "Invalid keyboard profile.")
                    self.assertFalse(result["requiresConfirmation"])
                    self.assertEqual(path.read_bytes(), baseline)
                    self.assertEqual(service.editor.registry.get_binding("history.go_to_move"), "Alt+J")

    def test_import_non_text_binding_returns_concise_error_not_python_exception(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            service = KeymapService(Path(td) / "keymap.json", lang="uk")
            payload = {
                "schema_version": 1,
                "bindings": {"history.go_to_move": 123},
                "aliases": {},
            }
            result = service.import_profile(json.dumps(payload))
            self.assertEqual(result, {
                "ok": False,
                "message": "Некоректний профіль клавіш.",
                "conflicts": [],
                "requiresConfirmation": False,
            })
            self.assertNotIn("attribute", result["message"].casefold())
            self.assertNotIn("traceback", result["message"].casefold())

    def test_capture_shortcut_rejects_scalar_key_and_non_boolean_modifiers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            service = KeymapService(Path(td) / "keymap.json", lang="en")
            scalar = service.capture_shortcut("history.go_to_move", 123)  # type: ignore[arg-type]
            coerced_flag = service.capture_shortcut("history.go_to_move", "J", ctrl=1)  # type: ignore[arg-type]
            for result in (scalar, coerced_flag):
                self.assertFalse(result["captured"])
                self.assertEqual(result["reason"], "invalid")
                self.assertEqual(result["message"], "Invalid shortcut")
                self.assertFalse(result["canSave"])
            self.assertEqual(service.editor.registry.get_binding("history.go_to_move"), "Ctrl+G")

    def test_unversioned_legacy_object_shape_remains_supported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            service = KeymapService(Path(td) / "keymap.json")
            payload = {"keys": {"history.go_to_move": "Alt+J"}, "commands": {}}
            result = service.import_profile(json.dumps(payload))
            self.assertTrue(result["ok"], result)
            self.assertEqual(service.editor.registry.get_binding("history.go_to_move"), "Alt+J")


if __name__ == "__main__":
    unittest.main()
