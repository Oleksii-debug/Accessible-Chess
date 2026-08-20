# Accessible Chess — Work Master Current

Updated: `2026-08-20T09:52:00Z`

## Recovery pointer

- `CURRENT_BRANCH`: `completion/full-product-critical-path-20260819`
- `START_SHA`: `588058634b378793b3c9aa0dca113af6b8a2dc8f`
- `CURRENT_REMOTE_SHA`: `77a6640dcc177c0c21a3c6b64ff1324ad0ff0ca5`
- `LAST_SAFE_SHA`: `77a6640dcc177c0c21a3c6b64ff1324ad0ff0ca5`
- `INTEGRATION_SHA`: `e8cd992d306975955784118364ce950963133d7e`
- `QA_SHA`: `07971835cb8fc294996165e577913ed350ae9f0e`
- `RESEARCH_SHA`: `0213f54f3f36fb30379f95c9979aea3a1cc41481`
- `COMPLETION_SHA`: `77a6640dcc177c0c21a3c6b64ff1324ad0ff0ca5`
- `COMPETITOR_EVIDENCE_BRANCH`: `research/competitor-interaction-lab-20260820`
- `COMPETITOR_EVIDENCE_SHA`: `0213f54f3f36fb30379f95c9979aea3a1cc41481`
- `CURRENT_STAGE1_STATE`: `BLOCKED — Issues #14 and #22 open; classification does not authorize a product-source change`
- `CURRENT_OWNER`: `WORK_MASTER — completion/shared-core/spec/test hardening only; Windows QA remains QA-owned`
- `CURRENT_PRIORITY`: `Isolated shared-core PGN/GameTree corruption and recovery hardening`
- `CURRENT_SUBSYSTEM`: non-destructive GameTree legality and immutable position links
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
- Local attached-NAG verification after `a7a0150`: broad unittest `802/802` passed; focused `57 tests`, `58 subtests` passed. Attached symbolic/numeric annotations are separated from SAN, preserve mixed order, round-trip through nested RAVs and share identity with spaced equivalents; malformed forms are `invalid_annotation` blockers.
- Local canonical-token verification after `7406890`: broad unittest `803/803` passed; focused GameTree/PGN/concurrency/identity/ACSDB `76 tests`, `117 subtests` passed. Only `n.`/`n...` move numbers and canonical `$0`..`$255` numeric NAGs remain clean; invalid forms preserve their exact token in structured blocking recovery evidence.
- Local tag-pair verification after `0602189`: broad unittest `806/806` passed; focused GameTree/PGN/concurrency/identity/ACSDB `79 tests`, `120 subtests` passed. Only supported quote/backslash escapes are clean; unsupported escapes and malformed tag-looking lines remain structured blockers attached to one damaged game while clean siblings stay independent.
- Local PGN resource-envelope verification after `b695444`: broad unittest `812/812` passed; focused GameTree/PGN/concurrency/identity/ACSDB/import/duplicate/architecture `108 tests`, `162 subtests` passed. Full pytest is `892 passed`, `1489 subtests`, with exactly the two unchanged Stage1 PRODUCT failures. Oversized source/output tests prove stable codes and no destination directory, lock, temp file or partial database write; a 200-game normal fixture round-trips.
- Local legality-linker verification after `77a6640`: broad unittest `820/820` passed; focused legality/GameTree/chesscore/Stage1-core/architecture `74 tests`, `88 subtests` passed. Standard and SetUp/FEN starts, correct pre-parent RAV positions, illegal-mainline isolation, coordinate/noncanonical SAN, move-number warnings, castling, en passant, promotion, check/checkmate, forced results, recovery separation, cycle/reuse and node bounds are proven without mutating GameTree.
- Competitor lab run `32342624286`: five jobs completed successfully and published compact evidence to `0213f54...`.

## Known failures and blockers

1. `test_rank_and_file_navigation_are_exposed_as_remappable_actions`: PRODUCT — static fallback JSON advertises 16 rank/file actions that the central runtime Action Registry cannot resolve.
2. `test_help_is_generated_from_live_rank_and_file_bindings`: PRODUCT — Help omits the live rank/file bindings.
3. Strict Windows run `32220453450`: BLOCKED / NO PRODUCT ATTRIBUTION YET at native Ctrl+A/Ctrl+C; QA owns the focused evidence pass.
4. Canonical ChessBase CBG move/variation/annotation decoding remains `UNSUPPORTED`; real licensed fixture corpus is absent; CBV/CBF/2CBH/CBONE content remains `UNSUPPORTED`.
5. Full licensed ChessBase/Fritz interactive/NVDA execution remains unavailable. Robot evidence must not be labelled `NVDA_VERIFIED`.
6. Legality projection is not yet enforced by PGN importer inspection or ACSDB persistence: a structurally clean but illegal game can still be labelled FULL and stored. Integration must preserve per-game read-only diagnostics, reject illegal/unverified writes atomically, and retain warning-only noncanonical evidence.

## Current ownership and invariants

- Preserve one canonical Position/Move/GameTree/application state.
- Keep Move, Teacher Pointer, Position Editor, Annotation, Student Hover and Student Selection as separate command families.
- Universal Windows editing semantics have priority inside editable/selectable controls.
- User-facing Help must be generated from the live Action Registry/keymap; menus remain the authoritative discovery path.
- Do not freeze Database, PGN/GameTree, Books, Engine, Teacher/Classroom, menu, keymap or Help UX before reconciling the verified competitor evidence.
- Research decisions require one of: `ADOPT_AS_DEFAULT`, `ADOPT_CONTEXTUALLY`, `COMPAT_PROFILE_ONLY`, `INSPIRE_BUT_IMPROVE`, `REJECT_ACCESSIBILITY_DEFECT`, `INSUFFICIENT_EVIDENCE`.

## Next exact action

Commit and checkpoint the legality linker, then integrate it into read-only PGN inspection and ACSDB import. Per game, classify illegal/unverified/invalid-start evidence as DAMAGED, noncanonical SAN/move-number evidence as WARNING, clean games as FULL, and structural recovery independently; block/roll back any damaged persistence while recording the failed attempt. Do not change the Stage 1 product or QA line. If Issue #14 transfers a PRODUCT fix, stop shared-core work and make the minimum central rank/file Action Registry plus live-Help repair before returning the exact SHA to QA.
