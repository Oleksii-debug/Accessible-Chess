import unittest

from acs.keybindings import ActionRegistry, BindingContext
from acs.ui_keymap_editor import KeymapEditorModel


class KeymapEditorModelTests(unittest.TestCase):
    def _row(self, model, action_id):
        return next(row for row in model.rows() if row.action_id == action_id)

    def test_rows_are_searchable_localized_and_expose_defaults(self):
        model = KeymapEditorModel(lang="uk")
        row = self._row(model, "history.go_to_move")
        self.assertEqual(row.label, "Перейти до ходу")
        self.assertEqual(row.context, "history")
        self.assertEqual(row.value, "Ctrl+G")
        self.assertFalse(row.changed)
        self.assertEqual([x.action_id for x in model.rows(query="перейти")], ["history.go_to_move"])
        model.set_language("en")
        self.assertEqual(self._row(model, "history.go_to_move").label, "Go to move")

    def test_board_filter_and_remap_use_central_registry(self):
        registry = ActionRegistry()
        model = KeymapEditorModel(registry)
        rows = model.rows(context=BindingContext.BOARD)
        self.assertTrue(rows)
        self.assertTrue({"board.attackers", "board.defenders", "board.input"}.issubset({r.action_id for r in rows}))
        result = model.save("history.go_to_move", "Ctrl+Shift+G")
        self.assertTrue(result.ok)
        self.assertEqual(registry.get_binding("history.go_to_move"), "Ctrl+Shift+G")

    def test_conflicts_never_silently_overwrite(self):
        registry = ActionRegistry()
        model = KeymapEditorModel(registry)
        duplicate = model.save("history.next", "Shift+A")
        self.assertFalse(duplicate.ok)
        self.assertEqual(registry.get_binding("history.next"), "Shift+D")
        reserved = model.save("history.go_to_move", "Ctrl+L")
        self.assertFalse(reserved.ok)
        accepted = model.save("history.go_to_move", "Ctrl+L", allow_warnings=True)
        self.assertTrue(accepted.ok)

    def test_alias_remap_reset_and_profile_roundtrip(self):
        source = KeymapEditorModel()
        self.assertTrue(source.save("move.black_to_move", "z").ok)
        duplicate = source.save("move.clear", "z")
        self.assertFalse(duplicate.ok)
        payload = source.export_profile()
        target = KeymapEditorModel()
        self.assertTrue(target.import_profile(payload).ok)
        self.assertEqual(target.registry.get_alias("move.black_to_move"), "z")
        target.reset_context(BindingContext.MOVE_ENTRY)
        self.assertEqual(target.registry.get_alias("move.black_to_move"), "b")

    def test_nvda_browse_commands_are_not_app_owned_rows(self):
        ids = {row.action_id for row in KeymapEditorModel().rows()}
        self.assertNotIn("nvda.heading", ids)
        self.assertNotIn("nvda.button", ids)
        self.assertNotIn("nvda.edit", ids)
        self.assertNotIn("nvda.form", ids)


if __name__ == "__main__":
    unittest.main()
