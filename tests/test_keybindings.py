import json
from pathlib import Path
import tempfile
import unittest

from acs.keybindings import (
    ActionDefinition,
    ActionRegistry,
    BindingContext,
    DEFAULT_ACTIONS,
    normalize_binding,
)


class ActionRegistryTests(unittest.TestCase):
    def test_locked_defaults_are_present_and_resolvable(self):
        registry = ActionRegistry()
        self.assertEqual(registry.resolve_binding(BindingContext.HISTORY, "shift+a").action_id, "history.previous")
        self.assertEqual(registry.resolve_binding(BindingContext.HISTORY, "shift+d").action_id, "history.next")
        self.assertEqual(registry.resolve_binding(BindingContext.HISTORY, "ctrl+g").action_id, "history.go_to_move")
        self.assertEqual(registry.resolve_binding(BindingContext.ANALYSIS, "alt+5").action_id, "analysis.pv5")
        self.assertEqual(registry.resolve_binding(BindingContext.BOARD, "a").action_id, "board.attackers")
        self.assertEqual(registry.resolve_binding(BindingContext.BOARD, "d").action_id, "board.defenders")
        self.assertEqual(registry.resolve_alias(BindingContext.MOVE_ENTRY, "b").action_id, "move.black_to_move")
        self.assertEqual(registry.resolve_alias(BindingContext.MOVE_ENTRY, "c").action_id, "move.clear")

    def test_board_rank_and_file_navigation_defaults_are_registered(self):
        registry = ActionRegistry()
        for number in range(1, 9):
            rank = registry.resolve_binding(BindingContext.BOARD, str(number))
            file_ = registry.resolve_binding(BindingContext.BOARD, f"Shift+{number}")
            self.assertIsNotNone(rank)
            self.assertIsNotNone(file_)
            self.assertEqual(rank.action_id, f"board.rank_{number}")
            self.assertEqual(file_.action_id, f"board.file_{number}")

        board_help = {item["action_id"]: item for item in registry.help_items(context=BindingContext.BOARD)}
        self.assertEqual(board_help["board.rank_1"]["binding"], "1")
        self.assertEqual(board_help["board.rank_8"]["binding"], "8")
        self.assertEqual(board_help["board.file_1"]["binding"], "Shift+1")
        self.assertEqual(board_help["board.file_8"]["binding"], "Shift+8")
        self.assertIn("rank 1", board_help["board.rank_1"]["description"].lower())
        self.assertIn("file a", board_help["board.file_1"]["description"].lower())
        self.assertEqual(registry.validate(), ())

    def test_board_rank_and_file_bindings_are_remappable_and_resettable(self):
        registry = ActionRegistry()
        registry.set_binding("board.rank_1", "Ctrl+1")
        registry.set_binding("board.file_1", "Ctrl+Shift+1")
        self.assertEqual(registry.resolve_binding(BindingContext.BOARD, "Ctrl+1").action_id, "board.rank_1")
        self.assertEqual(registry.resolve_binding(BindingContext.BOARD, "Ctrl+Shift+1").action_id, "board.file_1")
        registry.reset_action("board.rank_1")
        registry.reset_action("board.file_1")
        self.assertEqual(registry.get_binding("board.rank_1"), "1")
        self.assertEqual(registry.get_binding("board.file_1"), "Shift+1")

    def test_normalization_is_stable(self):
        self.assertEqual(normalize_binding("control-shift-z"), "Ctrl+Shift+Z")
        self.assertEqual(normalize_binding("shift+a"), "Shift+A")
        self.assertEqual(normalize_binding("alt+1"), "Alt+1")
        self.assertEqual(normalize_binding("esc"), "Escape")

    def test_nvda_pseudo_modifier_normalizes_for_conflict_diagnostics(self):
        self.assertEqual(normalize_binding("nvda+f1"), "NVDA+F1")
        self.assertEqual(normalize_binding("NVDA+Space"), "NVDA+Space")
        self.assertEqual(normalize_binding("ctrl+nvda+f2"), "NVDA+Ctrl+F2")

    def test_nvda_binding_warns_instead_of_failing_parser(self):
        registry = ActionRegistry()
        conflicts = registry.binding_conflicts("history.go_to_move", "NVDA+F1")
        self.assertTrue(any(c.kind == "nvda_likely" and c.severity == "warning" for c in conflicts))
        with self.assertRaisesRegex(ValueError, "likely to conflict with NVDA"):
            registry.set_binding("history.go_to_move", "NVDA+F1", allow_warnings=False)
        self.assertEqual(registry.get_binding("history.go_to_move"), "Ctrl+G")

    def test_nvda_binding_can_be_stored_after_warning_is_accepted(self):
        registry = ActionRegistry()
        conflicts = registry.set_binding("history.go_to_move", "NVDA+F1")
        self.assertEqual(registry.get_binding("history.go_to_move"), "NVDA+F1")
        self.assertTrue(any(c.kind == "nvda_likely" for c in conflicts))
        self.assertEqual(
            registry.resolve_binding(BindingContext.HISTORY, "nvda+f1").action_id,
            "history.go_to_move",
        )

    def test_context_specific_duplicates_are_allowed(self):
        definitions = [
            ActionDefinition("board.x", BindingContext.BOARD, "Board x", "X"),
            ActionDefinition("history.x", BindingContext.HISTORY, "History x", "X"),
        ]
        registry = ActionRegistry(definitions)
        self.assertEqual(registry.validate(), ())
        self.assertEqual(registry.resolve_binding(BindingContext.BOARD, "x").action_id, "board.x")
        self.assertEqual(registry.resolve_binding(BindingContext.HISTORY, "x").action_id, "history.x")

    def test_same_context_duplicate_is_rejected(self):
        registry = ActionRegistry()
        with self.assertRaisesRegex(ValueError, "already assigned"):
            registry.set_binding("board.defenders", "A")
        self.assertEqual(registry.get_binding("board.defenders"), "D")

    def test_alias_duplicate_is_rejected(self):
        registry = ActionRegistry()
        with self.assertRaisesRegex(ValueError, "already assigned"):
            registry.set_alias("move.clear", "b")
        self.assertEqual(registry.get_alias("move.clear"), "c")

    def test_reserved_shortcuts_warn_without_silent_overwrite(self):
        registry = ActionRegistry()
        conflicts = registry.set_binding("history.go_to_move", "Alt+F4")
        self.assertTrue(any(c.kind == "windows_reserved" and c.severity == "warning" for c in conflicts))
        self.assertEqual(registry.get_binding("history.go_to_move"), "Alt+F4")

        registry.reset_action("history.go_to_move")
        with self.assertRaisesRegex(ValueError, "Windows"):
            registry.set_binding("history.go_to_move", "Alt+F4", allow_warnings=False)

    def test_remap_persists_and_dynamic_help_uses_active_binding(self):
        registry = ActionRegistry()
        registry.set_binding("history.go_to_move", "Ctrl+J")
        registry.set_alias("move.clear", "z")
        clone = ActionRegistry.import_json(registry.export_json())
        self.assertEqual(clone.get_binding("history.go_to_move"), "Ctrl+J")
        self.assertEqual(clone.get_alias("move.clear"), "z")
        item = next(x for x in clone.help_items() if x["action_id"] == "history.go_to_move")
        self.assertEqual(item["binding"], "Ctrl+J")
        self.assertEqual(item["default_binding"], "Ctrl+G")

    def test_reset_action_context_and_all(self):
        registry = ActionRegistry()
        registry.set_binding("history.go_to_move", "Ctrl+J")
        registry.set_binding("history.previous", "Shift+Left")
        registry.set_alias("move.clear", "z")
        registry.reset_action("history.go_to_move")
        self.assertEqual(registry.get_binding("history.go_to_move"), "Ctrl+G")
        registry.reset_context(BindingContext.HISTORY)
        self.assertEqual(registry.get_binding("history.previous"), "Shift+A")
        self.assertEqual(registry.get_alias("move.clear"), "z")
        registry.reset_all()
        self.assertEqual(registry.get_alias("move.clear"), "c")

    def test_schema_zero_migration(self):
        legacy = {
            "keys": {"history.go_to_move": "Ctrl+J"},
            "commands": {"move.clear": "z"},
        }
        registry = ActionRegistry.from_profile(legacy)
        self.assertEqual(registry.get_binding("history.go_to_move"), "Ctrl+J")
        self.assertEqual(registry.get_alias("move.clear"), "z")

    def test_malformed_config_recovers_to_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "keymap.json"
            path.write_text("{not-json", encoding="utf-8")
            registry, warning = ActionRegistry.load(path)
            self.assertIsNotNone(warning)
            self.assertEqual(registry.get_binding("history.go_to_move"), "Ctrl+G")
            self.assertEqual(registry.get_alias("move.clear"), "c")

    def test_save_is_roundtrip_and_unknown_future_actions_are_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "keymap.json"
            registry = ActionRegistry()
            registry.set_binding("history.go_to_move", "Ctrl+J")
            registry.save(path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["bindings"]["future.action"] = "F12"
            path.write_text(json.dumps(raw), encoding="utf-8")
            loaded, warning = ActionRegistry.load(path)
            self.assertIsNone(warning)
            self.assertEqual(loaded.get_binding("history.go_to_move"), "Ctrl+J")

    def test_external_nvda_actions_are_not_remappable(self):
        definitions = [
            ActionDefinition("nvda.heading", BindingContext.DOCUMENT, "NVDA heading", "H", external=True),
            ActionDefinition("app.command", BindingContext.DOCUMENT, "App command", "Ctrl+J"),
        ]
        registry = ActionRegistry(definitions)
        with self.assertRaisesRegex(ValueError, "external"):
            registry.set_binding("nvda.heading", "J")
        self.assertIsNone(registry.resolve_binding(BindingContext.DOCUMENT, "H"))

    def test_data_syntax_is_not_part_of_command_alias_defaults(self):
        aliases = {item.default_alias for item in DEFAULT_ACTIONS if item.default_alias}
        self.assertNotIn("w:", aliases)
        self.assertNotIn("b:", aliases)


if __name__ == "__main__":
    unittest.main()
