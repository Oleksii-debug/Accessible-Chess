# Accessible Chess — Work Master Current

Updated: `2026-08-20T12:14:09Z`

## Recovery pointer

- `CURRENT_BRANCH`: `completion/full-product-critical-path-20260819`
- `START_SHA`: `588058634b378793b3c9aa0dca113af6b8a2dc8f`
- `CURRENT_REMOTE_SHA`: `1794bf391b2d0258cbfbd37068c7fd6531917194`
- `LAST_SAFE_SHA`: `1794bf391b2d0258cbfbd37068c7fd6531917194`
- `INTEGRATION_SHA`: `e8cd992d306975955784118364ce950963133d7e`
- `QA_SHA`: `07971835cb8fc294996165e577913ed350ae9f0e`
- `RESEARCH_SHA`: `0213f54f3f36fb30379f95c9979aea3a1cc41481`
- `COMPLETION_SHA`: `1794bf391b2d0258cbfbd37068c7fd6531917194`
- `COMPETITOR_EVIDENCE_BRANCH`: `research/competitor-interaction-lab-20260820`
- `COMPETITOR_EVIDENCE_SHA`: `0213f54f3f36fb30379f95c9979aea3a1cc41481`
- `CURRENT_STAGE1_STATE`: `PRODUCT CHECKPOINT READY — central rank/file actions plus Stockfish analysis/play are implemented; exact Windows/NVDA acceptance remains open`
- `CURRENT_OWNER`: `WORK_MASTER — completion product/core/contracts; Windows QA and human NVDA evidence remain QA-owned`
- `CURRENT_PRIORITY`: `Return exact Stage 1 product SHA to QA, then finish professional analysis/books/training while the human gate is pending; Classroom remains last`
- `CURRENT_SUBSYSTEM`: `ACSDB v3 migration/catalog/recovery complete; professional analysis and books/training next`
- `STATUS`: `WIP_SAFE — PRODUCT TESTS PASS; WINDOWS/NVDA PENDING`
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

Commit `1794bf391b2d0258cbfbd37068c7fd6531917194` ports ACSDB v3 onto
the hardened completion line without merging the legacy data branch:

- one atomic v1/v2-to-v3 transaction begins only after a verified sibling
  SQLite backup exists; injected DDL failure rolls back to the starting schema
  and exposes structured recovery evidence;
- deterministic versioned catalog IDs cover players, events, annotators,
  openings, games and default source provenance;
- every new game still passes structural recovery, legality, raw-PGN identity,
  warning and exact-scalar gates before its catalog row is written;
- invalid legacy rows remain preserved but are excluded from the semantic
  catalog with bounded `catalog_issues` evidence;
- indexed exact-source/record duplicate policies, atomic batch import,
  literal annotator/search filters, recursive GameTree retrieval and exact
  position/provenance results are active;
- validated backup/recovery copies publish atomically and never overwrite an
  existing destination.

The exact remote tree is `9b9d485b970f5bfe06c70d988d94d56e752ecc9b`.

Commit `6751827396283674a933a0b5c0c6142f6817a636` activates the Stage 1 game-against-Stockfish path on the production composition boundary:

- analysis and play share the one runtime-owned Stockfish provider and cannot create competing product processes;
- side, levels 1–10, all locked time presets and bounded custom time are exposed in a separate accessible setup dialog;
- typed and 64-square-board moves use the one canonical board/history, with automatic legal engine replies;
- stop, retry, two-ply takeback, draw offer/decline and confirmed resignation use the canonical engine-session/lifecycle contracts;
- timed takeback restores exact historical clocks; engine failure preserves the committed human move and pauses safely;
- both clocks, side, strength, turn and concise lifecycle state are projected without a second live region or raw exception/path leakage;
- packaged Stockfish resolution remains `engines/stockfish/stockfish.exe`, matching the exact QA workflow contract at `07971835...`.

