from __future__ import annotations

import unittest

from acs.keybindings import (
    ActionRegistry,
    BindingContext,
    MAX_KEYMAP_JSON_BYTES,
    normalize_binding,
)


class KeybindingPassiveBoundaryTests(unittest.TestCase):
    def test_hostile_text_subclasses_are_rejected_before_text_or_hash_hooks(self) -> None:
        class HostileText(str):
            touched = False

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile strip hook must not execute")

            def casefold(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile casefold hook must not execute")

            def replace(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile replace hook must not execute")

            def split(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile split hook must not execute")

            def encode(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile encode hook must not execute")

            def __len__(self):
                type(self).touched = True
                raise AssertionError("hostile length hook must not execute")

            def __eq__(self, other):
                type(self).touched = True
                raise AssertionError("hostile equality hook must not execute")

            def __hash__(self):
                type(self).touched = True
                raise AssertionError("hostile hash hook must not execute")

        hostile = HostileText("Ctrl+G")
        registry = ActionRegistry()

        operations = (
            lambda: normalize_binding(hostile),
            lambda: registry.definition(hostile),
            lambda: registry.get_binding(hostile),
            lambda: registry.set_binding(hostile, "Ctrl+J"),
            lambda: registry.set_binding("history.go_to_move", hostile),
            lambda: registry.set_alias("move.clear", hostile),
            lambda: registry.resolve_binding(BindingContext.HISTORY, hostile),
            lambda: registry.resolve_alias(BindingContext.MOVE_ENTRY, hostile),
            lambda: ActionRegistry.import_json(hostile),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises((TypeError, ValueError)):
                    operation()
                self.assertFalse(HostileText.touched)

    def test_allow_warnings_rejects_active_truthiness(self) -> None:
        class ActiveFlag:
            touched = False

            def __bool__(self):
                type(self).touched = True
                raise AssertionError("allow_warnings truth hook must not execute")

        with self.assertRaisesRegex(TypeError, "allow_warnings must be boolean"):
            ActionRegistry().set_binding(
                "history.go_to_move",
                "Alt+F4",
                allow_warnings=ActiveFlag(),
            )
        self.assertFalse(ActiveFlag.touched)

    def test_schema_version_rejects_active_integer_coercion(self) -> None:
        class ActiveVersion:
            touched = False

            def __int__(self):
                type(self).touched = True
                raise AssertionError("schema version coercion hook must not execute")

        with self.assertRaisesRegex(ValueError, "invalid schema_version"):
            ActionRegistry.from_profile(
                {
                    "schema_version": ActiveVersion(),
                    "bindings": {},
                    "aliases": {},
                }
            )
        self.assertFalse(ActiveVersion.touched)

    def test_nested_profile_mappings_must_be_plain_json_objects(self) -> None:
        class ActiveDict(dict):
            touched = False

            def __bool__(self):
                type(self).touched = True
                raise AssertionError("profile mapping truth hook must not execute")

            def items(self):
                type(self).touched = True
                raise AssertionError("profile mapping items hook must not execute")

        active = ActiveDict()
        with self.assertRaisesRegex(ValueError, "invalid keymap profile"):
            ActionRegistry.from_profile(
                {
                    "schema_version": 1,
                    "bindings": active,
                    "aliases": {},
                }
            )
        self.assertFalse(ActiveDict.touched)

    def test_direct_json_profile_has_bounded_utf8_envelope(self) -> None:
        with self.assertRaisesRegex(ValueError, "too large"):
            ActionRegistry.import_json(" " * (MAX_KEYMAP_JSON_BYTES + 1))

        multibyte = "é" * (MAX_KEYMAP_JSON_BYTES // 2 + 1)
        self.assertLessEqual(len(multibyte), MAX_KEYMAP_JSON_BYTES)
        with self.assertRaisesRegex(ValueError, "too large"):
            ActionRegistry.import_json(multibyte)

        with self.assertRaisesRegex(ValueError, "valid UTF-8"):
            ActionRegistry.import_json("\ud800")

    def test_duplicate_json_object_keys_fail_closed_at_every_level(self) -> None:
        malformed_profiles = (
            '{"schema_version":1,"schema_version":1,"bindings":{},"aliases":{}}',
            '{"schema_version":1,"bindings":{"history.go_to_move":"Ctrl+J","history.go_to_move":"Ctrl+K"},"aliases":{}}',
            '{"schema_version":1,"bindings":{},"aliases":{},"future":{"x":1,"x":2}}',
            '{"schema_version":1,"bindings":{"history.go_to_move":"Ctrl+J","history.go_to_move":"Ctrl+K"},"aliases":{}}'.replace(
                '"history.go_to_move":"Ctrl+K"',
                '"history\\u002ego_to_move":"Ctrl+K"',
            ),
        )
        for raw in malformed_profiles:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError, "duplicate JSON object keys"):
                    ActionRegistry.import_json(raw)

    def test_duplicate_json_on_disk_recovers_without_reinterpreting_profile(self) -> None:
        import tempfile
        from pathlib import Path

        raw = '{"schema_version":1,"bindings":{"history.go_to_move":"Ctrl+J","history.go_to_move":"Alt+F4"},"aliases":{}}'
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "keymap.json"
            path.write_text(raw, encoding="utf-8")
            registry, warning = ActionRegistry.load(path)
            self.assertIsNotNone(warning)
            self.assertIn("duplicate JSON object keys", warning)
            self.assertEqual(registry.get_binding("history.go_to_move"), "Ctrl+G")
            self.assertEqual(path.read_text(encoding="utf-8"), raw)

    def test_exact_builtin_values_keep_existing_keymap_semantics(self) -> None:
        registry = ActionRegistry()
        self.assertEqual(normalize_binding("control-shift-z"), "Ctrl+Shift+Z")
        registry.set_binding("history.go_to_move", "Ctrl+J")
        registry.set_alias("move.clear", "Z")
        self.assertEqual(
            registry.resolve_binding(BindingContext.HISTORY, "ctrl+j").action_id,
            "history.go_to_move",
        )
        self.assertEqual(
            registry.resolve_alias(BindingContext.MOVE_ENTRY, "z").action_id,
            "move.clear",
        )

        clone = ActionRegistry.import_json(registry.export_json())
        self.assertEqual(clone.get_binding("history.go_to_move"), "Ctrl+J")
        self.assertEqual(clone.get_alias("move.clear"), "z")

        legacy = ActionRegistry.from_profile(
            {
                "schema_version": "0",
                "keys": {"history.go_to_move": "Ctrl+K"},
                "commands": {"move.clear": "x"},
            }
        )
        self.assertEqual(legacy.get_binding("history.go_to_move"), "Ctrl+K")
        self.assertEqual(legacy.get_alias("move.clear"), "x")


if __name__ == "__main__":
    unittest.main()
