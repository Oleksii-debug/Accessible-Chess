# Accessible Chess — Work Master Current

Updated: `2026-08-20T08:25:44Z`

## Recovery pointer

- `CURRENT_BRANCH`: `completion/full-product-critical-path-20260819`
- `START_SHA`: `588058634b378793b3c9aa0dca113af6b8a2dc8f`
- `CURRENT_REMOTE_SHA`: `588058634b378793b3c9aa0dca113af6b8a2dc8f`
- `LAST_SAFE_SHA`: `588058634b378793b3c9aa0dca113af6b8a2dc8f`
- `INTEGRATION_SHA`: `e8cd992d306975955784118364ce950963133d7e`
- `QA_SHA`: `07971835cb8fc294996165e577913ed350ae9f0e`
- `RESEARCH_SHA`: `0213f54f3f36fb30379f95c9979aea3a1cc41481`
- `COMPLETION_SHA`: `588058634b378793b3c9aa0dca113af6b8a2dc8f`
- `COMPETITOR_EVIDENCE_BRANCH`: `research/competitor-interaction-lab-20260820`
- `COMPETITOR_EVIDENCE_SHA`: `0213f54f3f36fb30379f95c9979aea3a1cc41481`
- `CURRENT_STAGE1_STATE`: `BLOCKED — Issues #14 and #22 open; classification does not authorize a product-source change`
- `CURRENT_OWNER`: `WORK_MASTER — completion/shared-core/spec/test hardening only; Windows QA remains QA-owned`
- `CURRENT_PRIORITY`: `Restore the lost competitor-derived interaction contract from durable evidence`
- `CURRENT_SUBSYSTEM`: competitor-derived interaction contracts before user-facing UX freeze
- `STATUS`: `WIP_SAFE`
- `NVDA_VERIFIED`: `NO`

All four branch heads were verified live with `git ls-remote` on 2026-08-20. GitHub technical truth wins over stale handoffs.

## Live control state

- Issue #14 is open. Its latest strict Windows chain is run `32220453450` on QA SHA `07971835...` and product SHA `e8cd992...`; it is not a fully green release chain.
- Issue #22 is open and remains the authoritative human rejection/acceptance gate.
- Issue #45 is open and preserves the two-role Work/Audit model and the complete product architecture.
- Stage1 release lineage remains frozen and narrow. The old rejected ZIP is forbidden. No new candidate ZIP is authorized here.
- Stage1 Windows QA/harness ownership remains with QA. Work owns product/core/contracts on the isolated completion branch and must not modify QA-owned strict workflows without explicit ownership transfer.
- Draft PR #52 remains open at the separate canonical-interaction branch. The completion branch is not folded into that PR.

## Competitor lab evidence to consume, not repeat

- Exact evidence head: `0213f54f3f36fb30379f95c9979aea3a1cc41481`.
- Main practical run: `32342624286`; all five jobs completed successfully, including the compact evidence publisher.
- ChessBase Reader 2017: real Windows install/UIA/keyboard robot evidence exists; use domain patterns, not its weak UIA semantics as an accessibility model. Evidence is robot-only, never NVDA verification.
- Scid 5.2 and ChessX 1.6.10: practical execution was not reached because the selected SourceForge URLs returned HTML rather than the expected binaries. Classify as download/lab defects and keep practical execution pending.
- Lichess/Chess.com: public semantic/keyboard evidence exists. Lichess blind-mode control was found, but activation was not proven.
- SK Chess: documentation-confirmed accessibility-first conventions; no safe executable run was performed.
- Do not merge the research branch wholesale. Do not copy competitor installers, fake download artifacts, or incidental screenshots into product history.

## Last safe product result

Commit `11b92a1e827bf66f8075ac7f3571ae20b908c1af` added integrity-verified bounded ChessBase evidence windows:

- maximum 1024 CBH records per call;
- required read-only CBG/CBP/CBT companions;
- bounded exact payload/record reads;
- pre/post SHA-256 snapshots of the complete source family;
- per-record fault isolation;
- fail-closed `decoder_available=false` and `safe_to_import=false`.

`STAGE1_RELEASE_IMPACT=NONE`; `DATA_MIGRATION_IMPACT=NONE`.

## Tests and CI

- Local at `11b92a1`: ChessBase `127/127`; architecture `9/9`; broad unittest `793/793` with one existing skip; `git diff --check` and compileall passed.
- Work Core CI `32301688378` on exact `11b92a1`: raw core `793/793` passed.
- Unweakened pytest at `11b92a1`: `872` passed plus `1437` subtests, with exactly two unchanged Stage1 failures in `tests/test_board_rank_file_remapping_ui.py`.
- Competitor lab run `32342624286`: five jobs completed successfully and published compact evidence to `0213f54...`.

## Known failures and blockers

1. `test_board_dispatch_uses_action_ids_instead_of_hardcoded_digit_shortcuts`: likely stale static/literal expectation; preserve canonical action dispatch and convert only with behavioral proof.
2. `test_help_is_generated_from_live_rank_and_file_bindings`: genuine discoverability defect; Help must derive from the live Action Registry/keymap.
3. Canonical ChessBase CBG move/variation/annotation decoding remains `UNSUPPORTED`; real licensed fixture corpus is absent; CBV/CBF/2CBH/CBONE content remains `UNSUPPORTED`.
4. Full licensed ChessBase/Fritz interactive/NVDA execution remains unavailable. Robot evidence must not be labelled `NVDA_VERIFIED`.

## Current ownership and invariants

- Preserve one canonical Position/Move/GameTree/application state.
- Keep Move, Teacher Pointer, Position Editor, Annotation, Student Hover and Student Selection as separate command families.
- Universal Windows editing semantics have priority inside editable/selectable controls.
- User-facing Help must be generated from the live Action Registry/keymap; menus remain the authoritative discovery path.
- Do not freeze Database, PGN/GameTree, Books, Engine, Teacher/Classroom, menu, keymap or Help UX before reconciling the verified competitor evidence.
- Research decisions require one of: `ADOPT_AS_DEFAULT`, `ADOPT_CONTEXTUALLY`, `COMPAT_PROFILE_ONLY`, `INSPIRE_BUT_IMPROVE`, `REJECT_ACCESSIBILITY_DEFECT`, `INSUFFICIENT_EVIDENCE`.

## Next exact action

Read the exact research tree and compact evidence at `0213f54...`, then create and immediately checkpoint `docs/ux/COMPETITOR_DERIVED_INTERACTION_CONTRACTS.md`. The contract must cover Playing, Engine Play, Analysis, PGN/GameTree, Multi-game PGN, Database, Search, Opening Reference, Opening Book, Position Setup, Books, Training, Teacher/Classroom, Menus, Help and Keymap with focus entry/escape/restoration, accessible projection, canonical action, shortcut policy, error recovery, evidence and decision classification. After that, inspect the completion branch Action Registry/keymap/Help and implement exactly one Stage1-legal evidence-backed atomic fix.
