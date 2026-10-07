from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Section22ScopeTests(unittest.TestCase):
    def test_section22_registry_does_not_import_section36_domains(self):
        source = (ROOT / "acs" / "chess_agent_tools.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertNotIn("agent_classroom_tools", imported)
        self.assertNotIn("section36_integration", imported)
        self.assertNotIn("account", imported)
        self.assertIn("agent_speech_context_tools", imported)
        self.assertIn("agent_tactile_tools", imported)

    def test_tactile_gateway_has_no_model_supplied_position_setter(self):
        source = (ROOT / "acs" / "agent_tactile_tools.py").read_text(encoding="utf-8")
        self.assertNotIn("set_fen", source)
        self.assertNotIn("board_set", source)
        self.assertIn('"tactile.status"', source)
        self.assertIn('"tactile.refresh"', source)


if __name__ == "__main__":
    unittest.main()
