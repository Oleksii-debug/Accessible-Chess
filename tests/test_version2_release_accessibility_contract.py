from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = (ROOT / "web" / "version2_release_bootstrap.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
SHELL = (ROOT / "acs" / "full_product_ui_shell.py").read_text(encoding="utf-8")
PGN_PROJECTION = (ROOT / "acs" / "pgn_webview_projection.py").read_text(encoding="utf-8")
BOOK_PROJECTION = (ROOT / "acs" / "book_webview_projection.py").read_text(encoding="utf-8")
TRAINING_SURFACE = (ROOT / "web" / "full_product_books_training.js").read_text(encoding="utf-8")
WINDOWS_COMPOSITION = (ROOT / ".github" / "workflows" / "version2-windows-composition.yml").read_text(encoding="utf-8")


class Version2ReleaseAccessibilityContractTests(unittest.TestCase):
    def test_navigation_buttons_keep_concise_native_names(self) -> None:
        self.assertIn('const label = boundedText(item.label, MAX_NAVIGATION_LABEL);', BOOTSTRAP)
        self.assertIn('const button = documentRef.createElement("button")', BOOTSTRAP)
        self.assertIn('button.textContent = label;', BOOTSTRAP)
        self.assertIn('button.setAttribute("aria-current", "page")', BOOTSTRAP)
        self.assertNotIn("aria-describedby", BOOTSTRAP)
        self.assertNotIn('button.id + "-description"', BOOTSTRAP)

    def test_v2_navigation_is_a_named_landmark_in_both_languages(self) -> None:
        self.assertIn('const nav = documentRef.createElement("nav")', BOOTSTRAP)
        self.assertIn('nav.setAttribute(', BOOTSTRAP)
        self.assertIn(
            'uiTextFor(language, "Розділи Accessible Chess", "Accessible Chess sections")',
            BOOTSTRAP,
        )
        self.assertIn(
            'navHeading.textContent = uiTextFor(language, "Розділи", "Sections")',
            BOOTSTRAP,
        )

    def test_document_language_is_set_before_navigation_is_rendered(self) -> None:
        start = BOOTSTRAP.index('  function commitShellChrome(')
        end = BOOTSTRAP.index('  function deactivateLibrarySurface()', start)
        commit = BOOTSTRAP[start:end]
        language = 'documentRef.documentElement.lang = language;'
        navigation = 'navList.replaceChildren(navigationState.fragment);'
        self.assertIn(language, commit)
        self.assertIn(navigation, commit)
        self.assertLess(commit.index(language), commit.index(navigation))

    def test_workspace_does_not_create_a_second_live_region(self) -> None:
        self.assertIn('workspace.setAttribute("aria-live", "off")', BOOTSTRAP)
        self.assertNotIn('workspace.setAttribute("aria-live", "polite")', BOOTSTRAP)
        self.assertNotIn('workspace.setAttribute("aria-live", "assertive")', BOOTSTRAP)

    def test_product_routes_keep_a_real_main_landmark(self) -> None:
        self.assertIn('const workspace = documentRef.createElement("main")', BOOTSTRAP)
        self.assertNotIn('const workspace = documentRef.createElement("section")', BOOTSTRAP)
        render_start = BOOTSTRAP.index('  function render(snapshot, restoreFocus)')
        render_end = BOOTSTRAP.index('  function snapshotShellPublicationToken', render_start)
        render = BOOTSTRAP[render_start:render_end]
        product_commit = render.index('commitShellChrome(navigationState, nextLanguage, routeId);')
        hide_stage1 = render.index('originalMain.hidden = true;', product_commit)
        show_workspace = render.index('workspace.hidden = false;', hide_stage1)
        self.assertLess(product_commit, hide_stage1)
        self.assertLess(hide_stage1, show_workspace)
        stage1_commit = render.index(
            'commitShellChrome(navigationState, nextLanguage, routeId);',
            show_workspace,
        )
        hide_workspace = render.index('workspace.hidden = true;', stage1_commit)
        show_stage1 = render.index('originalMain.hidden = false;', hide_workspace)
        self.assertLess(stage1_commit, hide_workspace)
        self.assertLess(hide_workspace, show_stage1)

    def test_fallback_status_text_follows_document_language(self) -> None:
        for english in (
            "Could not open the section.",
            "No PGN is open yet.",
            "The Library is not ready to browse yet.",
            "No book is open yet.",
            "Could not load Version 2 sections.",
            "Could not refresh the board.",
        ):
            with self.subTest(text=english):
                self.assertIn(english, BOOTSTRAP)

    def test_initial_snapshot_restores_the_shell_keyboard_focus_target(self) -> None:
        self.assertIn('default_focus_id="move-input"', SHELL)
        self.assertIn('<input id="move-input" type="text"', HTML)
        self.assertIn('function restoreStage1Focus(routeId, requestedFocus)', BOOTSTRAP)
        self.assertIn('if (focusById(requestedFocus)) return true;', BOOTSTRAP)
        self.assertIn('if (focusById(stage1Focus[routeId] || "")) return true;', BOOTSTRAP)
        self.assertIn('return focusById("v2-nav-" + routeId);', BOOTSTRAP)
        self.assertIn('return documentRef.activeElement === target;', BOOTSTRAP)
        self.assertIn('refresh(true).catch(function () {', BOOTSTRAP)
        self.assertNotIn('refresh(false).catch(function () {', BOOTSTRAP)

    def test_training_shell_focus_names_the_real_answer_control(self) -> None:
        self.assertIn('default_focus_id="training-answer"', SHELL)
        self.assertNotIn('default_focus_id="training-prompt"', SHELL)
        self.assertIn('input.id = "training-answer";', TRAINING_SURFACE)
        product_start = BOOTSTRAP.index('  function renderProductSurface(')
        product_end = BOOTSTRAP.index('  function render(snapshot, restoreFocus)', product_start)
        product = BOOTSTRAP[product_start:product_end]
        self.assertIn('requestedFocus === "training-prompt"', product)
        self.assertIn('? "training-answer"', product)
        self.assertIn('focus || "training-answer"', product)

    def test_focus_targets_under_hidden_routes_are_never_programmatically_focused(self) -> None:
        self.assertIn('function hiddenByAncestor(target)', BOOTSTRAP)
        self.assertIn('if (node.hidden) return true;', BOOTSTRAP)
        self.assertIn('node = node.parentNode;', BOOTSTRAP)
        self.assertIn('if (!target || hiddenByAncestor(target) || typeof target.focus !== "function") return false;', BOOTSTRAP)

    def test_product_route_focus_converges_to_real_surface_or_current_navigation(self) -> None:
        self.assertIn('return "pgn-node-" + sha256(', PGN_PROJECTION)
        self.assertIn('"focus_target": focus_target', PGN_PROJECTION)
        self.assertIn('"dom_id": f"book-block-{block.index}"', BOOK_PROJECTION)
        self.assertIn('"focus_target": snapshot["block"]["dom_id"]', BOOK_PROJECTION)
        self.assertIn('function productSurfaceFocusTarget(snapshot, routeId)', BOOTSTRAP)
        self.assertIn(
            'return validFocusId(snapshot.pgn.focus_target) ? snapshot.pgn.focus_target : "";',
            BOOTSTRAP,
        )
        self.assertIn('return validFocusId(block.dom_id) ? block.dom_id : "";', BOOTSTRAP)
        self.assertIn('function restoreProductFocus(snapshot, routeId, requestedFocus)', BOOTSTRAP)
        self.assertIn('if (active && workspace.contains(active)) return true;', BOOTSTRAP)
        self.assertIn('if (focusById(productSurfaceFocusTarget(snapshot, routeId))) return true;', BOOTSTRAP)
        self.assertIn('if (focusById(requestedFocus)) return true;', BOOTSTRAP)
        self.assertIn('return focusById("v2-nav-" + routeId);', BOOTSTRAP)
        self.assertIn('productFocus = renderProductSurface(', BOOTSTRAP)
        self.assertIn(
            'restoreProductFocus(snapshot, routeId, productFocus);',
            BOOTSTRAP,
        )

    def test_empty_product_routes_have_heading_and_focusable_status(self) -> None:
        self.assertRegex(
            BOOTSTRAP,
            r'routeId === "pgn"\s*\|\|\s*routeId === "library"\s*\|\|\s*routeId === "books"\s*\|\|\s*routeId === "training"',
        )
        self.assertIn('return "v2-" + routeId + "-empty-status";', BOOTSTRAP)
        self.assertIn('function renderEmptyProduct(routeId, heading, language)', BOOTSTRAP)
        self.assertIn('const title = documentRef.createElement("h2");', BOOTSTRAP)
        self.assertIn('uiTextFor(language, "Бібліотека", "Library")', BOOTSTRAP)
        self.assertIn(
            'uiTextFor(language, "Бібліотека ще не готова до перегляду.", "The Library is not ready to browse yet.")',
            BOOTSTRAP,
        )
        self.assertIn('status.id = emptyStatusId(routeId);', BOOTSTRAP)
        self.assertIn('status.tabIndex = -1;', BOOTSTRAP)
        self.assertIn('workspace.replaceChildren(title, status);', BOOTSTRAP)
        self.assertIn('renderEmptyProduct(routeId, heading, language);', BOOTSTRAP)
        self.assertIn('const requestedFocus = validFocusId(screen.focus_target)', BOOTSTRAP)
        self.assertIn('? screen.focus_target', BOOTSTRAP)
        self.assertIn('const heading = boundedText(screen.heading, MAX_SCREEN_HEADING);', BOOTSTRAP)

    def test_global_navigation_focus_does_not_overwrite_route_local_history(self) -> None:
        focus_start = BOOTSTRAP.index('  documentRef.addEventListener("focusin"')
        focus_end = BOOTSTRAP.index('  refresh(true).catch(function () {', focus_start)
        focus_handler = BOOTSTRAP[focus_start:focus_end]
        skip = 'if (target.id.indexOf("v2-nav-") === 0) return;'
        record = 'bridge.v2_record_focus(target.id)'
        self.assertIn('const FOCUS_ID_PATTERN = /^[A-Za-z0-9_-]{1,160}$/;', BOOTSTRAP)
        self.assertIn('function validFocusId(value)', BOOTSTRAP)
        self.assertIn('if (!target || !validFocusId(target.id)) return;', focus_handler)
        self.assertIn(skip, focus_handler)
        self.assertIn(record, focus_handler)
        self.assertLess(focus_handler.index('validFocusId(target.id)'), focus_handler.index(record))
        self.assertLess(focus_handler.index(skip), focus_handler.index(record))

    def test_library_import_events_patch_only_the_import_region(self) -> None:
        apply_start = BOOTSTRAP.index('  function applyQueuedEvent(event, orderedStage1Refreshes)')
        apply_end = BOOTSTRAP.index('  function drainEvents()', apply_start)
        queued = BOOTSTRAP[apply_start:apply_end]
        self.assertIn('if (event.kind === "render-import")', queued)
        self.assertIn('currentRouteId === "library"', queued)
        self.assertIn(
            'global.AccessibleChessLibrarySurface.apply(workspace, event, areaInvoke("library"), announce);',
            queued,
        )
        self.assertIn('return false;', queued)
        self.assertIn('function delegatedHasOwnPresentationEvent(actionId)', BOOTSTRAP)
        self.assertIn('actionId === "library.import" || actionId === "library.cancel_import"', BOOTSTRAP)
        self.assertIn('if (delegatedHasOwnPresentationEvent(actionId)) return false;', queued)
        drain_start = BOOTSTRAP.index('  function drainEvents()')
        drain_end = BOOTSTRAP.index('  documentRef.addEventListener("focusin"', drain_start)
        drain = BOOTSTRAP[drain_start:drain_end]
        self.assertIn('let needsRefresh = false;', drain)
        self.assertIn('const refreshRequired = applyQueuedEvent(event, orderedStage1Refreshes);', drain)
        self.assertIn('if (refreshRequired) needsRefresh = true;', drain)
        self.assertIn('if (!needsRefresh && !orderedStage1Refreshes.length)', drain)

    def test_status_only_events_announce_without_rebuilding_the_active_surface(self) -> None:
        apply_start = BOOTSTRAP.index('  function applyQueuedEvent(event, orderedStage1Refreshes)')
        apply_end = BOOTSTRAP.index('  function drainEvents()', apply_start)
        queued = BOOTSTRAP[apply_start:apply_end]
        self.assertIn('if (payload.announcement) announce(payload.announcement);', queued)
        self.assertIn('return event.kind !== "error" && event.kind !== "status";', queued)

    def test_native_stage1_delegated_actions_refresh_the_existing_stage1_renderer(self) -> None:
        self.assertIn('async function refreshState()', HTML)
        self.assertIn('function isVersion2DomainAction(actionId)', BOOTSTRAP)
        self.assertIn('actionId.indexOf("pgn.") === 0', BOOTSTRAP)
        self.assertIn('actionId.indexOf("library.") === 0', BOOTSTRAP)
        self.assertIn('actionId.indexOf("book.") === 0', BOOTSTRAP)
        self.assertIn('function refreshStage1Surface()', BOOTSTRAP)
        self.assertIn('return Promise.resolve(global.refreshState()).then(function () {', BOOTSTRAP)
        self.assertIn('announce(uiText("Не вдалося оновити дошку.", "Could not refresh the board."));', BOOTSTRAP)
        apply_start = BOOTSTRAP.index('  function applyQueuedEvent(event, orderedStage1Refreshes)')
        apply_end = BOOTSTRAP.index('  function drainEvents()', apply_start)
        queued = BOOTSTRAP[apply_start:apply_end]
        self.assertIn('if (event.kind === "delegated")', queued)
        self.assertIn('if (actionId && !isVersion2DomainAction(actionId)) {', queued)
        self.assertIn('orderedStage1Refreshes.push(refreshStage1Surface);', queued)
        self.assertIn('return false;', queued)

    def test_book_board_repaint_is_an_awaited_focus_barrier(self) -> None:
        apply_start = BOOTSTRAP.index('  function applyQueuedEvent(event, orderedStage1Refreshes)')
        apply_end = BOOTSTRAP.index('  function drainEvents()', apply_start)
        queued = BOOTSTRAP[apply_start:apply_end]
        self.assertIn('if (event.kind === "book-board")', queued)
        self.assertIn('orderedStage1Refreshes.push(refreshStage1Surface);', queued)
        drain_start = BOOTSTRAP.index('  function drainEvents()')
        drain_end = BOOTSTRAP.index('  documentRef.addEventListener("focusin"', drain_start)
        drain = BOOTSTRAP[drain_start:drain_end]
        self.assertIn('const orderedStage1Refreshes = [];', drain)
        self.assertIn('const repaintBarrier = orderedStage1Refreshes.reduce(function (chain, refreshStage1) {', drain)
        self.assertIn('return chain.then(function () { return refreshStage1(); });', drain)
        self.assertIn('return repaintBarrier.then(function () {', drain)
        self.assertIn('return needsRefresh ? refresh(true) : undefined;', drain)

    def test_native_event_batch_restores_final_route_then_visible_explicit_focus(self) -> None:
        self.assertIn('<button id="board-launcher" type="button">', HTML)
        drain_start = BOOTSTRAP.index('  function drainEvents()')
        drain_end = BOOTSTRAP.index('  documentRef.addEventListener("focusin"', drain_start)
        drain = BOOTSTRAP[drain_start:drain_end]
        self.assertIn('const MAX_NATIVE_EVENT_BATCH = 64;', BOOTSTRAP)
        self.assertIn('events.length > MAX_NATIVE_EVENT_BATCH', drain)
        self.assertIn('let queuedTerminalFocus = "";', drain)
        self.assertIn('(event.kind === "status" || event.kind === "error")', drain)
        self.assertIn('validFocusId(event.payload.focus_target)', drain)
        self.assertIn('queuedTerminalFocus = event.payload.focus_target;', drain)
        self.assertIn('if (queuedTerminalFocus) restoreQueuedNativeFocus(queuedTerminalFocus);', drain)
        self.assertIn('return needsRefresh ? refresh(true) : undefined;', drain)
        self.assertLess(
            drain.index('if (queuedTerminalFocus) restoreQueuedNativeFocus(queuedTerminalFocus);'),
            drain.index('const repaintBarrier = orderedStage1Refreshes.reduce'),
        )

    def test_windows_composition_executes_behavioral_v2_bootstrap_smoke(self) -> None:
        test_path = "tests/js/version2_release_bootstrap_dom_test.js"
        self.assertIn("- '" + test_path + "'", WINDOWS_COMPOSITION)
        self.assertIn("node " + test_path, WINDOWS_COMPOSITION)
        self.assertIn("matrix:\n        os: [ubuntu-22.04, windows-2025]", WINDOWS_COMPOSITION)


if __name__ == "__main__":
    unittest.main()
