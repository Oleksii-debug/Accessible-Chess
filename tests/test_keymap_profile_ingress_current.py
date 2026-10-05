import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from acs.ui_keymap_service import (
    MAX_KEYMAP_OBJECT_ENTRIES,
    MAX_KEYMAP_PROFILE_BYTES,
    KeymapService,
)
from acs.version2_final_product_profile import build_final_product_action_registry


class _ActiveText(str):
    def __len__(self):  # pragma: no cover - must never execute
        raise AssertionError("active text length hook executed")

    def encode(self, *args, **kwargs):  # pragma: no cover - must never execute
        raise AssertionError("active text encode hook executed")

    def strip(self, *args, **kwargs):  # pragma: no cover - must never execute
        raise AssertionError("active text strip hook executed")


class _ActiveTruth:
    def __bool__(self):  # pragma: no cover - must never execute
        raise AssertionError("active truth hook executed")


class KeymapProfileIngressCurrentTests(unittest.TestCase):
    def _service(self, root: str, *, lang: str = "en") -> KeymapService:
        return KeymapService(Path(root) / "keymap.json", lang=lang)

    def test_snapshot_exposes_backend_owned_import_byte_limit(self):
        with TemporaryDirectory() as root:
            service = self._service(root)
            self.assertEqual(service.snapshot()["maxImportBytes"], MAX_KEYMAP_PROFILE_BYTES)

    def test_direct_import_rejects_active_text_before_any_text_hook(self):
        with TemporaryDirectory() as root:
            service = self._service(root)
            before = service.snapshot()
            result = service.import_profile(_ActiveText("{}"))
            self.assertFalse(result["ok"])
            self.assertEqual(service.snapshot(), before)
            self.assertFalse(service.path.exists())

    def test_direct_import_rejects_active_allow_warnings_before_truth_hook(self):
        with TemporaryDirectory() as root:
            service = self._service(root)
            payload = service.export_profile()
            result = service.import_profile(payload, allow_warnings=_ActiveTruth())
            self.assertFalse(result["ok"])
            self.assertFalse(service.path.exists())

    def test_direct_import_rejects_ascii_and_multibyte_overflow_before_publication(self):
        with TemporaryDirectory() as root:
            service = self._service(root)
            before = service.snapshot()
            for payload in (
                " " * (MAX_KEYMAP_PROFILE_BYTES + 1),
                "é" * (MAX_KEYMAP_PROFILE_BYTES // 2 + 1),
            ):
                result = service.import_profile(payload)
                self.assertFalse(result["ok"])
                self.assertEqual(service.snapshot(), before)
                self.assertFalse(service.path.exists())

    def test_direct_import_rejects_lone_surrogate_before_json_parse(self):
        with TemporaryDirectory() as root:
            service = self._service(root)
            result = service.import_profile('{"schema_version":1,"x":"\ud800"}')
            self.assertFalse(result["ok"])
            self.assertFalse(service.path.exists())

    def test_duplicate_root_and_nested_keys_fail_closed_without_mutation(self):
        duplicate_root = (
            '{"schema_version":1,"schema_version":1,"bindings":{},"aliases":{}}'
        )
        duplicate_binding = (
            '{"schema_version":1,"bindings":{'
            '"history.go_to_move":"Alt+J","history.go_to_move":"Alt+K"},'
            '"aliases":{}}'
        )
        with TemporaryDirectory() as root:
            service = self._service(root)
            before = service.snapshot()
            for payload in (duplicate_root, duplicate_binding):
                result = service.import_profile(payload)
                self.assertFalse(result["ok"])
                self.assertEqual(service.snapshot(), before)
                self.assertFalse(service.path.exists())

    def test_object_cardinality_bound_rejects_unknown_key_flood(self):
        with TemporaryDirectory() as root:
            service = self._service(root)
            payload = json.dumps({
                "schema_version": 1,
                "bindings": {f"unknown.{index}": "A" for index in range(MAX_KEYMAP_OBJECT_ENTRIES + 1)},
                "aliases": {},
            })
            self.assertLess(len(payload.encode("utf-8")), MAX_KEYMAP_PROFILE_BYTES)
            result = service.import_profile(payload)
            self.assertFalse(result["ok"])
            self.assertFalse(service.path.exists())

    def test_disk_restart_rejects_oversize_invalid_utf8_and_duplicate_keys_preserving_bytes(self):
        cases = (
            b" " * (MAX_KEYMAP_PROFILE_BYTES + 1),
            b'{"schema_version":1,"bindings":{},"aliases":{},"x":"\xff"}',
            b'{"schema_version":1,"bindings":{},"bindings":{},"aliases":{}}',
        )
        for payload in cases:
            with self.subTest(prefix=payload[:32]):
                with TemporaryDirectory() as root:
                    path = Path(root) / "keymap.json"
                    path.write_bytes(payload)
                    service = KeymapService(path, lang="en")
                    self.assertEqual(service.recovery_message, "invalid keymap profile")
                    self.assertFalse(service.snapshot()["writeBlocked"])
                    self.assertEqual(path.read_bytes(), payload)
                    self.assertEqual(
                        service.editor.registry.get_binding("history.go_to_move"),
                        "Ctrl+G",
                    )

    def test_wider_registry_adoption_rechecks_disk_through_same_ingress_boundary(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "keymap.json"
            first = KeymapService(path, lang="en")
            profile = json.loads(first.export_profile())
            profile["bindings"]["history.go_to_move"] = "Alt+J"
            path.write_text(json.dumps(profile), encoding="utf-8")

            service = KeymapService(path, lang="en")
            self.assertIsNone(service.recovery_message)
            path.write_text(
                '{"schema_version":1,"bindings":{"history.go_to_move":"Alt+J"},'
                '"bindings":{"history.go_to_move":"Alt+K"},"aliases":{}}',
                encoding="utf-8",
            )
            wider = build_final_product_action_registry()
            service.adopt_registry(wider)
            self.assertEqual(service.recovery_message, "invalid keymap profile")
            self.assertEqual(wider.get_binding("history.go_to_move"), "Alt+J")

    def test_classroom_list_remap_survives_restart_and_context_reset(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "keymap.json"
            service = KeymapService(path, lang="en")
            service.adopt_registry(build_final_product_action_registry())

            saved = service.save("classroom.next_item", "J")
            self.assertTrue(saved["ok"])
            self.assertEqual(
                service.resolve_binding("classroom_list", "J")["actionId"],
                "classroom.next_item",
            )
            self.assertIsNone(service.resolve_binding("classroom_list", "Down"))

            restarted = KeymapService(path, lang="en")
            restarted.adopt_registry(build_final_product_action_registry())
            self.assertEqual(
                restarted.resolve_binding("classroom_list", "J")["actionId"],
                "classroom.next_item",
            )
            self.assertIsNone(restarted.resolve_binding("classroom_list", "Down"))

            reset = restarted.reset_context("classroom_list")
            self.assertTrue(reset["ok"])
            self.assertEqual(
                restarted.resolve_binding("classroom_list", "Down")["actionId"],
                "classroom.next_item",
            )
            self.assertIsNone(restarted.resolve_binding("classroom_list", "J"))

    def test_valid_versioned_and_legacy_profiles_still_import(self):
        with TemporaryDirectory() as root:
            service = self._service(root)
            profile = json.loads(service.export_profile())
            profile["bindings"]["history.go_to_move"] = "Alt+J"
            result = service.import_profile(json.dumps(profile))
            self.assertTrue(result["ok"])
            self.assertEqual(service.editor.registry.get_binding("history.go_to_move"), "Alt+J")

            legacy = json.dumps({
                "keys": {"history.go_to_move": "Alt+K"},
                "commands": {"move.undo": "back"},
            })
            result = service.import_profile(legacy)
            self.assertTrue(result["ok"])
            self.assertEqual(service.editor.registry.get_binding("history.go_to_move"), "Alt+K")
            self.assertEqual(service.editor.registry.get_alias("move.undo"), "back")


if __name__ == "__main__":
    unittest.main()
