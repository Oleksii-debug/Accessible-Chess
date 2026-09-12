from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SemanticDocumentCopyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        cls.copy_surface = (ROOT / "web" / "document_text_copy.js").read_text(encoding="utf-8")
        cls.stage1_release = (ROOT / "acs" / "stage1_release_ui.py").read_text(encoding="utf-8")
        cls.release_ui = (ROOT / "acs" / "version2_release_ui.py").read_text(encoding="utf-8")
        cls.final_release = (ROOT / "acs" / "version2_education_mutation_release.py").read_text(encoding="utf-8")

    def test_shipping_windows_explicitly_enable_document_text_selection(self) -> None:
        for source in (self.stage1_release, self.release_ui):
            self.assertRegex(
                source,
                r"create_window\([\s\S]*?text_select\s*=\s*True",
            )

    def test_plain_ctrl_c_and_existing_selection_are_not_hijacked(self) -> None:
        self.assertIn("String(e.key).toLowerCase()==='c')return", self.index)
        self.assertIn("selection&&selection.toString()", self.index)
        self.assertNotRegex(
            self.index,
            r"(?is)(?:ctrlKey[^\n]{0,180}(?:key|code)[^\n]{0,80}['\"]c['\"][^\n]{0,300}preventDefault)|"
            r"(?:['\"]c['\"][^\n]{0,180}ctrlKey[^\n]{0,300}preventDefault)",
        )

    def test_semantic_text_is_not_css_selection_suppressed(self) -> None:
        combined = self.index + "\n" + self.copy_surface
        self.assertNotRegex(combined, r"(?i)user-select\s*:\s*none")
        self.assertIn("user-select: text !important", self.copy_surface)
        self.assertIn("-webkit-user-select: text !important", self.copy_surface)
        self.assertIn("#main-content", self.copy_surface)
        self.assertIn("#v2-workspace", self.copy_surface)

    def test_dynamic_rerender_preserves_meaningful_semantic_selection(self) -> None:
        self.assertIn("function captureSelectionForMutation(node)", self.copy_surface)
        self.assertIn("function restoreSelection(snapshot)", self.copy_surface)
        self.assertIn('Object.getOwnPropertyDescriptor(global.Node.prototype, "textContent")', self.copy_surface)
        self.assertIn('Object.getOwnPropertyDescriptor(global.Element.prototype, "innerHTML")', self.copy_surface)
        self.assertIn("global.Element.prototype.replaceChildren", self.copy_surface)
        self.assertIn("const snapshot = captureSelectionForMutation(this)", self.copy_surface)
        self.assertIn("if (snapshot) restoreSelection(snapshot)", self.copy_surface)
        self.assertIn('dataset.semanticDocumentSelectionGuardReady = "true"', self.copy_surface)
        self.assertIn("selectionTouches: selectionTouches", self.copy_surface)

    def test_copy_review_fallback_is_a_real_readonly_textarea(self) -> None:
        self.assertIn('documentRef.createElement("textarea")', self.copy_surface)
        self.assertIn("textarea.readOnly = true", self.copy_surface)
        self.assertNotIn("textarea.disabled = true", self.copy_surface)
        self.assertIn("textarea.focus()", self.copy_surface)
        self.assertIn("textarea.setSelectionRange(0, 0)", self.copy_surface)
        self.assertIn("Ctrl+C", self.copy_surface)
        self.assertIn("Ctrl+A", self.copy_surface)

    def test_fallback_uses_visible_semantic_section_not_debug_or_provider_text(self) -> None:
        self.assertIn('documentRef.getElementById("v2-workspace")', self.copy_surface)
        self.assertIn('documentRef.getElementById("main-content")', self.copy_surface)
        self.assertIn("innerText", self.copy_surface)
        forbidden = ("traceback", "uci output", "provider internals", "local path")
        lower = self.copy_surface.lower()
        for token in forbidden:
            self.assertNotIn(token, lower)

    def test_copy_surface_does_not_intercept_or_prevent_native_copy(self) -> None:
        self.assertNotIn('addEventListener("keydown"', self.copy_surface)
        self.assertNotIn("preventDefault()", self.copy_surface)
        self.assertNotIn("execCommand", self.copy_surface)
        self.assertNotIn("navigator.clipboard", self.copy_surface)

    def test_stage1_packages_copy_surface_before_release_bootstrap(self) -> None:
        self.assertIn('document_copy = _asset_root() / "web" / "document_text_copy.js"', self.stage1_release)
        self.assertIn('document_copy_source = document_copy.read_text(encoding="utf-8")', self.stage1_release)
        copy_eval = self.stage1_release.index("window.evaluate_js(document_copy_source)")
        bootstrap_eval = self.stage1_release.index("window.evaluate_js(bootstrap_source)")
        self.assertLess(copy_eval, bootstrap_eval)

    def test_current_final_product_packages_copy_surface_before_dynamic_routes(self) -> None:
        copy_pos = self.final_release.index('root / "document_text_copy.js"')
        pgn_pos = self.final_release.index('root / "full_product_pgn.js"')
        final_bootstrap_pos = self.final_release.index('root / "version2_final_product_bootstrap.js"')
        self.assertLess(copy_pos, pgn_pos)
        self.assertLess(copy_pos, final_bootstrap_pos)

    def test_copy_surface_is_idempotent_and_non_live(self) -> None:
        self.assertIn("__accessibleChessDocumentTextCopyInstalled", self.copy_surface)
        self.assertNotIn("aria-live", self.copy_surface)
        self.assertIn('dataset.semanticDocumentCopyReady = "true"', self.copy_surface)


if __name__ == "__main__":
    unittest.main()
