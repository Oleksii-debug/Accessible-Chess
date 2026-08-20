# Accessible Chess — Work Master Current

Updated: `2026-08-20T09:07:25Z`

## Recovery pointer

- `CURRENT_BRANCH`: `completion/full-product-critical-path-20260819`
- `START_SHA`: `588058634b378793b3c9aa0dca113af6b8a2dc8f`
- `CURRENT_REMOTE_SHA`: `05ca9e8213f8690172aaa767ec7d45fa96e6c6ab`
- `LAST_SAFE_SHA`: `05ca9e8213f8690172aaa767ec7d45fa96e6c6ab`
- `INTEGRATION_SHA`: `e8cd992d306975955784118364ce950963133d7e`
- `QA_SHA`: `07971835cb8fc294996165e577913ed350ae9f0e`
- `RESEARCH_SHA`: `0213f54f3f36fb30379f95c9979aea3a1cc41481`
- `COMPLETION_SHA`: `05ca9e8213f8690172aaa767ec7d45fa96e6c6ab`
- `COMPETITOR_EVIDENCE_BRANCH`: `research/competitor-interaction-lab-20260820`
- `COMPETITOR_EVIDENCE_SHA`: `0213f54f3f36fb30379f95c9979aea3a1cc41481`
- `CURRENT_STAGE1_STATE`: `BLOCKED — Issues #14 and #22 open; classification does not authorize a product-source change`
- `CURRENT_OWNER`: `WORK_MASTER — completion/shared-core/spec/test hardening only; Windows QA remains QA-owned`
- `CURRENT_PRIORITY`: `Isolated shared-core PGN/GameTree corruption and recovery hardening`
- `CURRENT_SUBSYSTEM`: complete lossy-warning classification and PGN token correctness
- `STATUS`: `WIP_SAFE`
- `NVDA_VERIFIED`: `NO`

All four branch heads were verified live with `git ls-remote` on 2026-08-20. GitHub technical truth wins over stale handoffs.

## Live control state

- Issue #14 is open. Strict Windows run `32220453450` on QA SHA `07971835...` and product SHA `e8cd992...` proved the real document, one unique original strict-valid Move Edit, legal `e4`, and invalid `e9`; it then failed because Ctrl+A/Ctrl+C left clipboard sentinel `__sentinel__` unchanged.
- Issue #22 is open and remains the authoritative human rejection/acceptance gate.
- Issue #45 is open and preserves the two-role Work/Audit model and the complete product architecture.
- Stage1 release lineage remains frozen and narrow. The old rejected ZIP is forbidden. No new candidate ZIP is authorized here.
- Stage1 Windows QA/harness ownership remains with QA. Work owns product/core/contracts on the isolated completion branch and must not modify QA-owned strict workflows without explicit ownership transfer.
- Draft PR #52 remains open at the separate canonical-interaction branch. The completion branch is not folded into that PR.
- Exact retained evidence and ownership are recorded in `docs/work/STAGE1_EXACT_BLOCKER_HANDOFF_2026-08-20.md`.

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
- Work Core CI `32346710032` on pre-recovery head `5880586`: raw core passed; full pytest remained `872 passed`, `1437` subtests, and two failures.
- Local behavioral reclassification at `e4b8751`: the stale direct `actionByChord(...)` literal expectation was replaced by proof that `onBoardKey` awaits the central resolver and dispatches its returned `actionId`. That contract passes. Two unweakened PRODUCT failures remain: central rank/file actions are absent and Help omits their live bindings.
- Local PGN/GameTree focused verification after `8178e45`: `66 passed`, `86 subtests passed`. A malformed nested RAV can no longer promote post-result child moves or nested branches into the parent mainline.
- Local structured-recovery verification after `19a94fa`: `69 passed`, `86 subtests passed`. Quarantined nested-RAV tails are `DAMAGED`, block serializer/atomic save with stable `unresolved_recovery`, and roll ACSDB import back as a recorded failed attempt.
- Current broad unittest at this checkpoint: `797/797` passed; compileall and `git diff --check` passed.
- Local all-lossy-warning verification after `05ca9e8`: `72 passed`, `96 subtests passed`; broad unittest `800/800` passed. Duplicate tags, unterminated structures, unmatched/orphan RAVs, orphan annotations, dropped move numbers and root post-result tails all produce structured blocking recovery, while fully preserved Result warnings remain exportable.
- Competitor lab run `32342624286`: five jobs completed successfully and published compact evidence to `0213f54...`.

## Known failures and blockers

1. `test_rank_and_file_navigation_are_exposed_as_remappable_actions`: PRODUCT — static fallback JSON advertises 16 rank/file actions that the central runtime Action Registry cannot resolve.
2. `test_help_is_generated_from_live_rank_and_file_bindings`: PRODUCT — Help omits the live rank/file bindings.
3. Strict Windows run `32220453450`: BLOCKED / NO PRODUCT ATTRIBUTION YET at native Ctrl+A/Ctrl+C; QA owns the focused evidence pass.
4. Canonical ChessBase CBG move/variation/annotation decoding remains `UNSUPPORTED`; real licensed fixture corpus is absent; CBV/CBF/2CBH/CBONE content remains `UNSUPPORTED`.
5. Full licensed ChessBase/Fritz interactive/NVDA execution remains unavailable. Robot evidence must not be labelled `NVDA_VERIFIED`.
6. Attached symbolic NAG suffixes such as `Nc3!?` are still embedded in `MoveNode.san` instead of the canonical `nags` collection; attached numeric NAGs such as `e4$1` are also not tokenized correctly. This blocks a trustworthy SAN/annotation and legality-linking boundary.

## Current ownership and invariants

- Preserve one canonical Position/Move/GameTree/application state.
- Keep Move, Teacher Pointer, Position Editor, Annotation, Student Hover and Student Selection as separate command families.
- Universal Windows editing semantics have priority inside editable/selectable controls.
- User-facing Help must be generated from the live Action Registry/keymap; menus remain the authoritative discovery path.
- Do not freeze Database, PGN/GameTree, Books, Engine, Teacher/Classroom, menu, keymap or Help UX before reconciling the verified competitor evidence.
- Research decisions require one of: `ADOPT_AS_DEFAULT`, `ADOPT_CONTEXTUALLY`, `COMPAT_PROFILE_ONLY`, `INSPIRE_BUT_IMPROVE`, `REJECT_ACCESSIBILITY_DEFECT`, `INSUFFICIENT_EVIDENCE`.

## Next exact action

Checkpoint complete lossy-warning classification. Then canonicalize attached symbolic and numeric NAG tokenization without accepting malformed annotation syntax: separate SAN from `!`, `?`, `!!`, `??`, `!?`, `?!` and `$digits`, preserve order, fail closed on invalid `$` forms, and prove nested/multi-game round-trip plus identity behavior. Do not change the Stage 1 product or QA line. If Issue #14 transfers a PRODUCT fix, stop shared-core work and make the minimum central rank/file Action Registry plus live-Help repair before returning the exact SHA to QA.
