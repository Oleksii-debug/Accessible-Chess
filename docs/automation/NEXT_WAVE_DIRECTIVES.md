# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-1102
REVISION: 1
SOURCE_RUN: 20260823-1102
EFFECTIVE: next fresh worker/DEV5 invocation after the 2026-08-23 11:02:13 Europe/Kyiv cutoff.

1. Freeze DEV1-DEV4 coordination intake at this cutoff. Use only terminal evidence that existed before it; never race or partially consume current-wave touching work.
2. Preserve accepted Stage1 `0fa442330bc2bb03636ff9297512da4c29e38684` and persistent exact-GREEN `dd9ebf9414103c805892856fe6a04706fa69039f` until an explicit promotion decision is machine-supported.
3. SAFE OVERLAP is mandatory because a prior DEV5 wave already owns touching release-critical Product work in draft PR #151, branch `release/dev5-stage1-path-privacy-repair-20260823`, based exactly on accepted Stage1. Do not create a competing Product patch.
4. PR #151 repair scope must remain minimal: cross-platform report-path sanitization; Stage1 PGN user-facing path diagnostics; ImportRegistry mutation/provenance/batch error rendering; Stockfish startup error redaction while preserving exception cause. Do not expand into GameTree, ACSDB, UI, Teacher/Classroom or strict Windows harness code without new proof.
5. Preserve every privacy oracle and frozen-core byte-identity assertion unchanged. No skip, xfail, assertion relaxation or basename-only semantic regression for safe relative provenance.
6. Live same-lane DEV5 WIP after this cutoff may be inspected for ownership/safety but must not be retroactively used as pre-cutoff DEV1-DEV4 coordination evidence. Current live repair head `909d8e2729e00ba5fce0f25a1520010844f9341b` is workflow-only over `f99146f728ace6f76606beeea6caafbb6ac940e9` and rematerializes exact Git bytes after LF config to fix checkout-time CRLF false-red. Require terminal exact-head CI before promotion.
7. If PR #151 exact head is fully GREEN on Linux privacy/full regressions and Windows privacy/release contracts, independently verify the exact diff and unchanged external QA oracles, then make an explicit Stage1 promotion decision. Do not silently retarget PR #139 or redefine accepted authority by implication.
8. If PR #151 exact head is RED, classify the exact failing gate first. Workflow/fixture failures may be repaired only without weakening assertions; Product changes require machine-proven Product defects.
9. Prior UIA evidence remains separate: V2 proved original Move Edit and native Backspace `e9 -> e`, then failed before Ctrl+A on immediate SetValue readback. No Ctrl+A Product defect is proven. Keep `qa/dev5-stage1-uia-setvalue-observability-20260823 @ 066d1e254c5a2776704bf1f48c580499a24b7045` and V3 `f13f20ca76c8b488447d1996a635df77216397fa` untouched unless ownership is terminal and a deliberate QA update is justified.
10. DEV4 `3e15dc2e844cb825e482317fd024795130147011` remains only a prior repair lineage anchor. Pre-cutoff PR #146 proves five PGN path-bearing diagnostic privacy leaks and PR #147 proves three ImportRegistry diagnostic/batch leaks. DEV5 shared-boundary `7c07147a21fd6c61cd2e072f8c1e457c17de639c` is GREEN only for its older tested scope.
11. DEV1 PR #138 accepted-source UI/NVDA source-contract evidence remains terminal GREEN on Linux and Windows for its tested source-contract scope; it does not replace a fresh candidate chain.
12. DEV2 PR #140 and DEV3 Full Product slices remain later selective Full Product backlog only; do not contaminate Stage1 release freeze.
13. After an explicit repaired-Stage1 promotion, execute a completely fresh Windows candidate chain against the promoted exact source and one designated exact QA harness SHA. Do not reuse the rejected ZIP or assume any prior PR #139 artifact remains valid.
14. A valid candidate requires one uninterrupted terminal GREEN chain: exact source lock, frozen core identity, release contracts, WAV assets, official Stockfish, native-menu structural gate, Nuitka standalone build, built-EXE diagnostic, real WebView2 startup, strict UIA interaction, packaged sound/Stockfish lifecycle, release preflight, ZIP reopen/identity and upload-candidate production.
15. PR #54 and frozen refs remain protected. No force-push shared history.
16. `FRESH_WINDOWS_CANDIDATE=NO`, `READY_FOR_RELEASE=NO`, `NVDA_VERIFIED=NO` until the complete machine chain is GREEN. `NVDA_VERIFIED` changes only after the user personally verifies that exact newly produced artifact.
17. Preserve canonical chess core, GameTree/domain semantics, Windows-only direction, native keyboard/menu behavior, focus origin, clipboard invariants, WebView2 boundary, accessibility names/roles/states and fail-closed privacy/security contracts.
18. `AGENTS.md` and `docs/codex/*` remain absent on live default branch at this cutoff. Use live GitHub SHA/diff/tests/CI plus versioned `docs/automation/*` unless those canonical files later appear and are verified.
