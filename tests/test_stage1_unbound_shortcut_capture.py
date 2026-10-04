from __future__ import annotations

import unittest
from pathlib import Path

from acs.keybindings import ActionRegistry
from acs.ui_keymap_adapter import build_web_keymap
from acs.ui_keymap_editor import KeymapEditorModel


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


class Stage1UnboundShortcutCaptureTests(unittest.TestCase):
    def test_board_material_remains_an_unbound_shortcut_not_an_alias(self) -> None:
        registry = ActionRegistry()
        actions = {
            item["id"]: item
            for item in build_web_keymap(registry)["actions"]
        }
        material = actions["board.material"]
        self.assertIsNone(material["binding"])
        self.assertIsNone(material["defaultBinding"])
        self.assertIsNone(material["alias"])
        self.assertIsNone(material["defaultAlias"])

        editor_rows = {
            row.action_id: row
            for row in KeymapEditorModel(registry, lang="en").rows()
        }
        self.assertEqual(editor_rows["board.material"].value_kind, "shortcut")
        self.assertEqual(editor_rows["board.material"].value, "")

        alias = actions["move.undo"]
        self.assertIsNone(alias["binding"])
        self.assertIsNone(alias["defaultBinding"])
        self.assertEqual(alias["alias"], "u")
        self.assertEqual(alias["defaultAlias"], "u")
        self.assertEqual(editor_rows["move.undo"].value_kind, "alias")

    def test_web_editor_matches_backend_shortcut_classification_when_unbound(self) -> None:
        self.assertIn(
            "const shortcut=item.binding!=null||item.defaultBinding!=null||item.defaultAlias==null;",
            HTML,
        )
        self.assertIn(
            "inp.value=shortcut?(item.binding||''):(item.alias||'')",
            HTML,
        )
        self.assertIn("if(shortcut)inp.readOnly=true", HTML)
        self.assertIn("if(shortcut){const b=document.createElement('button')", HTML)
        self.assertNotIn("if(item.binding){const b=document.createElement('button')", HTML)

    def test_keymap_editor_controls_have_action_specific_accessible_names(self) -> None:
        self.assertIn(
            "const token=String(item.id).replace(/[^A-Za-z0-9_-]/g,'-')",
            HTML,
        )
        self.assertIn("h.id='binding-label-'+token", HTML)
        self.assertIn("inp.setAttribute('aria-labelledby',h.id)", HTML)
        self.assertIn("status.id='binding-status-'+token", HTML)
        self.assertIn(
            "b.setAttribute('aria-label',(en?'New shortcut for ':'Нова комбінація для ')+h.textContent)",
            HTML,
        )
        self.assertIn(
            "save.setAttribute('aria-label',(en?'Save ':'Зберегти ')+h.textContent)",
            HTML,
        )
        self.assertIn(
            "reset.setAttribute('aria-label',(en?'Restore default for ':'Відновити за замовчуванням для ')+h.textContent)",
            HTML,
        )

    def test_context_default_metadata_covers_current_terminal_contexts(self) -> None:
        self.assertIn("function keymapContextLabel(ctx)", HTML)
        for token in (
            "pgn_tree:'PGN tree'",
            "library_results:'Library results'",
            "education_list:'Education list'",
            "pgn_tree:'Дерево PGN'",
            "library_results:'Результати бібліотеки'",
            "education_list:'Навчальний список'",
        ):
            self.assertIn(token, HTML)
        self.assertIn(
            "all.textContent=document.documentElement.lang==='en'?'All':'Усі'",
            HTML,
        )
        self.assertIn("o.textContent=keymapContextLabel(ctx)", HTML)
        self.assertIn("meta.id='binding-meta-'+token", HTML)
        self.assertIn("meta.className='binding-meta'", HTML)
        self.assertIn(
            "meta.textContent=(en?'Context: ':'Контекст: ')+keymapContextLabel(item.registryContext||item.context)+(en?'; Default: ':'; За замовчуванням: ')+defaultValue",
            HTML,
        )
        self.assertIn(
            "inp.setAttribute('aria-describedby',meta.id+' '+status.id)",
            HTML,
        )
        self.assertIn(
            "const next=lang==='en'?'en':'uk',changed=document.documentElement.lang!==next",
            HTML,
        )
        self.assertIn("if(changed&&keymap.length)renderKeymap();renderHelp()", HTML)
        self.assertNotIn("if(keymap.length)renderKeymap();renderHelp()", HTML)

    def test_shortcut_capture_remains_keyboard_first_and_backend_validated(self) -> None:
        self.assertIn("b.textContent='Нова комбінація'", HTML)
        self.assertIn("b.setAttribute('aria-pressed','false')", HTML)
        self.assertIn(
            "b.addEventListener('click',()=>beginCapture(item,inp,status,b))",
            HTML,
        )
        self.assertIn("typeof a.keymap_capture_shortcut==='function'", HTML)
        self.assertIn("typeof a.keymap_preview==='function'", HTML)


if __name__ == "__main__":
    unittest.main()
