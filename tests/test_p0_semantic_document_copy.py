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
        cls.p0_runtime = (ROOT / "web" / "p0_accessibility_runtime.js").read_text(encoding="utf-8")
        cls.stage1_release = (ROOT / "acs" / "stage1_release_ui.py").read_text(encoding="utf-8")
        cls.release_ui = (ROOT / "acs" / "version2_release_ui.py").read_text(encoding="utf-8")
        cls.final_release = (ROOT / "acs" / "version2_education_mutation_release.py").read_text(encoding="utf-8")
        cls.shipping_surfaces = [
            (ROOT / "web" / name).read_text(encoding="utf-8")
            for name in (
                "full_product_pgn.js",
                "full_product_library.js",
                "full_product_books_training.js",
                "full_product_teacher.js",
                "full_product_classroom.js",
                "full_product_education.js",
            )
        ]

    def test_both_shipping_windows_enable_native_document_text_selection(self) -> None:
        for source in (self.stage1_release, self.release_ui):
            self.assertRegex(source, r"create_window\([\s\S]*?text_select\s*=\s*True")

    def test_stage1_plain_ctrl_c_and_existing_selection_are_not_hijacked(self) -> None:
        handler_start = self.index.index("document.addEventListener('keydown',async e=>{if(capture)return;")
        handler_end = self.index.index("\nel('move-submit').addEventListener", handler_start)
        handler = self.index[handler_start:handler_end]

        ctrl_c_guard = "if(e.ctrlKey&&!e.altKey&&!e.shiftKey&&String(e.key).toLowerCase()==='c')return;"
        selection_guard = (
            "const selection=window.getSelection&&window.getSelection();"
            "if(e.ctrlKey&&!e.altKey&&selection&&selection.toString())return;"
        )
        binding_resolution = "const chord=eventChord(e);"

        ctrl_c_index = handler.index(ctrl_c_guard)
        selection_index = handler.index(selection_guard)
        binding_index = handler.index(binding_resolution)
        prevent_default_index = handler.index("e.preventDefault();", binding_index)
        execute_index = handler.index("executeAction(a.actionId)", prevent_default_index)

        self.assertNotIn("preventDefault", handler[:ctrl_c_index])
        self.assertLess(ctrl_c_index, selection_index)
        self.assertLess(selection_index, binding_index)
        self.assertLess(binding_index, prevent_default_index)
        self.assertLess(prevent_default_index, execute_index)

    def test_v2_semantic_text_is_explicitly_selectable(self) -> None:
        self.assertIn('selectionStyle.id = "v2-semantic-selection-style"', self.v2_bootstrap)
        self.assertIn("user-select: text !important", self.v2_bootstrap)
        self.assertIn("-webkit-user-select: text !important", self.v2_bootstrap)
        self.assertIn("#main-content", self.v2_bootstrap)
        self.assertIn("#v2-workspace", self.v2_bootstrap)
        self.assertIn("#main-content button", self.v2_bootstrap)
        self.assertIn("#v2-workspace button", self.v2_bootstrap)
        self.assertIn("#v2-navigation", self.v2_bootstrap)
        self.assertIn("#v2-navigation button", self.v2_bootstrap)
        self.assertNotRegex(self.v2_bootstrap, r"(?i)user-select\s*:\s*none")

    def test_shipping_semantic_surfaces_do_not_hide_or_disable_ordinary_text(self) -> None:
        hidden_or_uncopyable = re.compile(
            r"(?i)(?:-webkit-)?user-select\s*:\s*none|"
            r"visibility\s*:\s*hidden|"
            r"color\s*:\s*transparent|"
            r"clip-path\s*:|"
            r"text-indent\s*:\s*-\d|"
            r"left\s*:\s*-\d"
        )
        for source in self.shipping_surfaces:
            self.assertIn("element.textContent = String(text)", source)
            self.assertNotRegex(source, hidden_or_uncopyable)

    def test_v2_navigation_selection_is_inside_the_same_retention_authority(self) -> None:
        self.assertIn('const navigation = documentRef.getElementById("v2-navigation");', self.p0_runtime)
        self.assertIn('const activeNavigation = documentRef.getElementById("v2-navigation");', self.p0_runtime)
        self.assertIn("activeNavigation && activeNavigation.contains(node)", self.p0_runtime)
        self.assertIn('attributeFilter: ["hidden", "aria-current"]', self.p0_runtime)
        self.assertIn("if (navigation) observer.observe(navigation, observerOptions);", self.p0_runtime)

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

    def test_current_final_product_loads_canonical_p0_selection_runtime(self) -> None:
        bootstrap = self.final_release.index('root / "version2_final_product_bootstrap.js"')
        runtime = self.final_release.index('root / "p0_accessibility_runtime.js"')
        self.assertLess(bootstrap, runtime)

    def test_stage1_does_not_duplicate_canonical_selection_runtime(self) -> None:
        self.assertNotIn("function captureTextSelection(root)", self.index)
        self.assertNotIn("function restoreTextSelection(root,snapshot)", self.index)
        self.assertNotIn("function nearestTextOccurrence(text,needle,offset)", self.index)

    def test_canonical_runtime_preserves_backward_selection_direction(self) -> None:
        self.assertIn("backward: backward", self.p0_runtime)
        self.assertIn('typeof selection.setBaseAndExtent === "function"', self.p0_runtime)
        self.assertIn('typeof selection.collapse === "function"', self.p0_runtime)
        self.assertIn('typeof selection.extend === "function"', self.p0_runtime)
        self.assertIn("selection.setBaseAndExtent(", self.p0_runtime)
        self.assertIn("selection.collapse(endPoint.node, endPoint.offset)", self.p0_runtime)
        self.assertIn("selection.extend(startPoint.node, startPoint.offset)", self.p0_runtime)

    def test_v2_bootstrap_preserves_backward_selection_direction(self) -> None:
        self.assertIn("backward: backward", self.v2_bootstrap)
        self.assertIn('typeof selection.setBaseAndExtent === "function"', self.v2_bootstrap)
        self.assertIn('typeof selection.collapse === "function"', self.v2_bootstrap)
        self.assertIn('typeof selection.extend === "function"', self.v2_bootstrap)
        self.assertIn("selection.setBaseAndExtent(", self.v2_bootstrap)
        self.assertIn("selection.collapse(endPoint.node, endPoint.offset)", self.v2_bootstrap)
        self.assertIn("selection.extend(startPoint.node, startPoint.offset)", self.v2_bootstrap)

    def test_duplicate_selection_restore_uses_bounded_semantic_context(self) -> None:
        for source in (self.p0_runtime, self.v2_bootstrap):
            self.assertIn("SELECTION_CONTEXT_CHARS = 48", source)
            self.assertIn("function selectionContext(fullText, start, end)", source)
            self.assertIn("function contextMatchScore(fullText, selectedText, start, before, after)", source)
            self.assertIn("before: context.before", source)
            self.assertIn("after: context.after", source)
            self.assertIn("snapshot.before", source)
            self.assertIn("snapshot.after", source)

    def test_selection_restore_never_crosses_product_routes(self) -> None:
        self.assertIn("routeId: currentRouteId", self.v2_bootstrap)
        self.assertIn("snapshot.routeId !== routeId", self.v2_bootstrap)


if __name__ == "__main__":
    unittest.main()
