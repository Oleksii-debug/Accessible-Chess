from __future__ import annotations

import unittest
from pathlib import Path

from acs.keybindings import ActionRegistry
from acs.ui_keymap_adapter import build_web_keymap


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


class Stage1UnboundShortcutCaptureTests(unittest.TestCase):
    def test_board_material_is_an_unbound_shortcut_not_an_alias(self) -> None:
        actions = {item["id"]: item for item in build_web_keymap(ActionRegistry())["actions"]}
        material = actions["board.material"]
        self.assertIsNone(material["binding"])
        self.assertIsNone(material["defaultBinding"])
        self.assertIsNone(material["alias"])
        self.assertIsNone(material["defaultAlias"])

        alias = actions["move.undo"]
        self.assertIsNone(alias["binding"])
        self.assertIsNone(alias["defaultBinding"])
        self.assertEqual(alias["alias"], "u")
        self.assertEqual(alias["defaultAlias"], "u")

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

    def test_shortcut_capture_remains_keyboard_first_and_backend_validated(self) -> None:
        self.assertIn("b.textContent='Нова комбінація'", HTML)
        self.assertIn("b.setAttribute('aria-pressed','false')", HTML)
        self.assertIn("b.addEventListener('click',()=>beginCapture(item,inp,status,b))", HTML)
        self.assertIn("typeof a.keymap_capture_shortcut==='function'", HTML)
        self.assertIn("typeof a.keymap_preview==='function'", HTML)


if __name__ == "__main__":
    unittest.main()
