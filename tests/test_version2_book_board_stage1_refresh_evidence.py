from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "js" / "version2_release_bootstrap_dom_test.js"


class Version2BookBoardStage1RefreshEvidenceTests(unittest.TestCase):
    """Red-first convergence oracle for #495 Book projection + #462 V2 DOM routing.

    #495 makes the canonical release-board backend accept the BookBoard FEN.
    Once the V2 route returns to the original Stage1 board, that existing DOM must
    be refreshed through its canonical ``window.refreshState()`` renderer before
    the user/NVDA is focused into it.  A V2-only snapshot refresh is insufficient:
    it only hides/unhides the original Stage1 DOM and cannot repaint its 64 squares.

    This test reuses the W4 behavioral DOM harness without modifying its owner file.
    It injects one additional assertion into the already-covered Book->Board event
    scenario, then executes the resulting harness with Node on both CI platforms.
    """

    def test_book_board_transition_refreshes_original_stage1_dom(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for the Version 2 DOM evidence oracle")

        source = HARNESS.read_text(encoding="utf-8")
        before = (
            '  currentRoute = "board";\n'
            '  eventQueue = [\n'
            '    { kind: "book-board", payload: { focus_target: "board-launcher" } },\n'
        )
        after = (
            '  check(documentRef.activeElement === boardLauncher, '
            '"trailing delegated event erased the Book-to-Board focus target");\n'
        )
        self.assertIn(before, source, "W4 Book->Board behavioral scenario changed; re-audit the oracle")
        self.assertIn(after, source, "W4 Book->Board focus assertion changed; re-audit the oracle")

        source = source.replace(
            before,
            '  const beforeBookBoardStage1Refreshes = stage1RefreshCalls;\n' + before,
            1,
        )
        source = source.replace(
            after,
            after
            + '  check(stage1RefreshCalls === beforeBookBoardStage1Refreshes + 1, '
            + '"Book-to-Board transition exposed stale Stage1 DOM without refreshState");\n',
            1,
        )

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".js",
                prefix="book_board_stage1_refresh_",
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
            "Book->Board must refresh the original Stage1 DOM after the canonical "
            "Book FEN is projected and before Board focus is restored.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