`STAGE1_RELEASE_IMPACT=PRODUCT`; `WINDOWS_TEST_PASS=UNPROVEN`; `NVDA_VERIFIED=NO`.

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
- Local legality-persistence verification after `f559a56`: broad unittest `824/824` passed; focused legality/GameTree/PGN/concurrency/ACSDB/identity/import/duplicate/architecture `120 tests`, `172 subtests` passed. Full pytest is `904 passed`, `1499 subtests`, with exactly the two unchanged Stage1 PRODUCT failures. Mixed inspection yields DAMAGED/WARNING/FULL independently; illegal mixed imports and direct store fail atomically with a recorded attempt; coordinate SAN persists as warning evidence.
- Local PGN provenance verification after `794e3bf`: broad unittest `828/828` passed; focused ACSDB/duplicate/identity/legality `62 tests`, `68 subtests` passed. Full pytest is `913 passed`, `1499 subtests`, with exactly the two unchanged Stage1 PRODUCT failures. Raw overrides must be one clean, legal, record-identical game; warning-only equivalent source bytes retain diagnostics; illegal incoming duplicate collections fail before any claim; illegal legacy rows are explicitly skipped; exact-source SHA evidence is unchanged.
- Local GameTree-navigation verification after `c0aef81`: broad unittest `836/836` passed; focused navigation/GameTree/legality/architecture `47 tests`, `71 subtests` passed. Full pytest is `921 passed`, `1512 subtests`, with exactly the two unchanged Stage1 PRODUCT failures. The adapted legacy cursor now uses the canonical legality path type, exact scalar/tuple boundaries, deterministic nested enter/leave return, immutable addresses and explicit cycle/reuse/depth/node guards without mutating round-trip content.
- Local GameTree-editing verification after `5609dcc`: broad unittest `844/844` passed; focused editing/navigation/GameTree/legality/identity/architecture `64 tests`, `85 subtests` passed. Full pytest is `929 passed`, `1526 subtests`, with exactly the two unchanged Stage1 PRODUCT failures. Promote/reorder/delete are copy-on-write and stale-revision protected; every source cursor receives a deterministic valid remap or explicit deletion; comments/NAG/results/warnings/recovery survive and edited clean games retain round-trip record identity.
- Local generated GameTree-corpus verification after `2af1311`: broad unittest `849/849` passed; generated corpus `5 tests`, `156 subtests` passed. Full pytest is `934 passed`, `1682 subtests`, with exactly the two unchanged Stage1 PRODUCT failures. Sixty-four generated nested/sibling trees retain record identity and stable addresses; generated and chained edits have total composable cursor maps; repeated malformed delimiters remain blockers; forced small token/node/depth envelopes raise exact domain codes.
- Local CBG token-framing verification at `2fea86a`: focused CBG/capability/architecture `22/22` passed; broad unittest `859/859` passed with one existing skip; full pytest is `944 passed`, `1959 subtests`, with exactly the same two unchanged Stage1 PRODUCT failures; compileall and `git diff --check` passed.
- Commit `60ff50d6053c48d8e3308447324cb266b2561ff4` resolves both Stage 1 rank/file PRODUCT failures by registering all 16 actions centrally and generating Help from their live bindings.
- Exact Stage 1 engine-play tree at `6751827396283674a933a0b5c0c6142f6817a636`: broad unittest `877/877` passed; full pytest `965 passed` plus `1959 subtests`; JavaScript parse, compileall and `git diff --check` passed. The remote tree SHA `38e70a7166adfd32ae1a48159cfe576875864a6b` exactly matches the tested local tree. No commit-associated GitHub workflow/status check was emitted for this push.
- Exact ACSDB v3 tree at `1794bf391b2d0258cbfbd37068c7fd6531917194`: broad unittest `889/889` passed; full pytest `977 passed` plus `1965 subtests`; focused pre-v3 ACSDB/search/duplicate/data regression `48/48` passed; compileall and `git diff --check` passed. The remote tree SHA `9b9d485b970f5bfe06c70d988d94d56e752ecc9b` exactly matches the tested local tree. The v3 vertical includes a 600-game catalog corpus, verified v2 backup, injected migration rollback, stale-index fail-closed duplicate proof and recovery-copy reopen.
- Competitor lab run `32342624286`: five jobs completed successfully and published compact evidence to `0213f54...`.

## Known failures and blockers

1. Strict Windows run `32220453450`: BLOCKED / NO PRODUCT ATTRIBUTION YET at native Ctrl+A/Ctrl+C; QA owns the focused evidence pass on a candidate built from the exact new product SHA.
2. Human Windows/NVDA acceptance in Issue #22 is still required; local/Linux tests and UIA robot evidence must not be labelled `NVDA_VERIFIED`.
3. Canonical ChessBase CBG move/variation/annotation decoding remains `UNSUPPORTED`; real licensed fixture corpus is absent; CBV/CBF/2CBH/CBONE content remains `UNSUPPORTED`.
4. Full licensed ChessBase/Fritz interactive/NVDA execution remains unavailable. Robot evidence must not be labelled `NVDA_VERIFIED`.
5. PGN/GameTree is complete within its documented bounded in-memory contract.
   Collections larger than the explicit envelope still require a future
   streaming import service, but the current API neither accepts them partially
   nor claims an unbounded mode.

## Current ownership and invariants

- Preserve one canonical Position/Move/GameTree/application state.
- Keep Move, Teacher Pointer, Position Editor, Annotation, Student Hover and Student Selection as separate command families.
- Universal Windows editing semantics have priority inside editable/selectable controls.
- User-facing Help must be generated from the live Action Registry/keymap; menus remain the authoritative discovery path.
- Do not freeze Database, PGN/GameTree, Books, Engine, Teacher/Classroom, menu, keymap or Help UX before reconciling the verified competitor evidence.
- Research decisions require one of: `ADOPT_AS_DEFAULT`, `ADOPT_CONTEXTUALLY`, `COMPAT_PROFILE_ONLY`, `INSPIRE_BUT_IMPROVE`, `REJECT_ACCESSIBILITY_DEFECT`, `INSUFFICIENT_EVIDENCE`.

## Next exact action

Return Stage 1 product SHA `6751827396283674a933a0b5c0c6142f6817a636`
to the QA-owned Windows candidate line without changing its workflows. While
the exact Windows/NVDA gate is pending, inspect the current professional engine
analysis, books and training surfaces against the canonical product/UX
contracts; close the highest-risk persistence, lifecycle, accessibility and
Windows composition gaps before adapting Teacher/Classroom. Preserve the new
ACSDB v3 boundary and keep Classroom/remote work last.
