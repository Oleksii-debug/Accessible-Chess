# Accessible Chess — canonical Sections 43 and 44 implementation evidence

Source plan: [Official Sections 0–53, 2026-10-08](https://docs.google.com/document/d/1ITsUBFwwETRICctcOWLd6atuMcCFZg6v5-wVFumIyxE/edit).
Status: **IMPLEMENTING / NOT TERMINAL DONE**. This is not a substitute for required
actual Windows/WebView2/owner-final acceptance, nor a claim that 37–42 is closed.

Current source integration: [PR #2499](https://github.com/Oleksii-debug/Accessible-Chess/pull/2499),
stacked on active [PR #2494](https://github.com/Oleksii-debug/Accessible-Chess/pull/2494).
Do not merge this feature into docs-only `main` while shipping ancestry remains separate.

## S43 — Windows workspace and navigation

- 43.1 Professional shared product chrome: **IMPLEMENTED SLICE**. Existing
  `web/index.html` / `web/assets/accessible_chess_design.css` using Section-41 local
  Tabler-provenance assets and design variables. One native WinForms/WebView2 product.
- 43.2 Chess Workspace: **IMPLEMENTED SLICE**. Existing board, move history,
  Stockfish, position entry, live regions and engine controls use responsive
  cards/columns, not duplicate chess/analysis state. Board and native field IDs unchanged.
- 43.3 Per-workspace layout and recovery: **IMPLEMENTED SLICE**. Twelve
  preexisting Windows panels have native buttons for expand/collapse and height,
  globally selectable density and column flow, restore-layout action and
  versioned bounded layout-only storage. Existing V2 module navigation gets its
  own mode selector (comfortable/compact/reading) with per-route restart
  persistence; dynamic services retain their DOM ownership. **Windows persistence
  now uses the existing atomic, upgrade-locked Settings writer via validated
  `get_presentation_layout`/`save_presentation_layout` API methods.** Browser
  localStorage is a fallback only, not treated as durable in pywebview private mode.
- 43.4 Menus/dialogs/import-export/progress/help: **PARTIAL**. Shared CSS
  styles existing native controls/forms/status; no signed native-menu rewrite or
  confirmed complete Windows dialog-by-dialog aesthetic qualification.
- 43.5 Keyboard/NVDA/selection/error: **PARTIAL**. Reuses the established
  keyboard owner, semantic HTML and selectable text. New layout control focus,
  restart and corrupt-profile cases tested in JS harness. Actual Windows UIA
  and NVDA acceptance have not been verified.
- 43.6 Tests: **PARTIAL**. Repo-local V8 execution of canonical inline UI and
  product-mode snippets passed; source changes also include a new five-case
  native `Settings` unit suite for actual durable restart, stale writers,
  upgrade lock, invalid payloads and no-chess-data side effects. Live Actions
  Ubuntu/Windows exact-SHA qualification remains queued, not SUCCESS. No screenshot/DPI/zoom
  pixel/real WebView2 run has completed for this new source.

## S44 — shared style for actual services

- 44.1 Books: **IMPLEMENTED SLICE**. Actual Book metadata/author, reading
  sections, semantic navigation, bookmark and toolbar restyled via existing
  Book semantic DOM. Genuine licensed cover thumbnails are not invented.
- 44.2 Library/PGN: **IMPLEMENTED SLICE**. Existing listbox, search filters,
  source badges, selected rows, tables, PGN/GameTree semantic navigation and
  import/progress controls receive shared visual treatment.
- 44.3 Training: **IMPLEMENTED SLICE**. Existing task answer, progress stats,
  solution tree, engine evaluation/progress and text equivalents emphasized;
  no second analysis/AI Coach authority.
- 44.4 Teacher/Classes: **IMPLEMENTED SLICE**. Existing teaching boards,
  accessibility-labeled squares, class lists and education detail cards styled.
  No invented user permission semantics or background media takeover.
- 44.5 Web/Online/Spectator/Media: **IMPLEMENTED SLICE**. Original Web routes
  use shared responsive card-like layout for board, route text, status,
  command and video components. Media/YouTube native controls are not covered.
- 44.6 Tests: **PARTIAL**. Added exact-source cross-OS workflow that executes
  9 custom runtime/static contract groups plus six preexisting Books/Training,
  Library, PGN, Teacher, Classroom and Education DOM test scripts and
  preexisting Web Python tests. CI is not yet qualified; module-specific
  performance, real multi-device visuals and full keyboard/zoom acceptance
  remain open.

## Local executed JS evidence

Nine source-bound groups passed in a V8 harness that loaded live GitHub
blob bytes and executed the actual `web/index.html` inline layout script and
extracted `web/version2_final_product_bootstrap.js` product-mode authority,
including collapsed focus, restart/reset, invalid/oversized storage,
previously-hidden child preservation, route-specific mode persistence, bilingual
options, current service/CSS selector wiring, simulated private-WebView native restart, and WCAG AA text/action contrast checks for light, dark and high-contrast modes. This is not a claim that
Node GitHub Actions or genuine Windows UI Automation ran.

CI workflow: `.github/workflows/sections43-44-workspace-qualification.yml`.
Native Settings tests: `tests/test_sections43_44_native_layout_persistence.py`.
Independent manual checklist: `docs/automation/SECTIONS43_44_WINDOWS_NVDA_READBACK_UK_EN.md`.
Tests: `tests/js/sections43_44_workspace_contract_test.js`.

## Terminal closure rule

Before changing Section 43 and 44 to DONE: settle the live PR into the
canonical product shipping/integration lineage without losing active 37–42
source; obtain available exact commit CI qualification with no known
unrepaired failures; run the Windows UIA/keyboard/DPI/zoom and representative
per-module render/readback gates; check genuine licensing/asset and
accessibility boundaries. Manual owner NVDA approval is the **final product**
gate per AGENTS.md v3 and must not falsely block intermediate source
qualification, but a known internal failure or absent feature may not be
silently reclassified as PASS.

## Integration reconciliation — 2026-10-08, PR #2499

Created genuine two-parent merge commit `e77a5abf8a2d5397bebf6664326f52cd5f961c79` from the existing Sections 43–44 feature head `2be937d7230f6fbe2cf45c88ec998baddcb255da` and the then-current canonical Section41/42 ancestor `1096ddb3e3bf33c9397dbe6cc791967f22212305` (not a forced rewrite). Verified by source blob comparison that the eight non-overlapping Section43/44 files were left intact, while the **additive** Stage1 HTML IIFE (8,666 characters) and Section43/44 CSS styles (13,568 characters) were applied to the upstream source without deleting the newer Section42 licensed-piece renderer, low-power/forced-colors fallback, live copyable annotations, or the WCAG contrast correction.

Merge readback: PR #2499 remained open on its existing canonical integration lineage. Both inline Stage1 scripts passed V8 syntax parsing; 12-panel Section43 Workspace function was then actually executed in a V8 DOM fixture. Checked panel-fold focus retention, saved-state restoration in the English-language workspace, and reset to expanded/default layout. All assertions passed. The worker's original `tests/js/sections43_44_workspace_contract_test.js` and Python native Settings tests remain part of this same PR, without duplicate authority.

**Do not mistake this for terminal Section43 or 44 DONE.** Newer upstream worker commits may advance the #2494 base; confirm mergeability and exact-source readback at the final merge. Required unverified evidence: real Windows executable workspace route and UIA/NVDA keyboard recovery, DPI/zoom/screenshot baselines, complete module journeys, exact-head CI, and final owner acceptance. This note records real *integration progress* only.
