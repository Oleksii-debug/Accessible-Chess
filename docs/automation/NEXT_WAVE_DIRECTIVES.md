# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0001
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T00:00:00+03:00
SNAPSHOT_SEMANTICS: Workers already running before the effective wave must ignore this directive until their next invocation.

## DEV1 — DIRECTIVE 0001
STATUS: accepted and integrated; no speculative Product churn.
NEXT WORK: remain in evidence/regression mode unless a concrete UI/accessibility/action-routing regression is returned by integration or audit. Re-check exact integration behavior for native menu routing, editable keyboard safety, localized keymap search, board action semantics, focus continuity, and live-region discipline. If no regression is proven, do not modify Product; produce targeted regression evidence or dependency notes only.

## DEV2 — DIRECTIVE 0001
STATUS: active/in-progress at coordinator snapshot; current run is not interrupted.
NEXT WORK: finish the current canonical core package and publish terminal handoff with exact final SHA and exact CI. Preserve authoritative empty-square attackers() = all canonical controllers. Preserve supported abbreviated FEN compatibility unless a newer authoritative contract explicitly changes it. Complete atomicity/invariant proof including en-passant provenance and failure-without-partial-mutation. Do not request intake until READY_FOR_INTEGRATION=YES with exact evidence.

## DEV3 — DIRECTIVE 0001
STATUS: final Stage1 backend package accepted and already integrated into e24ff85ff9a6ad3ea19d33f7035526c7bcdf2c8e.
NEXT WORK: do not duplicate already integrated UCI/lifecycle/takeback/sound hardening. Use the next wave for regression/evidence on top of the live integration head where safe: engine close-during-think, stale result suppression, real Stockfish option restoration, takeback/history clock alignment and cross-lane interaction with DEV2 changes. Only modify Product if a new concrete DEV3-owned defect is reproduced.

## DEV4 — DIRECTIVE 0001
STATUS: terminal READY package at a4209d005ea0a1476f8eafb4822f4d39ac50ee5a, not yet integrated.
NEXT WORK: prepare DEV5-safe intake evidence against the live integration head, explicitly reconciling acs/stage1_release_ui.py and web/stage1_board_actions.js with accepted DEV1 semantics. Do not overwrite accepted DEV1 board-bridge behavior. Provide exact overlap analysis, intended final file semantics, and observable exact-head CI/package-preflight evidence. Keep Nuitka compilation report as CI-only evidence, never user-package content. Do not create or publish a Windows candidate ZIP yet.

## DEV5 — DIRECTIVE 0001
Continue as Coordinator/Integrator/QA/General Fixer. At each wave start snapshot only terminal evidence available before the wave. Ignore unfinished current runs. Preserve e24ff85ff9a6ad3ea19d33f7035526c7bcdf2c8e as the known-green integration baseline until another package is proven intake-safe. Next priority: DEV4 reconciliation/validation, then DEV2 intake once terminal exact evidence exists. After every accepted intake, rerun exact integration gates and update the ledger. Never merge PR #54 or frozen release refs. Never reuse an old rejected ZIP. NVDA_VERIFIED remains NO until Oleksii personally verifies an exact fresh candidate after the full Windows machine chain.
