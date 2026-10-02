from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "web" / "stage1_board_actions.js"


class Stage1BoardBridgeResourceSafetyTests(unittest.TestCase):
    def run_node(self, body: str) -> subprocess.CompletedProcess[str]:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is unavailable")
        harness = f"""
const fs = require('fs');
const source = fs.readFileSync({str(BRIDGE)!r}, 'utf8');
function resetDocument() {{
  const help = {{appendChild: () => {{}}}};
  global.document = {{
    documentElement: {{lang:'uk'}}, body:{{dataset:{{}}}},
    getElementById: id => id === 'help' ? help : null,
    createElement: () => ({{id:'',textContent:'',append:()=>{{}},remove:()=>{{}}}}),
  }};
  global.state = {{board: []}}; global.boardIndex = 0; global.keymap = [];
  global.apiAction = async () => ({{ok:true}}); global.jumpBoardFocus = () => {{}};
}}
resetDocument();
{body}
"""
        return subprocess.run(
            [node, "-e", harness],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )

    def test_missing_bootstrap_does_not_set_false_readiness_and_can_recover(self) -> None:
        run = self.run_node("""
global.window = {renderHelp: () => {}};
eval(source);
if (window.__accessibleChessStage1BoardActions) throw new Error('false readiness guard set');
if (document.body.dataset.stage1BoardActionBridgeReady) throw new Error('false body readiness set');
window.executeAction = async id => `base:${id}`;
const base = window.executeAction;
eval(source);
if (!window.__accessibleChessStage1BoardActions) throw new Error('recovery injection did not install');
if (window.executeAction === base) throw new Error('board wrapper was not installed');
if (document.body.dataset.stage1BoardActionBridgeReady !== 'true') throw new Error('body readiness missing');
console.log('RECOVERABLE PREREQUISITE PASS');
""")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("RECOVERABLE PREREQUISITE PASS", run.stdout)

    def test_successful_reinjection_is_idempotent(self) -> None:
        run = self.run_node("""
global.window = {executeAction: async id => `base:${id}`, renderHelp: () => {}};
eval(source);
const installed = window.executeAction;
eval(source);
if (window.executeAction !== installed) throw new Error('repeat injection stacked wrapper');
console.log('IDEMPOTENT REINJECTION PASS');
""")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("IDEMPOTENT REINJECTION PASS", run.stdout)


if __name__ == "__main__":
    unittest.main()
