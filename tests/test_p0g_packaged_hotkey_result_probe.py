from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "p0g_packaged_hotkey_result_probe.ps1"
WEB = ROOT / "web" / "index.html"
KEYMAP = ROOT / "web" / "keybindings.json"


class PackagedP0GHotkeyResultProbeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = PROBE.read_text(encoding="utf-8")
        cls.web = WEB.read_text(encoding="utf-8")
        cls.keymap = json.loads(KEYMAP.read_text(encoding="utf-8"))

    def test_probe_launches_real_extracted_exe_and_uses_connected_provider_roots(self) -> None:
        self.assertIn("AccessibleChess.exe", self.text)
        self.assertIn("Start-Process -FilePath $exe", self.text)
        self.assertIn("ProviderRoots($Report)", self.text)
        self.assertIn("AutomationElement]::FromHandle", self.text)
        self.assertIn("ControlViewWalker", self.text)
        self.assertIn("provider_subtree_seen", self.text)
        self.assertNotIn("RootElement]::FindAll", self.text)
        self.assertNotIn("$desktop.FindAll", self.text)

    def test_probe_keeps_focus_outside_board_application_and_sends_native_alt_1_and_alt_2(self) -> None:
        self.assertIn("board-launcher", self.text)
        self.assertIn("AssertLauncherFocus $launcher", self.text)
        self.assertIn("AutomationElement]::FocusedElement", self.text)
        self.assertIn("hotkey_focus_path='board-launcher SetFocus outside role=application", self.text)
        self.assertIn("board_application_entered=$false", self.text)
        self.assertNotIn("Invoke $launcher", self.text)
        self.assertIn("AccessibleChessP0GKeys]::Alt", self.text)
        self.assertIn("@{index=1; key=0x31}", self.text)
        self.assertIn("@{index=2; key=0x32}", self.text)
        self.assertNotIn("dispatch_action", self.text)
        self.assertNotIn("keymap_resolve_binding", self.text)

    def test_probe_enables_stockfish_idempotently(self) -> None:
        self.assertIn("function EnsureEngineEnabled($EngineToggle)", self.text)
        self.assertIn("^(Увімкнути Stockfish|Enable Stockfish)$", self.text)
        self.assertIn("^(Вимкнути Stockfish|Disable Stockfish)$", self.text)
        self.assertIn("return 'enabled-by-probe'", self.text)
        self.assertIn("return 'already-enabled'", self.text)
        self.assertIn("$engineState=EnsureEngineEnabled $engineToggle", self.text)
        self.assertIn("engine_enable_state=$engineState", self.text)
        self.assertNotIn("Invoke $engineToggle 'engine-toggle'\n\n", self.text)

    def test_shipping_routes_alt_variations_only_through_analysis_context_outside_board(self) -> None:
        actions = {item["id"]: item for item in self.keymap["actions"]}
        self.assertEqual(actions["analysis.pv1"]["binding"], "Alt+1")
        self.assertEqual(actions["analysis.pv1"]["registryContext"], "analysis")
        self.assertEqual(actions["analysis.pv2"]["binding"], "Alt+2")
        self.assertEqual(actions["analysis.pv2"]["registryContext"], "analysis")
        self.assertIn("if(e.target.closest('#board-application'))return", self.web)
        self.assertIn("resolveBinding(eventChord(e),'board','board')", self.web)
        self.assertIn("resolveBinding(chord,'analysis','analysis')", self.web)

    def test_probe_requires_accessible_result_semantics_not_handler_execution_only(self) -> None:
        self.assertIn("Accessible status live region #live", self.text)
        self.assertIn("Alt+$index did not expose a matching live-region result", self.text)
        self.assertIn("result does not identify the selected variation", self.text)
        self.assertIn("result omits analysis depth", self.text)
        self.assertIn("result omits evaluation", self.text)
        self.assertIn("raw provider/debug text", self.text)
        self.assertIn("alt_1_action_occurred=$true", self.text)
        self.assertIn("alt_1_accessible_result_exposed=$true", self.text)
        self.assertIn("alt_2_action_occurred=$true", self.text)
        self.assertIn("alt_2_accessible_result_exposed=$true", self.text)

    def test_probe_is_bounded_and_does_not_claim_human_nvda_acceptance(self) -> None:
        self.assertIn("TimeoutSeconds = 60", self.text)
        self.assertIn("Provider-root traversal cap reached", self.text)
        self.assertIn("human_tested=$false", self.text)
        self.assertIn("nvda_verified=$false", self.text)
        self.assertIn("packaged-p0g-hotkey-result-summary.json", self.text)
        self.assertIn("Local path leaked into P0-G evidence", self.text)


if __name__ == "__main__":
    unittest.main()
