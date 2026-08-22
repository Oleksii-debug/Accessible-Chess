# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-0027
REVISION: 1
SOURCE_RUN: 20260822-2225
SNAPSHOT: SNAPSHOT_20260822_2225.md
EFFECTIVE: next fresh DEV5/worker invocation after this terminal handoff; AUDIT_MASTER directives remain authoritative where newer or explicitly scoped.

1. Establish a fresh immutable cutoff before any Product mutation. Use only terminal foreign-lane evidence existing before that cutoff for intake authorization.
2. Preserve accepted Stage1 `manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684`; never merge PR #54 or move frozen refs for convenience.
3. Preserve persistent exact-GREEN DEV5 authority `full5/dev5-compose-1700-20260822 @ dd9ebf9414103c805892856fe6a04706fa69039f`, CI `32577600761 / 97042099941` SUCCESS, until a newer selective composition is exact-green.
4. DEV1: RUN `20260822-1904` was IN_PROGRESS at the 22:25 cutoff on `full5/dev1-pgn-webview-20260822-1904`. Next invocation must first obtain canonical terminal handoff/RUN_STATE and exact-source CI. Do not consume the 4-path PGN WebView package while it is moving.
5. DEV2: canonical Product ceiling `7d525dd34f6ae1a2083a79e25638cbc101e9beaf`, exact CI GREEN. It already contains missing-PGN-termination semantic repair `8ef02d46...` + `918d4e56...`; preserve this GameTree authority and never overwrite it with DEV4 historical ancestry.
6. DEV3: Product ceiling `9c8a342e7dd98fee52c9776c0cb6a9b970d49296`. Current 100k Unicode query-plan work is evidence-only. Preserve NFKC+casefold/literal wildcard/resource/keyset/provenance semantics.
7. DEV4: pre-cutoff terminal head `f44113ac3c7783aca761c0a7e9044a6cac334cb3` was validated by DEV5 evidence PR #111. Exact run `32593848747 / 97081672853` proved identity/diff/compile and narrowed remaining evidence. Do not call the no-overwrite RED a Product regression: its test still mocks obsolete `os.replace` while Product now publishes no-clobber through `os.link`. Update the race injection to the actual primitive without changing the required `FileExistsError` + competing-file-preservation outcome. Missing-termination RED is already repaired in canonical DEV2 and is an ancestry conflict.
8. DEV4 PR #100 moved after the cutoff. Next run must re-read its fresh terminal head and CI; post-cutoff commits from this wave are quarantined until then. Require exact executable evidence for the final DEV4-owned Product repair scope.
9. SAFE OVERLAP rule: if DEV1 PGN presentation or DEV4 shared-boundary work is still IN_PROGRESS at fresh cutoff, no competing Product composition. Evidence review/conflict analysis/directive maintenance only.
10. When DEV1 and DEV4 are terminal, build a disposable selective composition from `dd9ebf...` in this order: canonical DEV2 current head (including termination semantics) -> accepted DEV3 Product -> only DEV4-owned import/PGN file-service/security repair paths -> terminal DEV1 presentation/WebView paths. Never whole-merge PR #100/#111 or validation/evidence branches.
11. Combined required gates: PGN publication/open -> canonical GameTree -> ACSDB -> Unicode Search/Open; explicit/missing termination; malformed/oversized/invalid-UTF8/truncation; expected-hash and no-clobber races using actual commit primitives; cleanup/recovery/rollback; symlink/reparse/FIFO/special-file rejection; path/error privacy; batch continuation; stable provenance; bounded PresentationState; remote-session replay isolation; Teacher pointer/highlight/hover/selection non-mutation; keyboard/focus/clipboard accessibility; full unittest; full pytest; SELFTEST; complete WebView2 diagnostic; exact-head CI.
12. Never weaken tests, skip, or xfail to obtain GREEN. Old rejected ZIP is forbidden. Fresh Windows candidate requires complete exact-SHA machine release chain. `NVDA_VERIFIED=NO` until the user personally verifies that exact candidate.
