# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-0025
REVISION: 1
EFFECTIVE_NEXT_WAVE: 2026-08-22 22:00 Europe/Kyiv
SOURCE_RUN: 20260822-2101
SNAPSHOT: SNAPSHOT_20260822_2101.md

1. Re-read live GitHub and all lane handoffs at a fresh cutoff before acting. Use only terminal evidence that existed before that wave began for DEV1-DEV4 coordination.
2. Preserve Stage1 accepted integration `manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684`; do not merge PR #54 or move frozen refs for convenience.
3. Preserve persistent GREEN full-product validation authority `full5/dev5-compose-1700-20260822 @ dd9ebf9414103c805892856fe6a04706fa69039f`, CI `32577600761 / 97042099941` SUCCESS, until a newer selective composition is independently exact-green.
4. DEV1 eligible terminal intake ceiling: `6b3e41f6c7bf0a436d70c9926e3761cc7f99260f`.
5. DEV2 canonical intake ceiling: `7d525dd34f6ae1a2083a79e25638cbc101e9beaf`; PR #104 is validation-only. Preserve bounded PresentationState plus existing remote/shared-session and PGN termination semantics.
6. DEV3 Product intake ceiling: `9c8a342e7dd98fee52c9776c0cb6a9b970d49296`; PR #106 is validation-only. Preserve Unicode NFKC+casefold Library/Search matching, literal escaping and existing query/resource bounds.
7. DEV4 remains blocking. Head `521966b5e6c3b2b6432468f8ad69a48305bc7b8d` explicitly leaves PGN `expected_sha256` lost-update plus `overwrite=False` no-clobber races unresolved and lacks exact-head Actions. No DEV4 intake until both are repaired and exact executable CI is green.
8. While any touching worker is active or DEV4 remains non-green, SAFE OVERLAP only: evidence review, conflict analysis, backlog ordering, disposable integration preparation and directive maintenance. No competing Product push.
9. After all blocking lanes are terminal exact-green, build a disposable selective composition from `dd9ebf...`; never wholesale-merge validation/evidence PRs. Required vertical: PGN -> canonical GameTree -> ACSDB -> Search/Open plus malformed/oversized/encoding/truncation/concurrency/path/provenance/privacy/recovery, bounded PresentationState, Unicode search semantics, remote-session replay isolation and accessibility regressions.
10. Required verification before persistent promotion: focused tests, full unittest, full pytest, SELFTEST, complete WebView2 diagnostic and applicable exact-head CI. Do not weaken tests/skips/xfail.
11. Fresh Windows candidate requires the complete exact-SHA machine release chain. Old rejected ZIP is forbidden. `NVDA_VERIFIED=NO` until Oleksii personally verifies that exact fresh candidate.
