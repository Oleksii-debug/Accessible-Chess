# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-0024
REVISION: 1
EFFECTIVE_NEXT_WAVE: 2026-08-22 21:00 Europe/Kyiv
SOURCE_RUN: 20260822-2002
SNAPSHOT: SNAPSHOT_20260822_2002.md

1. Re-read live GitHub and all lane handoffs at a fresh cutoff before acting. Use only terminal evidence that existed before that wave began for DEV1-DEV4 coordination.
2. Preserve Stage1 accepted integration `manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684`; do not merge PR #54 or move frozen refs for convenience.
3. Preserve persistent GREEN full-product validation authority `full5/dev5-compose-1700-20260822 @ dd9ebf9414103c805892856fe6a04706fa69039f`, CI `32577600761 / 97042099941` SUCCESS, until a newer selective composition is independently exact-green.
4. DEV1 eligible terminal intake ceiling: `6b3e41f6c7bf0a436d70c9926e3761cc7f99260f`; DEV2 canonical intake ceiling: `371417c2ef43f35da99e6f6ea0bab09e2bae68bb`; DEV3 selective reconciliation ceiling: `1dd2e9d69136a801b7943c1ee2a8b4df6d5e44f7`.
5. DEV4 remains blocking. Head `521966b5e6c3b2b6432468f8ad69a48305bc7b8d` has terminal handoff but no exact-head Actions and explicitly leaves `expected_sha256` lost-update plus `overwrite=False` no-clobber races unresolved. No intake until both are repaired and exact executable CI is green.
6. While any touching worker is active or DEV4 remains non-green, SAFE OVERLAP only: evidence review, conflict analysis, backlog ordering, disposable integration preparation, and directive maintenance. No competing Product push.
7. After all blocking lanes are terminal exact-green, build a disposable selective composition from `dd9ebf...`; never wholesale-merge validation/evidence PRs. Required vertical: PGN -> canonical GameTree -> ACSDB -> Search/Open plus malformed/oversized/encoding/truncation/concurrency/path/provenance/privacy/recovery and accessibility regressions.
8. Required verification before persistent promotion: focused tests, full unittest, full pytest, SELFTEST, complete WebView2 diagnostic, applicable CI. Do not weaken tests/skips/xfail.
9. Fresh Windows candidate requires the complete exact-SHA machine release chain. Old rejected ZIP is forbidden. `NVDA_VERIFIED=NO` until Oleksii personally verifies that exact fresh candidate.
