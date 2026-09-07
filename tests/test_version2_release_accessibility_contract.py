from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = (ROOT / "web" / "version2_release_bootstrap.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
SHELL = (ROOT / "acs" / "full_product_ui_shell.py").read_text(encoding="utf-8")
PGN_PROJECTION = (ROOT / "acs" / "pgn_webview_projection.py").read_text(encoding="utf-8")
BOOK_PROJECTION = (ROOT / "acs" / "book_webview_projection.py").read_text(encoding="utf-8")


class Version2ReleaseAccessibilityContractTests(unittest.TestCase):
    def test_navigation_buttons_keep_concise_native_names(self) -> None:
        self.assertIn('const button = documentRef.createElement("button")', BOOTSTRAP)
        self.assertIn('button.textContent = String(item.label || item.route_id || "")', BOOTSTRAP)
        self.assertIn('button.setAttribute("aria-current", "page")', BOOTSTRAP)
        self.assertNotIn("aria-describedby", BOOTSTRAP)
        self.assertNotIn('button.id + "-description"', BOOTSTRAP)

    def test_v2_navigation_is_a_named_landmark_in_both_languages(self) -> None:
        self.assertIn('const nav = documentRef.createElement("nav")', BOOTSTRAP)
        self.assertIn('nav.setAttribute("aria-label", uiText(', BOOTSTRAP)
        self.assertIn('"Розділи Accessible Chess"', BOOTSTRAP)
        self.assertIn('"Accessible Chess sections"', BOOTSTRAP)
        self.assertIn('navHeading.textContent = uiText("Розділи", "Sections")', BOOTSTRAP)

    def test_document_language_is_set_before_navigation_is_rendered(self) -> None:
        language = '    documentRef.documentElement.lang = currentLanguage;'
        navigation_call = '    renderNavigation(snapshot);'
        self.assertIn(language, BOOTSTRAP)
        self.assertIn(navigation_call, BOOTSTRAP)
        self.assertLess(BOOTSTRAP.index(language), BOOTSTRAP.index(navigation_call))

    def test_workspace_does_not_create_a_second_live_region(self) -> None:
        self.assertIn('workspace.setAttribute("aria-live", "off")', BOOTSTRAP)
        self.assertNotIn('workspace.setAttribute("aria-live", "polite")', BOOTSTRAP)
        self.assertNotIn('workspace.setAttribute("aria-live", "assertive")', BOOTSTRAP)

    def test_product_routes_keep_a_real_main_landmark(self) -> None:
        # V2 product routes hide the Stage 1 main region. Their replacement must
        # therefore itself be a native main landmark, not a generic section.
        self.assertIn('const workspace = documentRef.createElement("main")', BOOTSTRAP)
        self.assertNotIn('const workspace = documentRef.createElement("section")', BOOTSTRAP)
        product_start = BOOTSTRAP.index('  function renderProductSurface(')
        product_end = BOOTSTRAP.index('  function render(snapshot, restoreFocus)', product_start)
        product = BOOTSTRAP[product_start:product_end]
        self.assertIn('originalMain.hidden = true;', product)
        self.assertIn('workspace.hidden = false;', product)
        self.assertLess(product.index('originalMain.hidden = true;'), product.index('workspace.hidden = false;'))
        stage1_restore = BOOTSTRAP[product_end:]
        self.assertIn('workspace.hidden = true;', stage1_restore)
        self.assertIn('originalMain.hidden = false;', stage1_restore)

    def test_fallback_status_text_follows_document_language(self) -> None:
        for english in (
            "Could not open the section.",
            "No PGN is open yet.",
            "No book is open yet.",
            "Could not load Version 2 sections.",
        ):
            with self.subTest(text=english):
                self.assertIn(english, BOOTSTRAP)

    def test_initial_snapshot_restores_the_shell_keyboard_focus_target(self) -> None:
        # The shell's initial Board route names the real Stage 1 move edit as its
        # keyboard target. The V2 bootstrap must apply that target on the first
        # snapshot rather than leaving WebView2/NVDA focus at an undefined body.
        self.assertIn('default_focus_id="move-input"', SHELL)
        self.assertIn('<input id="move-input" type="text"', HTML)
        self.assertIn('function restoreStage1Focus(routeId, requestedFocus)', BOOTSTRAP)
        self.assertIn('if (focusById(requestedFocus)) return true;', BOOTSTRAP)
        self.assertIn('return focusById(stage1Focus[routeId] || "");', BOOTSTRAP)
        self.assertIn('return documentRef.activeElement === target;', BOOTSTRAP)
        self.assertIn('refresh(true).catch(function () {', BOOTSTRAP)
        self.assertNotIn('refresh(false).catch(function () {', BOOTSTRAP)

    def test_product_route_focus_converges_to_real_surface_or_current_navigation(self) -> None:
        # Shell defaults are presentation-level placeholders. PGN and Books own
        # the exact DOM identities of their current canonical content, so route
        # entry must converge to those identities instead of dropping focus when
        # renderNavigation replaces the previously focused navigation button.
        self.assertIn('return "pgn-node-" + sha256(', PGN_PROJECTION)
        self.assertIn('"focus_target": focus_target', PGN_PROJECTION)
        self.assertIn('"dom_id": f"book-block-{block.index}"', BOOK_PROJECTION)
        self.assertIn('"focus_target": snapshot["block"]["dom_id"]', BOOK_PROJECTION)

        self.assertIn('function productSurfaceFocusTarget(snapshot, routeId)', BOOTSTRAP)
        self.assertIn('return String(snapshot.pgn.focus_target || "");', BOOTSTRAP)
        self.assertIn('return String(block.dom_id || "");', BOOTSTRAP)
        self.assertIn('function restoreProductFocus(snapshot, routeId, requestedFocus)', BOOTSTRAP)
        self.assertIn('if (active && workspace.contains(active)) return true;', BOOTSTRAP)
        self.assertIn('if (focusById(productSurfaceFocusTarget(snapshot, routeId))) return true;', BOOTSTRAP)
        self.assertIn('if (focusById(requestedFocus)) return true;', BOOTSTRAP)
        self.assertIn('return focusById("v2-nav-" + routeId);', BOOTSTRAP)
        self.assertIn('renderProductSurface(snapshot, routeId, requestedFocus, restoreFocus);', BOOTSTRAP)
        self.assertIn('if (restoreFocus) restoreProductFocus(snapshot, routeId, requestedFocus);', BOOTSTRAP)

    def test_background_event_refresh_never_steals_keyboard_focus(self) -> None:
        drain_start = BOOTSTRAP.index('  function drainEvents()')
        drain_end = BOOTSTRAP.index('  documentRef.addEventListener("focusin"', drain_start)
        drain = BOOTSTRAP[drain_start:drain_end]
        self.assertIn('refresh(false);', drain)
        self.assertNotIn('refresh(true);', drain)


if __name__ == "__main__":
    unittest.main()
