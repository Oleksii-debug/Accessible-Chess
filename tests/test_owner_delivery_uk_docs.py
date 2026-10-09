from __future__ import annotations

import json
import subprocess
from pathlib import Path
import unittest


class OwnerDeliveryUkrainianDocsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.hotkeys_path = self.root / "web" / "docs" / "ACCESSIBLE_CHESS_HOTKEYS_UK.txt"
        self.capabilities_path = (
            self.root / "web" / "docs" / "ACCESSIBLE_CHESS_CAPABILITIES_TESTING_UK.txt"
        )
        self.hotkeys = self.hotkeys_path.read_text(encoding="utf-8")
        self.capabilities = self.capabilities_path.read_text(encoding="utf-8")

    def test_documents_are_plain_utf8_copyable_text(self) -> None:
        for path, text in (
            (self.hotkeys_path, self.hotkeys),
            (self.capabilities_path, self.capabilities),
        ):
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                self.assertEqual(raw.decode("utf-8"), text)
                self.assertNotIn("\x00", text)
                self.assertTrue(text.endswith("\n"))
                self.assertGreater(len(text.strip()), 1000)
                self.assertTrue(
                    all(ch in "\n\r\t" or ord(ch) >= 32 for ch in text),
                    "owner-facing docs must not contain hidden control characters",
                )

    def test_hotkey_guide_matches_every_current_keymap_action_exactly(self) -> None:
        keymap = json.loads(
            (self.root / "web" / "keybindings.json").read_text(encoding="utf-8")
        )
        self.assertEqual(keymap.get("schemaVersion"), 1)
        actions = keymap.get("actions")
        self.assertIsInstance(actions, list)
        documented = {
            line.split(" | ", 1)[0].removeprefix("ACTION: "): line
            for line in self.hotkeys.splitlines()
            if line.startswith("ACTION: ")
        }
        self.assertEqual(len(documented), len(actions))
        self.assertEqual(set(documented), {action["id"] for action in actions})

        for action in actions:
            with self.subTest(action=action["id"]):
                binding = action["binding"] if action["binding"] is not None else "NONE"
                alias = action["alias"] if action["alias"] is not None else "NONE"
                expected = (
                    f"ACTION: {action['id']} | {action['labelUk']} | "
                    f"context={action['context']} | binding={binding} | alias={alias}"
                )
                self.assertEqual(documented[action["id"]], expected)

    def test_context_and_native_copy_claims_are_bound_to_current_product(self) -> None:
        html = (self.root / "web" / "index.html").read_text(encoding="utf-8")
        pgn = (self.root / "web" / "full_product_pgn.js").read_text(encoding="utf-8")
        library = (self.root / "web" / "full_product_library.js").read_text(encoding="utf-8")

        self.assertIn("function editableShortcutTarget(node)", html)
        self.assertIn("if(!e.altKey)return", html)
        self.assertIn("projectedOwnedAction(e,['global'])", html)
        self.assertIn("projectedOwnedAction(e,['analysis'])", html)
        self.assertIn("let a=await resolveBinding(chord,'analysis','analysis')", html)
        self.assertIn("if(e.ctrlKey&&!e.altKey&&!e.shiftKey&&String(e.key).toLowerCase()==='c')return", html)
        self.assertIn("if(e.ctrlKey&&!e.altKey&&selection&&selection.toString())return", html)
        self.assertIn("['INPUT','TEXTAREA','SELECT'].includes(node.tagName)", html)

        self.assertIn('"pgn_tree"', pgn)
        self.assertIn('"pgn.previous_item"', pgn)
        self.assertIn('"pgn.next_item"', pgn)
        self.assertIn('"pgn.parent_variation"', pgn)
        self.assertIn('"library_results"', library)
        self.assertIn('"library.open_game"', library)

        for phrase in (
            "Ctrl+A, Ctrl+C, Ctrl+X і Ctrl+V",
            "Alt+1…Alt+5",
            "ArrowUp/ArrowDown",
            "нативним Ctrl+C",
            "PGN / GAME TREE",
            "БІБЛІОТЕКА / ACSDB",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.hotkeys)

    def test_documented_native_editing_and_live_remaps_execute_shipping_handlers(self) -> None:
        for name in ("v2_remapped_keyboard_native_editing_test.js",
                     "remappable_board_grid_controls_current_test.js",
                     "remappable_input_submit_keys_current_test.js"):
            with self.subTest(script=name):
                result = subprocess.run(["node", "tests/js/" + name], cwd=self.root,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_docs_follow_existing_canonical_package_path(self) -> None:
        workflow = (
            self.root / ".github" / "workflows" / "w4-v2-p0-fresh-windows-candidate.yml"
        ).read_text(encoding="utf-8")
        payload = (self.root / "acs" / "version2_release_payload.py").read_text(
            encoding="utf-8"
        )
        assembler = (self.root / "acs" / "version2_package_assembler.py").read_text(
            encoding="utf-8"
        )
        preflight = (self.root / "acs" / "version2_package_preflight.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("--include-data-dir=web=web", workflow)
        self.assertIn("_copy_tree_without_links(standalone, product)", payload)
        self.assertIn('_copy_tree(product, staged / "AccessibleChess"', assembler)
        for name in (
            "ACCESSIBLE_CHESS_HOTKEYS_UK.txt",
            "ACCESSIBLE_CHESS_CAPABILITIES_TESTING_UK.txt",
        ):
            self.assertIn(name, payload)
            self.assertIn(name, preflight)
        self.assertTrue(self.hotkeys_path.is_file())
        self.assertTrue(self.capabilities_path.is_file())

    def test_capabilities_guide_preserves_release_and_format_boundaries(self) -> None:
        required = (
            "HUMAN_TESTED=NO",
            "NVDA_VERIFIED=NO",
            "FINAL_WINDOWS_ZIP=NO",
            "НЕ ВВАЖАТИ CBH/CBV ПІДТРИМКОЮ ЗА ЗАМОВЧУВАННЯМ",
            "UTF-8 PGN",
            "Windows-1251",
            "UTF-16 LE/BE",
            "ACSDB",
            "GameTree",
            "EPUB",
            "330-WAV",
            "100-studies-ordered",
            "Anthology of Chess Combinations 3",
            "візуальний redesign",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.capabilities)

        self.assertNotIn("NVDA_VERIFIED=YES", self.hotkeys + self.capabilities)
        self.assertNotIn("HUMAN_TESTED=YES", self.hotkeys + self.capabilities)
        self.assertNotIn("FINAL_WINDOWS_ZIP=YES", self.hotkeys + self.capabilities)


if __name__ == "__main__":
    unittest.main()
