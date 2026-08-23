from __future__ import annotations

import unittest
from pathlib import Path


class Stage1SubmitListenerFocusRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.html = (root / "web" / "index.html").read_text(encoding="utf-8")
        self.bootstrap = (root / "web" / "stage1_release_bootstrap.js").read_text(encoding="utf-8")

    def test_preinstalled_click_listener_is_rebound_to_focus_policy_wrapper(self) -> None:
        self.assertIn("el('move-submit').addEventListener('click',submitMove)", self.html)

        start = self.bootstrap.index("function installMoveFocusPolicy()")
        end = self.bootstrap.index("function installMoveEntryIdentity()", start)
        body = self.bootstrap[start:end]

        self.assertIn("const baseSubmit = window.submitMove", body)
        self.assertIn("window.submitMove = wrappedSubmit", body)
        self.assertIn(
            "submit.removeEventListener('click', baseSubmit)",
            body,
            "The original click listener keeps the old function object and bypasses the focus-policy wrapper unless it is explicitly removed.",
        )
        self.assertIn(
            "submit.addEventListener('click', wrappedSubmit)",
            body,
            "UIA Invoke/click must route through the wrapped submit path that restores semantic board focus.",
        )
        self.assertLess(
            body.index("submit.removeEventListener('click', baseSubmit)"),
            body.index("submit.addEventListener('click', wrappedSubmit)"),
        )


if __name__ == "__main__":
    unittest.main()
