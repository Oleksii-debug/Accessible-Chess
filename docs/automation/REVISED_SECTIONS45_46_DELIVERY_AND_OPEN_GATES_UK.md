# Accessible Chess: canonical Sections 45–46 — verified scope and open gates

Canonical user plan: https://docs.google.com/document/d/1ITsUBFwwETRICctcOWLd6atuMcCFZg6v5-wVFumIyxE/edit (0–53).

Canonical repo: Oleksii-debug/Accessible-Chess.

Candidate PR: https://github.com/Oleksii-debug/Accessible-Chess/pull/2503

Exact ancestry: #2503 against #2499 (Sections 43–44), #2499 against #2494 (Sections 37–42). Do not merge into the old docs-only main or duplicate Settings/Board owners.

**Truth state: Section 45 ENGINEERING CANDIDATE — NOT DONE. Section 46 ENGINEERING CANDIDATE — NOT DONE.** A PR or queued CI run is not terminal evidence.

## Section 45: implemented product functions

1. One versioned, bounded, strict design profile schema for six built-in presets: Classic, Tournament, Coach, Classroom Presentation, Low Vision, High Contrast.
2. Custom profiles: up to 16, safe names, copy/Apply/Cancel/Reset/export/import, strict unknown/duplicate keys and prototype-name rejection, bounded data, no private paths or chess states stored in profile.
3. Eleven preferences: interface and board themes, piece set, text size, board scale, density, layout, coordinates, orientation, highlights, animation and sound.
4. One canonical Windows Settings writer with restart, upgrade lock, CAS-like stale revision checks; corrupt existing settings fail closed without overwriting original user bytes; legacy language/sound/volume retained.
5. Real keyboard-first studio script added to existing Stage1 Windows and Web HTML. Preview and initial hydration never invoke board commands. Explicit Apply delegates to the existing board preference handlers; sound delegates to existing sound API; no separate chess parser/rules.
6. Shared field schema on Windows and Web. Web profiles are local-only with explicit export/import for moving to another device and conservative stale-tab conflict rejection; no fabricated cloud sync.
7. Authenticated Web ASGI now delivers locally linked CSS/JS; local Windows release preflight fails if the advertised studio asset is absent, fake or duplicated.
8. Tests include six presets, 3,456 valid field combinations, malformed/prototype/oversize inputs, native restart, recovery and legacy migration, native and Web DOM, Web ASGI authentication and package asset rejection.

Files: acs/section45_design_profiles.py; acs/settings.py; acs/stage1_release_ui.py; web/section45_design_studio.js; web/index.html; web/accessible_chess_web.html; acs/web_client_http.py; acs/version2_package_preflight.py; tests/test_section45_design_profiles.py; tests/test_section45_package_studio_asset.py; tests/js/section45_design_studio_dom_test.js.

## Section 46: implemented engineering qualification

1. tests/test_section46_visual_contracts.py checks real HTML, locally served authenticated design resources, accessibility semantics, offline licenses and absence of duplicate chess authority.
2. tools/section46_visual_quality_browser.py exercises two real HTML documents x three themes x four zoom/device-scale factors x two viewport widths = **48 browser scenarios**; Playwright captures screenshots, SHA-256 manifest, focus/aria/overflow, forced-colors and reduced-motion. axe-core evaluates WCAG. This runs against local HTML fixture transport, not a live authenticated production service.
3. tools/section46_baseline_diff.py compares actual pixels/geometry only to independently human-approved baselines. Missing baselines are NOT_QUALIFIED rather than false PASS.
4. Ubuntu/Windows source-bound checks, Python native settings tests, executable Node DOM tests and Ubuntu headless screenshots/axe are configured in .github/workflows/sections45-46-design-visual-qualification.yml.
5. Borrowed MIT Tabler Core/Icons, CC0 RhosGFX and their local source/license records remain required by existing package qualification.

## Terminal blockers and evidence that may not be fabricated

- New exact-head CI must actually execute and pass, with tests/negative/recovery results and logs reviewed. Queued GitHub Actions are not green.
- Parent #2499 and upstream #2494 plus shipping integration must converge into the canonical product before Section 45/46 can be declared integrated.
- Physical native Windows WebView2/WinForms/NVDA/UIA and DPI/real keyboard-copy behavior need actual executable readback, not just mocked DOM.
- Independent sighted visual/usability acceptance and approved screenshot baselines have **not** been supplied. Automated screenshots are NOT an equivalent.
- Full realistic library/media/teacher/game-load performance and shipping artifact release/package readback remain outstanding.
- Only once all valid acceptance conditions hold may the live GitHub ledger and authoritative Google Drive plan be marked terminal DONE.

**HUMAN_TESTED=NO; NVDA_VERIFIED=NO; APPROVED_BASELINES=NO; REAL_PRODUCT_PERFORMANCE_VERIFIED=NO; TERMINAL_DONE=NO.**
