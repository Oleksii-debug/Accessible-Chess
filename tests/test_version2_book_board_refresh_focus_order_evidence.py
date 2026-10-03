from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "js" / "version2_release_bootstrap_dom_test.js"


class Version2BookBoardRefreshFocusOrderEvidenceTests(unittest.TestCase):
    """Fail-closed oracle for the asynchronous Book->Stage1 Board repaint order."""

    def test_book_board_does_not_restore_focus_before_stage1_refresh_finishes(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for the Version 2 DOM evidence oracle")

        source = HARNESS.read_text(encoding="utf-8")
        self.assertIn(
            "let holdNextStage1Refresh = false;\n",
            source,
            "W4 Stage1 refresh hold seam changed; re-audit ordering oracle",
        )
        self.assertIn(
            "let heldStage1RefreshResolve = null;\n",
            source,
            "W4 Stage1 refresh release seam changed; re-audit ordering oracle",
        )

        original_block = '''  currentRoute = "board";\n  eventQueue = [\n    { kind: "book-board", payload: { focus_target: "board-launcher" } },\n    { kind: "delegated", payload: { action_id: "book.open_position" } }\n  ];\n  intervalCallback();\n  await flush();\n  await flush();\n  check(originalMain.hidden === false, "queued Board transition did not restore the Stage 1 main");\n  check(workspace.hidden === true, "queued Board transition left the V2 product main exposed");\n  check(documentRef.activeElement === boardLauncher, "trailing delegated event erased the Book-to-Board focus target");\n'''
        ordered_block = '''  currentRoute = "board";\n  const beforeBookBoardRefreshes = stage1RefreshCalls;\n  holdNextStage1Refresh = true;\n  heldStage1RefreshResolve = null;\n  moveInput.focus();\n  check(documentRef.activeElement === moveInput, "ordering probe did not establish non-target focus");\n  eventQueue = [\n    { kind: "book-board", payload: { focus_target: "board-launcher" } },\n    { kind: "delegated", payload: { action_id: "book.open_position" } }\n  ];\n  intervalCallback();\n  await flush();\n  await flush();\n  check(stage1RefreshCalls === beforeBookBoardRefreshes + 1, "Book-to-Board did not start the canonical Stage 1 refresh");\n  check(typeof heldStage1RefreshResolve === "function", "Book-to-Board did not awaitable-start the Stage 1 refresh");\n  check(documentRef.activeElement === moveInput, "Book-to-Board moved keyboard focus before Stage 1 repaint completed");\n  heldStage1RefreshResolve();\n  holdNextStage1Refresh = false;\n  await flush();\n  await flush();\n  await flush();\n  check(originalMain.hidden === false, "queued Board transition did not restore the Stage 1 main");\n  check(workspace.hidden === true, "queued Board transition left the V2 product main exposed");\n  check(documentRef.activeElement === boardLauncher, "Book-to-Board did not restore Board focus after Stage 1 repaint completed");\n'''
        self.assertIn(original_block, source, "W4 Book->Board scenario changed; re-audit ordering oracle")
        source = source.replace(original_block, ordered_block, 1)

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".js",
                prefix="book_board_refresh_order_",
                dir=HARNESS.parent,
                delete=False,
            ) as handle:
                handle.write(source)
                temp_path = Path(handle.name)
            completed = subprocess.run(
                [node, str(temp_path)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

        self.assertEqual(
            completed.returncode,
            0,
            "Book->Board must finish the canonical Stage1 repaint before restoring final NVDA/keyboard focus.\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
