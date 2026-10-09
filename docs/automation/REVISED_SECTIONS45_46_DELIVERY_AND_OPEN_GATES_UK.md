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


## Integration hardening added after original delivery note

- Re-converged Section 45/46 branch on live Sections 43–44 source by two-parent history-preserving merge b73b3ac452ade659684a9406a2152e9014cde3e3. Preserved upstream Section 42 renderer, Web ASGI allowlist, corpus and Section 43–44 settings/layout authorities; candidate-to-parent compare was ahead-only with zero behind. Upstream parent may advance again, so refresh exact ancestry at terminal acceptance.
- Real Web board now consumes the same validated presentation-only profile through its already-shipped renderBoard() function: 64 canonical read-only cells, theme, RhosGFX/letters/Unicode, orientation, coordinates, board size, highlighting and animation. The canonical snapshot/FEN/MoveList never changes. Existing overlay authority retained.
- Added interactive 64-square first-party decorative preview, marked aria-hidden; no second playable board, no duplicate position state or FEN parser.
- Windows and Web profile inputs reject duplicate JSON keys, malicious prototype names and unknown fields. Damaged Web settings bytes are preserved until owner explicitly chooses Reset then Apply; stale-tab conflict is rejected. Native settings remain upgrade-locked with exact revision.
- Actual executable source-bound JavaScript smoke run on the merged branch passed ten design-studio DOM groups and an independent real Web renderBoard() VM integration test: themes/pieces/orientation, accessibility labels, focus, arrow-key navigation, invalid-values fallback and immutable canonical snapshot. These runs are LOCAL CONNECTOR-EXECUTED SCRIPT EVIDENCE, **not GitHub Actions green, physical Windows or full application acceptance**.
- Section46 browser qualification now includes keyboard Enter/Tab, Ctrl+A native text selection, long translation reflow, actual CSS zoom and device DPI, six preset preview redraw, source-bound screenshot SHA-256, local synthetic Web 64-cell fixture, plus real Stage1 keymap and engine-start dialogs. The planned matrix is 48 primary HTML combinations + 6 modal screenshots; all are unapproved until captured and reviewed.
- Screenshot diff no longer allocates Python boolean arrays per pixel: bounded Pillow histogram is used. Approval requires reviewer identity, UTC review date, exact baseline source SHA and both baseline/current PNG SHA-256. Missing/falsified evidence fails closed.
- A bilingual Windows/NVDA/sighted-review protocol is at docs/automation/SECTION46_WINDOWS_NVDA_SIGHTED_VISUAL_REVIEW_PROTOCOL_UK_EN.md. This is a protocol, **not completed human acceptance**.
- GitHub CI uses one cancel-in-progress group for the current branch to discard stale queued duplicate runs. At this note the hosted CI may still be queued; do not infer pass from the candidate.
- New actual-web reflow fix removes eight fixed 2.7rem minimum grid columns that otherwise could overflow narrow/high-zoom screens.

### Exact residual blockers, not optional DONE substitutes

1. Exact current-head Ubuntu/Windows jobs must truly finish SUCCESS and their logs/test counts/negative checks be inspected.
2. Real Windows/WebView2/WinForms UIA, native focus/editing/copy, NVDA, OS DPI and force-color qualification must execute on a user-consumable Windows artifact.
3. Visually approved screenshots and independent sighted tester evaluation of all real modules are not yet recorded. A captured browser PNG is not sighted approval.
4. Large real user Library/media/engine performance must be qualified, including restart and access to actual Product-backed routes.
5. Sections 41–44 ancestor candidates and Sections 45–46 must converge into one shipping Product; post-integration exact-source readback and license verification are mandatory.

**SECTION45_TERMINAL_DONE=NO. SECTION46_TERMINAL_DONE=NO.** These are engineering advancements with verifiable scope, not certified terminal closures.


## 2026-10-09 Section 45.5–45.6 portability/recovery checkpoint — NOT TERMINAL DONE

Source branch: `feature/section45-46-design-studio-qa-20261008`; protected PR #2503 remains DRAFT and OPEN, not the current shipping `main`.

- Web profile decoder now treats structural JSON characters inside quoted strings as data; duplicate object keys still fail closed at any depth. Portable custom names containing unmatched `{`, `[`, `}`, `]` no longer spuriously fail import/restart. Commit `8b5a4695bf0bffd92d17d5098b3500a404d83c85`.
- Web import, export and local persistence now enforce the same 16,384-byte UTF-8 payload bound used by Python, rather than JavaScript UTF-16 code-unit length. Same source commit.
- Native Python and existing real-studio Web DOM source tests gained portable-profile punctuation/restart regression cases. Commits `2c27a5278df63b331c3b046bd0b4c07eb99d7e0e` and `09a87405cc46e562ab856a0cd8bfc2d8dfa174b7`.
- Existing actual Web `renderBoard(snapshot)` integration test gained 3,456 combinations from six preset-palette selections x four UI-theme values x three piece sets x six zoom values x both orientations x both densities x both layout selections. Every scenario asserts 64 cells, canonical per-square accessibility label, board/piece theme, zoom and coordinates plus invariant canonical snapshot. Commit `a27842112a85a99ae411235761caacfb6d66d2f0`. This is **source test authored, not yet an observed CI PASS**.
- Exact GitHub file-blob readback confirms four changed branch files. No chess move, FEN, GameTree, sound engine, student record, public release or protected Section 45.1–45.4 implementation was rewritten.
- The restricted `fetch_commit_workflow_runs` GitHub view returned no PR-triggered workflow runs for the new branch head; no exact-head Ubuntu/Windows success can be claimed. Local container Git clone is blocked by DNS resolution. Native Windows/NVDA/OS-DPI, approved sighted baselines, full-module performance, correct shipping-main convergence and artifact restart validation remain unqualified.

Closure authority: 45.1–45.4 stay protected/locked; 45.5–45.6 improved but PARTIAL; SECTION 45 = **NOT DONE**, never promote to DONE on a branch diff or staged test alone.

- Additional isolated, locally executed Node smoke for the extracted JSON key scanner and UTF-8 byte-count checks: **17/17 assertions PASS**, including unbalanced braces/brackets inside quoted names, duplicate keys, escaped aliases and malformed nesting. This does not substitute for executing the full source-tree Web DOM/Python/Windows tests.
- **main→candidate GitHub compare (read-only)**: `status=diverged`, candidate ahead **1966** and behind **313** commits (GitHub comparison only provided a capped 300 changed-file list). **Do not merge PR #2503 directly** or call its authored UI code shipping-main integrated; rebase/convergence needs conflict-safe preservation of main's Section 45.1–45.4 settings and Board owners. This reinforces Section 45 NOT DONE.
