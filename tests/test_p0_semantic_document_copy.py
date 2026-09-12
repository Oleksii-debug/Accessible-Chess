from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SemanticDocumentCopyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        cls.v2_bootstrap = (ROOT / "web" / "version2_final_product_bootstrap.js").read_text(encoding="utf-8")
        cls.stage1_release = (ROOT / "acs" / "stage1_release_ui.py").read_text(encoding="utf-8")
        cls.release_ui = (ROOT / "acs" / "version2_release_ui.py").read_text(encoding="utf-8")
        cls.final_release = (ROOT / "acs" / "version2_education_mutation_release.py").read_text(encoding="utf-8")

    def test_both_shipping_windows_enable_native_document_text_selection(self) -> None:
        for source in (self.stage1_release, self.release_ui):
            self.assertRegex(source, r"create_window\([\s\S]*?text_select\s*=\s*True")

    def test_stage1_plain_ctrl_c_and_existing_selection_are_not_hijacked(self) -> None:
        self.assertIn("String(e.key).toLowerCase()==='c')return", self.index)
        self.assertIn("selection&&selection.toString()", self.index)
        self.assertNotRegex(
            self.index,
            r"(?is)(?:ctrlKey[^\n]{0,180}(?:key|code)[^\n]{0,80}['\"]c['\"][^\n]{0,300}preventDefault)|"
            r"(?:['\"]c['\"][^\n]{0,180}ctrlKey[^\n]{0,300}preventDefault)",
        )

    def test_v2_semantic_text_is_explicitly_selectable(self) -> None:
        self.assertIn('selectionStyle.id = "v2-semantic-selection-style"', self.v2_bootstrap)
        self.assertIn("user-select: text !important", self.v2_bootstrap)
        self.assertIn("-webkit-user-select: text !important", self.v2_bootstrap)
        self.assertIn("#main-content", self.v2_bootstrap)
        self.assertIn("#v2-workspace", self.v2_bootstrap)
        self.assertNotRegex(self.v2_bootstrap, r"(?i)user-select\s*:\s*none")

    def test_v2_refresh_preserves_meaningful_workspace_selection(self) -> None:
        self.assertIn("function captureWorkspaceSelection()", self.v2_bootstrap)
        self.assertIn("function restoreWorkspaceSelection(snapshot, routeId)", self.v2_bootstrap)
        self.assertIn("workspace.contains(range.startContainer)", self.v2_bootstrap)
        self.assertIn("workspace.contains(range.endContainer)", self.v2_bootstrap)
        self.assertIn("const selectionSnapshot = captureWorkspaceSelection();", self.v2_bootstrap)
        self.assertIn("restoreWorkspaceSelection(selectionSnapshot, routeId);", self.v2_bootstrap)
        self.assertIn("snapshot.routeId !== routeId", self.v2_bootstrap)
        self.assertIn("nearestSelectionStart", self.v2_bootstrap)

    def test_v2_incremental_library_rerender_preserves_selection_too(self) -> None:
        render_import = self.v2_bootstrap.index('if (event.kind === "render-import")')
        capture = self.v2_bootstrap.index("const selectionSnapshot = captureWorkspaceSelection();", render_import)
        apply_call = self.v2_bootstrap.index("AccessibleChessLibrarySurface.apply", capture)
        restore = self.v2_bootstrap.index("restoreWorkspaceSelection(selectionSnapshot, currentRouteId);", apply_call)
        self.assertLess(capture, apply_call)
        self.assertLess(apply_call, restore)

    def test_v2_does_not_replace_native_copy_with_scripted_clipboard(self) -> None:
        self.assertNotIn("navigator.clipboard", self.v2_bootstrap)
        self.assertNotIn("execCommand", self.v2_bootstrap)
        self.assertNotRegex(
            self.v2_bootstrap,
            r"(?is)(?:ctrlKey[^\n]{0,180}(?:key|code)[^\n]{0,80}['\"]c['\"][^\n]{0,300}preventDefault)|"
            r"(?:['\"]c['\"][^\n]{0,180}ctrlKey[^\n]{0,300}preventDefault)",
        )

    def test_v2_selection_repair_is_local_not_a_global_dom_monkeypatch(self) -> None:
        self.assertNotIn("Node.prototype", self.v2_bootstrap)
        self.assertNotIn("Element.prototype.replaceChildren =", self.v2_bootstrap)
        self.assertNotIn("Object.defineProperty", self.v2_bootstrap)

    def test_current_final_product_still_loads_the_repaired_v2_bootstrap(self) -> None:
        self.assertIn('root / "version2_final_product_bootstrap.js"', self.final_release)

    def test_selection_restore_never_crosses_product_routes(self) -> None:
        self.assertIn("routeId: currentRouteId", self.v2_bootstrap)
        self.assertIn("snapshot.routeId !== routeId", self.v2_bootstrap)


if __name__ == "__main__":
    unittest.main()
