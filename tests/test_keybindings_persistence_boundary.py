from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.keybindings import ActionRegistry, MAX_KEYMAP_JSON_BYTES


class KeybindingPersistenceBoundaryTests(unittest.TestCase):
    def test_disk_load_is_bounded_before_text_decode_or_json_parse(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "keymap.json"
            oversized = b" " * (MAX_KEYMAP_JSON_BYTES + 1)
            path.write_bytes(oversized)

            registry, warning = ActionRegistry.load(path)

            self.assertIsNotNone(warning)
            self.assertIn("too large", warning)
            self.assertEqual(registry.get_binding("history.go_to_move"), "Ctrl+G")
            self.assertEqual(path.read_bytes(), oversized)

    def test_invalid_utf8_disk_profile_recovers_without_rewriting_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "keymap.json"
            raw = b'{"schema_version":1,"bindings":{},"aliases":{}}\xff'
            path.write_bytes(raw)

            registry, warning = ActionRegistry.load(path)

            self.assertIsNotNone(warning)
            self.assertIn("valid UTF-8", warning)
            self.assertEqual(registry.get_alias("move.clear"), "c")
            self.assertEqual(path.read_bytes(), raw)

    def test_missing_disk_profile_still_loads_defaults_without_warning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "missing.json"
            registry, warning = ActionRegistry.load(path)
            self.assertIsNone(warning)
            self.assertEqual(registry.get_binding("history.go_to_move"), "Ctrl+G")

    def test_save_does_not_reuse_predictable_legacy_temp_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "keymap.json"
            legacy_tmp = path.with_suffix(path.suffix + ".tmp")
            sentinel = b"do-not-touch"
            legacy_tmp.write_bytes(sentinel)

            registry = ActionRegistry()
            registry.set_binding("history.go_to_move", "Ctrl+J")
            registry.save(path)

            self.assertEqual(legacy_tmp.read_bytes(), sentinel)
            loaded, warning = ActionRegistry.load(path)
            self.assertIsNone(warning)
            self.assertEqual(loaded.get_binding("history.go_to_move"), "Ctrl+J")
            self.assertEqual(
                [p.name for p in path.parent.iterdir() if p.name.startswith(".keymap.json.")],
                [],
            )

    def test_replace_failure_leaves_existing_profile_unchanged_and_cleans_private_temp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "keymap.json"
            original = ActionRegistry()
            original.save(path)
            original_bytes = path.read_bytes()

            changed = ActionRegistry()
            changed.set_binding("history.go_to_move", "Ctrl+J")

            real_replace = os.replace

            def fail_replace(src, dst):
                self.assertEqual(Path(dst), path)
                self.assertNotEqual(Path(src), path.with_suffix(path.suffix + ".tmp"))
                raise OSError("injected replace failure")

            with mock.patch("acs.keybindings.os.replace", side_effect=fail_replace):
                with self.assertRaisesRegex(OSError, "injected replace failure"):
                    changed.save(path)

            self.assertEqual(path.read_bytes(), original_bytes)
            self.assertEqual(
                [p.name for p in path.parent.iterdir() if p.name.startswith(".keymap.json.")],
                [],
            )
            # Sanity: restore path uses the real primitive outside the patch.
            self.assertIs(os.replace, real_replace)


if __name__ == "__main__":
    unittest.main()
