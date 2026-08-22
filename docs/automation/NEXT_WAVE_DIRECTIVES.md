# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-0026
REVISION: 1
SOURCE_RUN: 20260822-2202
SNAPSHOT: SNAPSHOT_20260822_2202.md

1. Establish a fresh immutable cutoff before acting; use only terminal DEV1-DEV4 evidence that existed before that cutoff for coordination.
2. Preserve Stage1 `manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684`; do not merge PR #54 or move frozen refs for convenience.
3. Preserve persistent GREEN DEV5 authority `full5/dev5-compose-1700-20260822 @ dd9ebf9414103c805892856fe6a04706fa69039f`, CI `32577600761 / 97042099941` SUCCESS, until a newer selective composition is independently exact-green.
4. DEV1 intake ceiling: `6b3e41f6c7bf0a436d70c9926e3761cc7f99260f`.
5. DEV2 canonical intake ceiling: `7d525dd34f6ae1a2083a79e25638cbc101e9beaf`; PR #104 is validation-only.
6. DEV3 canonical intake ceiling: `9c8a342e7dd98fee52c9776c0cb6a9b970d49296`; PR #107/#108 is performance evidence only, not Product authority.
7. DEV4 pre-cutoff terminal handoff `05e85dbb794388afb390b2319e04b9f818c5ba1b` repairs both previously proven PGN publication races but has `COMPLETE_WITH_CI_UNOBSERVED`. PR #100 moved post-cutoff, proving touching work remains active. No DEV4 intake until final terminal exact head has executable GREEN CI and no touching worker remains.
8. While any shared-boundary worker is active, SAFE OVERLAP only: CI/evidence review, conflict analysis, backlog ordering, disposable integration preparation, directive maintenance. No competing Product push.
9. After blocking lanes are terminal exact-green, build only a disposable selective composition from `dd9ebf...`; never wholesale-merge evidence/validation PRs.
10. Required validation: PGN publication/open -> canonical GameTree -> ACSDB -> Unicode Search/Open; malformed/oversized/encoding/truncation/concurrency/path/provenance/privacy/recovery; bounded PresentationState; remote-session replay isolation; Teacher pointer/highlight/hover/selection non-mutation; keyboard/focus/clipboard accessibility; full unittest; full pytest; SELFTEST; complete WebView2 diagnostic; applicable exact-head CI. Do not weaken tests/skips/xfail.
11. Old rejected ZIP is forbidden. A fresh Windows candidate requires the complete exact-SHA machine release chain. `NVDA_VERIFIED=NO` until Oleksii personally verifies that exact fresh candidate.
