# Codex current state — 2026-08-21

## Repository and release lineage

Repository: `Oleksii-debug/Accessible-Chess`

Frozen Stage1 Product/release SHA:
`656e8ec311e364e6e54a30504fd30a4aaff586f9`

Frozen tree:
`bfbf3c5ae86b141bc3916c63e9613c25342e1af8`

At handoff, both:
- `integration/accessible-chess-next`
- `integration/stage1-product-candidate-20260820`

remain on the frozen Product SHA. Do not move them casually.

Human NVDA state: `NVDA_VERIFIED=NO`.
Old human-rejected ZIP: forbidden.
Fresh accepted candidate ZIP: none.

## Latest Product development line

Developer saturation branch:
`dev/stage1-saturation-hardening-20260821`

PR: #54 `Stage1 saturation hardening — 2026-08-21`
State at handoff: OPEN, DRAFT, NOT MERGED.

Exact latest Developer head discovered by Audit:
`498989b4fda33e6529e29c9704fb4c724d0d3455`

The Codex bootstrap branch `codex/autonomous-20260821` was created directly from that exact head, then documentation-only bootstrap commits were added.

Important: Drive handoff/checkpoint text lagged the live repository. GitHub live state is authoritative.

## What the saturation work already achieved

The branch refactored the large Stage1 release/keymap modules into facades plus `*_core.py`, while tests proved the extracted core blobs byte-identical to the frozen implementation. It added board-action integration, central action routing, native-menu routing work, resource/reinjection checks, long-history stress tests and stronger CI.

Previously green exact checkpoints proved:
- byte-identical extracted frozen core blobs;
- fresh-process cold imports and MRO/import-surface invariants;
- resource ordering: release bootstrap before board-action bridge;
- fail-closed missing resource behavior;
- 560/560 unittest at an earlier checkpoint;
- 638 pytest + 524 subtests at an earlier checkpoint;
- official Stockfish 18 UCI/bestmove/MultiPV5 smoke;
- complete Stage1 diagnostic.

The earlier audit claim that sound settings UI was missing was a false positive. Frozen `656e8ec...` already exposes accessible persisted sound enable, bounded volume and real preview controls for the 9-event sound pack via `web/stage1_release_bootstrap.js`.

## CRITICAL: exact latest head is currently red

Do NOT treat the latest Developer head as green merely because older checkpoints were green.

Exact head `498989b4...` produced two latest failing PR workflows:

1. Stage1 Saturation Hardening CI
- run `32461361192`
- job `96708776708`
- conclusion: FAILURE
- failure: architecture/refactor gate
- exact failing test: `tests.test_stage1_saturation_refactor_contract.Stage1SaturationRefactorContractTests.test_run_release_window_executes_real_bootstrap_then_board_bridge`
- error: `Stage1NativeMenuActionProxy(api)` rejects the test double because it lacks callable `dispatch_action`, raising `TypeError: native menu API must expose dispatch_action`.
- all preceding ancestry/diff/compile/JS reinjection checks passed; later saturation stages were skipped because the gate failed.

2. UI Semantic Gate
- run `32461361267`
- job `96708777091`
- conclusion: FAILURE
- semantic/accessibility/diagnostic and history-analysis-sound blocks passed before the failure.
- exact failing test: `tests/test_ui_keymap_editor.py::test_rows_are_searchable_localized_and_expose_context_and_defaults`
- query `перейти` now returns `history.go_to_move` plus 16 board rank/file rows, because the newly localized board rank/file text also contains the matching word. This is a search-contract regression or stale expectation; determine the intended UX and fix root cause/test precisely without weakening localization/search semantics.
- block result before stop: 1 failed, 105 passed, 23 subtests passed.

These two failures are the immediate highest-priority Product/CI closure items.

## Windows strict release history

Latest independently verified strict Windows run remains:
- run `32411492785`
- job `96562722877`
- frozen Product SHA `656e8ec...`
- classification: `C — INCONCLUSIVE / QA synchronization-and-observability boundary`

Steps 1–13 passed. Step 14 proved native key delivery with End baseline and Backspace `e9 -> e`, then the QA helper failed while restoring `e9` through UIA ValuePattern before decisive native Ctrl+A/Ctrl+C proof. This did NOT establish a Product Ctrl+A or Ctrl+C defect. Steps 15–18 were skipped. No candidate ZIP was produced.

QA branch last known handoff line:
`qa/windows-current-integration-candidate-20260815`
with bounded restore/reacquisition work. Re-read the live branch and Actions before changing any QA code; do not duplicate strict runs (WIP=1).

## Canonical future product

The complete Windows product is defined in `docs/CANONICAL_PRODUCT_VISION_UA.md` and `docs/TECHNICAL_ROADMAP.md`.

Roadmap dependency order after Stage1 release work:
1. canonical core/contracts;
2. PGN + full GameTree round-trip;
3. ACSDB / Library / Search;
4. ChessBase-family compatibility adapters with capability/import reports;
5. Books / structured diagrams / training;
6. Teacher/Classroom, visual board, keyboard visual pointer, student reverse channel;
7. courses / assignments / progress / session records;
8. online/remote lessons/shared sessions.

There are existing branches containing future/core/data/classroom work. Reuse only after auditing; do not assume an old branch is correct merely because it exists.

## Handoff objective

First restore the exact latest Stage1 saturation head to green without weakening any gate. Then close remaining machine-verifiable Stage1/release work. If only human NVDA acceptance remains, keep productive momentum by advancing the canonical future roadmap in isolated branches/worktrees, without contaminating the frozen Stage1 release lineage.