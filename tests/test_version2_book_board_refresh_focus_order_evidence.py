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
        # The canonical DOM harness now owns a controllable one-shot Stage1
        # repaint barrier. Reuse that real barrier instead of rewriting the
        # refresh stub, so this oracle cannot silently drift from production
        # event-drain serialization semantics.
        for required in (
            "let holdNextStage1Refresh = false;\n",
            "let heldStage1RefreshResolve = null;\n",
            "if (holdNextStage1Refresh) {\n",
            "heldStage1RefreshResolve = () => {\n",
        ):
            self.assertIn(
                required,
                source,
                "W4 Stage1 refresh barrier changed; re-audit Book->Board focus ordering oracle",
            )

        original_block = '''  currentRoute = "board";\n  eventQueue = [\n    { kind: "book-board", payload: { focus_target: "board-launcher" } },\n    { kind: "delegated", payload: { action_id: "book.open_position" } }\n  ];\n  intervalCallback();\n  await flush();\n  await flush();\n  check(originalMain.hidden === false, "queued Board transition did not restore the Stage 1 main");\n  check(workspace.hidden === true, "queued Board transition left the V2 product main exposed");\n  check(documentRef.activeElement === boardLauncher, "trailing delegated event erased the Book-to-Board focus target");\n'''
        ordered_block = '''  currentRoute = "board";\n  holdNextStage1Refresh = true;\n  heldStage1RefreshResolve = null;\n  eventQueue = [\n    { kind: "book-board", payload: { focus_target: "board-launcher" } },\n    { kind: "delegated", payload: { action_id: "book.open_position" } }\n  ];\n  intervalCallback();\n  await flush();\n  check(\n    typeof heldStage1RefreshResolve === "function",\n    "Book-to-Board did not awaitably start the canonical Stage 1 refresh"\n  );\n  check(\n    documentRef.activeElement !== boardLauncher,\n    "Book-to-Board restored final Board focus before Stage 1 repaint completed"\n  );\n  heldStage1RefreshResolve();\n  await flush();\n  await flush();\n  await flush();\n  check(originalMain.hidden === false, "queued Board transition did not restore the Stage 1 main");\n  check(workspace.hidden === true, "queued Board transition left the V2 product main exposed");\n  check(documentRef.activeElement === boardLauncher, "Book-to-Board did not restore Board focus after Stage 1 repaint completed");\n'''
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
