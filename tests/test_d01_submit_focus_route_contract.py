from __future__ import annotations

import unittest
from pathlib import Path


class D01SubmitFocusRouteContractTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.html = (root / "web" / "index.html").read_text(encoding="utf-8")
        self.bootstrap = (root / "web" / "stage1_release_bootstrap.js").read_text(encoding="utf-8")
        self.route = (root / "web" / "stage1_submit_focus_route.js").read_text(encoding="utf-8")
        self.release_ui = (root / "acs" / "stage1_release_ui.py").read_text(encoding="utf-8")

    def test_native_button_listener_is_known_to_precede_release_wrapper(self) -> None:
        self.assertIn("el('move-submit').addEventListener('click',submitMove)", self.html)
        self.assertIn("const baseSubmit = window.submitMove", self.bootstrap)
        self.assertIn("window.submitMove = wrappedSubmit", self.bootstrap)
        self.assertIn("wrappedSubmit.__stage1FocusPolicy = true", self.bootstrap)

    def test_packaged_click_is_routed_through_focus_policy_without_double_submit(self) -> None:
        text = self.route
        self.assertIn("typeof submit !== 'function' || !submit.__stage1FocusPolicy", text)
        self.assertIn("button.addEventListener('click', routeSubmitThroughFocusPolicy, true)", text)
        self.assertIn("event.stopImmediatePropagation()", text)
        self.assertIn("void window.submitMove()", text)
        self.assertLess(text.index("event.stopImmediatePropagation()"), text.index("void window.submitMove()"))
        self.assertIn("stage1SubmitFocusRouteReady", text)

    def test_release_loader_installs_route_after_wrapper_before_board_bridge(self) -> None:
        text = self.release_ui
        self.assertIn('submit_focus_route = _asset_root() / "web" / "stage1_submit_focus_route.js"', text)
        self.assertIn('(submit_focus_route, "Stage 1 submit focus route")', text)
        self.assertIn('submit_focus_route_source = submit_focus_route.read_text(encoding="utf-8")', text)
        bootstrap = text.index("window.evaluate_js(bootstrap_source)")
        route = text.index("window.evaluate_js(submit_focus_route_source)")
        board = text.index("window.evaluate_js(board_bridge_source)")
        self.assertLess(bootstrap, route)
        self.assertLess(route, board)

    def test_normal_move_input_enter_and_standard_text_keys_are_not_intercepted(self) -> None:
        self.assertIn("if(e.key==='Enter'){e.preventDefault();submitMove()}", self.html)
        self.assertNotIn("keydown", self.route)
        self.assertNotIn("keyup", self.route)
        self.assertNotIn("Ctrl", self.route)
        self.assertNotIn("clipboard", self.route)


if __name__ == "__main__":
    unittest.main()
