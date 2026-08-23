from __future__ import annotations

import unittest
from pathlib import Path


class D01SubmitFocusRouteContractTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.html = (root / "web" / "index.html").read_text(encoding="utf-8")
        self.bootstrap = (root / "web" / "stage1_release_bootstrap.js").read_text(encoding="utf-8")

    def test_preinstalled_native_button_listener_is_rebound_to_focus_policy(self) -> None:
        self.assertIn("el('move-submit').addEventListener('click',submitMove)", self.html)

        start = self.bootstrap.index("function installMoveFocusPolicy()")
        end = self.bootstrap.index("function installMoveEntryIdentity()", start)
        body = self.bootstrap[start:end]

        self.assertIn("const baseSubmit = window.submitMove", body)
        self.assertIn("wrappedSubmit.__stage1FocusPolicy = true", body)
        self.assertIn("const submit = byId('move-submit')", body)
        self.assertIn("submit.removeEventListener('click', baseSubmit)", body)
        self.assertIn("submit.addEventListener('click', wrappedSubmit)", body)
        self.assertIn("window.submitMove = wrappedSubmit", body)
        self.assertLess(
            body.index("submit.removeEventListener('click', baseSubmit)"),
            body.index("submit.addEventListener('click', wrappedSubmit)"),
        )

    def test_button_rebind_occurs_only_inside_existing_focus_policy(self) -> None:
        self.assertEqual(self.bootstrap.count("submit.removeEventListener('click', baseSubmit)"), 1)
        self.assertEqual(self.bootstrap.count("submit.addEventListener('click', wrappedSubmit)"), 1)
        self.assertNotIn("cloneNode", self.bootstrap)
        self.assertNotIn("replaceWith", self.bootstrap)

    def test_normal_move_input_enter_semantics_remain_original(self) -> None:
        self.assertIn("if(e.key==='Enter'){e.preventDefault();submitMove()}", self.html)
        self.assertIn("if(r&&r.ok){input.value='';input.focus()}else{input.focus();input.select()}", self.html)
        policy = self.bootstrap[
            self.bootstrap.index("function installMoveFocusPolicy()"):self.bootstrap.index(
                "function installMoveEntryIdentity()"
            )
        ]
        self.assertNotIn("keydown", policy)
        self.assertNotIn("keyup", policy)
        self.assertNotIn("clipboard", policy)

    def test_focus_wrapper_retains_bounded_board_restore(self) -> None:
        self.assertIn("if (boardSquare) settleBoardFocusAfterInvoke(boardSquare)", self.bootstrap)
        self.assertIn("restoreBoardSquare(square, generation)", self.bootstrap)
        self.assertIn("setTimeout(() => restoreBoardSquare(square, generation), 0)", self.bootstrap)
        self.assertIn("setTimeout(() => restoreBoardSquare(square, generation), 50)", self.bootstrap)


if __name__ == "__main__":
    unittest.main()
