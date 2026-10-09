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
from acs.full_product_actions import build_full_product_action_registry
from acs.version2_profile import build_version2_action_registry


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

    def test_blocking_import_conflicts_keep_shared_authority_and_disk_bytes(self):
        for language in ("en", "uk"):
            with self.subTest(language=language), TemporaryDirectory() as root:
                path = Path(root) / "keymap.json"
                service = KeymapService(path, lang=language)
                service.adopt_registry(build_final_product_action_registry())
                self.assertTrue(service.save("toolbar.next_control", "Ctrl+J")["ok"])
                authority = service.editor.registry
                before = service.snapshot()
                original = path.read_bytes()
                for field, action_id, value, kind in (
                    ("bindings", "toolbar.next_control", "Left", "duplicate"),
                    ("aliases", "move.undo", "y", "alias_duplicate"),
                ):
                    profile = json.loads(service.export_profile())
                    profile[field][action_id] = value
                    for confirmed in (False, True):
                        result = service.import_profile(json.dumps(profile), allow_warnings=confirmed)
                        self.assertFalse(result["ok"])
                        self.assertFalse(result["requiresConfirmation"])
                        self.assertNotIn("snapshot", result)
                        self.assertTrue(any(item["severity"] == "error" and item["kind"] == kind
                                            for item in result["conflicts"]), result)
                        self.assertNotIn("invalid keymap profile:", result["message"])
                        self.assertIs(service.editor.registry, authority)
                        self.assertEqual(service.snapshot(), before)
                        self.assertEqual(path.read_bytes(), original)

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
                    self.assertTrue(service.snapshot()["writeBlocked"])
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

    def test_final_education_remaps_survive_restart_and_context_reset(self):
        for language in ("en", "uk"):
            with self.subTest(language=language), TemporaryDirectory() as root:
                path = Path(root) / "keymap.json"
                service = KeymapService(path, lang=language)
                service.adopt_registry(build_final_product_action_registry())
                for action, old, new in (
                    ("education.previous_item", "Up", "Ctrl+K"),
                    ("education.next_item", "Down", "Alt+J"),
                    ("education.open_selected", "Enter", "Shift+O"),
                ):
                    self.assertTrue(service.save(action, new, allow_warnings=True)["ok"])
                    self.assertIsNone(service.resolve_binding("education_list", old))
                restarted = KeymapService(path, lang=language)
                restarted.adopt_registry(build_final_product_action_registry())
                for action, old, new in (
                    ("education.previous_item", "Up", "Ctrl+K"),
                    ("education.next_item", "Down", "Alt+J"),
                    ("education.open_selected", "Enter", "Shift+O"),
                ):
                    self.assertEqual(restarted.resolve_binding("education_list", new)["actionId"], action)
                    self.assertIsNone(restarted.resolve_binding("education_list", old))
                self.assertTrue(restarted.reset_context("education_list")["ok"])
                for action, old, new in (
                    ("education.previous_item", "Up", "Ctrl+K"),
                    ("education.next_item", "Down", "Alt+J"),
                    ("education.open_selected", "Enter", "Shift+O"),
                ):
                    self.assertEqual(restarted.resolve_binding("education_list", old)["actionId"], action)
                    self.assertIsNone(restarted.resolve_binding("education_list", new))

    def test_preview_classroom_list_remap_survives_restart_and_context_reset(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "keymap.json"
            service = KeymapService(path, lang="en")
            service.adopt_registry(build_full_product_action_registry())

            saved = service.save("classroom.next_item", "J")
            self.assertTrue(saved["ok"])
            self.assertEqual(
                service.resolve_binding("classroom_list", "J")["actionId"],
                "classroom.next_item",
            )
            self.assertIsNone(service.resolve_binding("classroom_list", "Down"))

            restarted = KeymapService(path, lang="en")
            restarted.adopt_registry(build_full_product_action_registry())
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

    def test_toolbar_remap_survives_restart_and_context_reset(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "keymap.json"
            service = KeymapService(path, lang="en")
            service.adopt_registry(build_final_product_action_registry())

            saved = service.save("toolbar.next_control", "J")
            self.assertTrue(saved["ok"])
            self.assertEqual(
                service.resolve_binding("toolbar", "J")["actionId"],
                "toolbar.next_control",
            )
            self.assertIsNone(service.resolve_binding("toolbar", "Right"))

            restarted = KeymapService(path, lang="en")
            restarted.adopt_registry(build_final_product_action_registry())
            self.assertEqual(
                restarted.resolve_binding("toolbar", "J")["actionId"],
                "toolbar.next_control",
            )
            self.assertIsNone(restarted.resolve_binding("toolbar", "Right"))

            reset = restarted.reset_context("toolbar")
            self.assertTrue(reset["ok"])
            self.assertEqual(
                restarted.resolve_binding("toolbar", "Right")["actionId"],
                "toolbar.next_control",
            )
            self.assertIsNone(restarted.resolve_binding("toolbar", "J"))

    def test_all_toolbar_modifier_remaps_persist_in_base_and_final_profiles(self):
        remaps = {
            "toolbar.previous_control": "Alt+K",
            "toolbar.next_control": "Ctrl+J",
            "toolbar.first_control": "Shift+F8",
            "toolbar.last_control": "Ctrl+Shift+F9",
        }
        for build_registry in (build_version2_action_registry, build_final_product_action_registry):
            with self.subTest(profile=build_registry.__name__), TemporaryDirectory() as root:
                path = Path(root) / "keymap.json"
                service = KeymapService(path, lang="en")
                service.adopt_registry(build_registry())
                for action_id, binding in remaps.items():
                    result = service.save(action_id, binding)
                    self.assertTrue(result["ok"], result)
                restarted = KeymapService(path, lang="en")
                restarted.adopt_registry(build_registry())
                for action_id, binding in remaps.items():
                    self.assertEqual(restarted.resolve_binding("toolbar", binding)["actionId"], action_id)
                for old in ("Left", "Right", "Home", "End"):
                    self.assertIsNone(restarted.resolve_binding("toolbar", old))
                self.assertTrue(restarted.reset_context("toolbar")["ok"])
                reset = KeymapService(path, lang="en")
                reset.adopt_registry(build_registry())
                for binding in remaps.values():
                    self.assertIsNone(reset.resolve_binding("toolbar", binding))
                for action_id in remaps:
                    default = build_registry().get_binding(action_id)
                    self.assertEqual(reset.resolve_binding("toolbar", default)["actionId"], action_id)

    def test_profile_dialog_remap_survives_restart_and_context_reset(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "keymap.json"
            service = KeymapService(path, lang="en")
            service.adopt_registry(build_final_product_action_registry())

            saved = service.save("profile.save_name", "J")
            self.assertTrue(saved["ok"])
            self.assertEqual(
                service.resolve_binding("profile_dialog", "J")["actionId"],
                "profile.save_name",
            )
            self.assertIsNone(service.resolve_binding("profile_dialog", "Enter"))

            restarted = KeymapService(path, lang="en")
            restarted.adopt_registry(build_final_product_action_registry())
            self.assertEqual(
                restarted.resolve_binding("profile_dialog", "J")["actionId"],
                "profile.save_name",
            )
            self.assertIsNone(restarted.resolve_binding("profile_dialog", "Enter"))

            reset = restarted.reset_context("profile_dialog")
            self.assertTrue(reset["ok"])
            self.assertEqual(
                restarted.resolve_binding("profile_dialog", "Enter")["actionId"],
                "profile.save_name",
            )
            self.assertIsNone(restarted.resolve_binding("profile_dialog", "J"))

    def test_valid_versioned_and_legacy_profiles_still_import(self):
        with TemporaryDirectory() as root:
            service = self._service(root)
            profile = json.loads(service.export_profile())
            profile["bindings"]["history.go_to_move"] = "Alt+J"
            result = service.import_profile(json.dumps(profile))
            self.assertFalse(result["ok"])
            self.assertTrue(result["requiresConfirmation"])
            self.assertEqual(service.editor.registry.get_binding("history.go_to_move"), "Ctrl+G")
            self.assertFalse(service.path.exists())
            result = service.import_profile(json.dumps(profile), allow_warnings=True)
            self.assertTrue(result["ok"])
            self.assertEqual(service.editor.registry.get_binding("history.go_to_move"), "Alt+J")

            legacy = json.dumps({
                "keys": {"history.go_to_move": "Alt+K"},
                "commands": {"move.undo": "back"},
            })
            result = service.import_profile(legacy)
            self.assertFalse(result["ok"])
            self.assertTrue(result["requiresConfirmation"])
            self.assertEqual(service.editor.registry.get_binding("history.go_to_move"), "Alt+J")
            result = service.import_profile(legacy, allow_warnings=True)
            self.assertTrue(result["ok"])
            self.assertEqual(service.editor.registry.get_binding("history.go_to_move"), "Alt+K")
            self.assertEqual(service.editor.registry.get_alias("move.undo"), "back")


if __name__ == "__main__":
    unittest.main()
