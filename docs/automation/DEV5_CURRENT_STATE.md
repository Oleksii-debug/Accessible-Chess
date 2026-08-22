# DEV5_CURRENT_STATE

UPDATED_FROM_RUN: 20260822-2233
MODE: SAFE_OVERLAP_COORDINATION / EXACT_DEV4_REPAIR_VALIDATION
SNAPSHOT_CUTOFF: 2026-08-22T22:33:56+03:00

Accepted Stage1 remains `manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684`.
Persistent exact-GREEN DEV5 full-product non-PGN authority remains `full5/dev5-compose-1700-20260822 @ dd9ebf9414103c805892856fe6a04706fa69039f`, PR #93 DRAFT / DO NOT MERGE, CI `32577600761 / 97042099941` SUCCESS.

## Live overlap
DEV1 RUN `20260822-2236` remains IN_PROGRESS for Library/Search WebView UX over accepted DEV3 SearchService.
DEV2 prior Classroom RUN `20260822-2226` terminalized at 22:39 after exact GREEN validation, but successor RUN `20260822-2240` immediately started from Product `8d9c7c99ef8d1754555adaf286ab15f5da3224af` to harden deterministic exchange/corruption boundaries. Therefore touching Product work remains active and DEV5 cannot advance composition in this invocation.

## DEV1 evidence
Prior PGN/GameTree WebView package is technical-GREEN at `6336d917319f22e422fc3b541feecf7c40977ac9`, PR #112, CI `32594006323 / 97082049039`: focused 115/115, canonical+Stage1 accessibility 65/65, unittest 726/726, pytest 804 + 719 subtests, diagnostic PASS. Intake waits for a future fresh cutoff after current DEV1 work terminalizes.

## DEV2 evidence and current defects
Terminal Classroom Product `8d9c7c99ef8d1754555adaf286ab15f5da3224af` is technical-GREEN via PR #114 / CI `32594221729 / 97082562977`: classroom 22/22, interaction 19/19, remote 14/14, unittest 787 OK + 1 skip, pytest 867 + 1336 subtests.

Successor RUN `20260822-2240` has two source-confirmed P1 boundaries on that terminal head: (1) text validation allows unpaired Unicode surrogates which can raise raw UTF-8 encoding errors in digest/JSON; (2) revision validation allows arbitrarily large non-negative Python ints which can fail during deterministic JSON integer conversion. These remain canonical DEV2 ownership and are being repaired there; DEV5 does not duplicate the fix.

Clean future Classroom intake delta relative to prior DEV2 `7d525dd...`: exactly Product `acs/classroom_domain.py`, focused `tests/test_classroom_domain.py`, plus lane CI metadata. Consume only after successor hardening terminalizes.

## DEV3
Shippable Product authority remains PR #105 / `9c8a342e7dd98fee52c9776c0cb6a9b970d49296`, exact CI `32586785490 / 97064264493` SUCCESS.
Future selective delta from previously composed DEV3 `6f90516a...` is 40 commits ahead / 0 behind; Product overlay set is `acs/analysis_service.py`, `acs/bookreader.py`, new `acs/game_review_service.py`, `acs/search_service.py`, `acs/student_progress.py`, `acs/student_progress_store.py` plus focused tests. Exclude lane workflow/docs metadata. Later 100k Unicode performance/shadow-column work remains evidence-only.

## DEV4
Current repair head: PR #100 / `6298899cb112336ef220caa8d0e52334ddc0c0ae`. DEV5 evidence-only PR #113 exact run `32594202023 / 97082512844` reached 38 focused PASS / 2 FAIL after checkout/diff/compile PASS.

RED A is stale QA instrumentation: race test mocks obsolete `os.replace`; repaired no-clobber publication uses `os.link`. Re-instrument at the actual commit primitive, preserving `FileExistsError` + competing-file preservation.
RED B is older DEV4 GameTree ancestry; canonical DEV2 already repaired missing-termination quality and passes the independent truncation oracle. Preserve DEV2 `acs/gametree.py` and never whole-merge PR #100.

DEV4 `acs/acsdb.py` overlaps accepted DEV3/current-green ACSDB and must be reconciled hunk-level, taking only DEV4 persisted import-error redaction while preserving current Unicode search/resource/provenance behavior.

## Release boundary
No Product/test integration mutation this run. PR #54/frozen refs untouched. Old rejected ZIP forbidden. Fresh Windows candidate NO. `NVDA_VERIFIED=NO`. `READY_FOR_RELEASE=NO`.
