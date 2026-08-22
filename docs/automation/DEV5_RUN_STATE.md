# DEV5_RUN_STATE

RUN_ID: 20260822-2233
STARTED_LOCAL: 2026-08-22 22:33:56 Europe/Kyiv
STATUS: COMPLETE
MODE: SAFE_OVERLAP_COORDINATION / EXACT_DEV4_REPAIR_VALIDATION
COORDINATOR_BRANCH: auto/dev5-coordinator-2233-20260822
SNAPSHOT_CUTOFF: 2026-08-22T22:33:56+03:00
ACTIVE_AUDIT_DIRECTIVE: AUDIT-20260822-1900-01
NEXT_DEV5_DIRECTIVE: DEV5-0028 revision 2

STAGE1_INTEGRATION_TARGET: manual5/integration-20260821
STAGE1_INTEGRATION_SHA: 0fa442330bc2bb03636ff9297512da4c29e38684
PERSISTENT_GREEN_VALIDATION_BRANCH: full5/dev5-compose-1700-20260822
PERSISTENT_GREEN_VALIDATION_SHA: dd9ebf9414103c805892856fe6a04706fa69039f
PERSISTENT_GREEN_CI: 32577600761 / 97042099941 SUCCESS
NVDA_VERIFIED: NO
FRESH_WINDOWS_CANDIDATE: NO
READY_FOR_RELEASE: NO

## Cutoff ruling
Product composition was not legal in this invocation. DEV2 RUN `20260822-2226` was IN_PROGRESS at cutoff; DEV1 work was moving around the cutoff and later started RUN `20260822-2236` for Library/Search WebView UX. Same-wave terminalization/CI is evidence only under the one-wave-lag rule. DEV5 performed no Product composition, cherry-pick, persistent full5 advancement, Stage1 mutation or release mutation.

## DEV4 exact current Product validation
Fresh DEV4 Product repair: PR #100 / `full5/dev4-import-security-repair-20260822 @ 6298899cb112336ef220caa8d0e52334ddc0c0ae`.
DEV5 created evidence-only branch `auto/dev5-validate-dev4-6298899c-20260822` from that exact Product head, added only `.github/workflows/dev5-dev4-product-validation.yml`, and opened draft PR #113 DO NOT MERGE.

Exact validation run `32594202023`, job `97082512844`: FAILURE after checkout, diff hygiene and compile PASS. Strict focused DEV4 suite: 38 PASS / 2 FAIL.

Failure classification:
1. `test_no_overwrite_mode_rechecks_nonexistence_at_commit_boundary` is stale test instrumentation, not a proven Product regression. The test injects a competing creator by mocking `os.replace`, but repaired `overwrite=False` publishes through `_publish_no_clobber()` -> `os.link(tmp_path, destination)`. Re-gate at the real `os.link` commit boundary while preserving `FileExistsError` + competing-byte preservation.
2. `test_missing_game_termination_marker_is_not_counted_full` is branch-ancestry conflict. Canonical DEV2 repaired it in `8ef02d462f3af38a9620f9aae02cdf64654c0652` + `918d4e560d99c12e24e0763dc3a6fc1f1fbd82d4`; exact CI `32583061094 / 97055206185` passes the byte-identical DEV4 truncation oracle. DEV4 must not duplicate/overwrite canonical GameTree ownership.

PR #100 coordination comment `5382238032` records the exact machine evidence. PR #100 remains NOT READY for intake until real-primitive race regression and exact GREEN are available.

## Same-wave evidence quarantined from intake
DEV1 prior PGN/GameTree WebView package terminalized at source `6336d917319f22e422fc3b541feecf7c40977ac9`, PR #112, CI `32594006323 / 97082049039` SUCCESS: focused 115/115, canonical+Stage1 accessibility 65/65, unittest 726/726, pytest 804 + 719 subtests, diagnostic PASS. It cannot be consumed retroactively and DEV1 successor RUN `20260822-2236` is IN_PROGRESS.

DEV2 Classroom Product `8d9c7c99ef8d1754555adaf286ab15f5da3224af`, validation PR #114 / head `08e68af64c7fc8742571f9a7361f912d26fa7881`, CI `32594221729 / 97082562977` SUCCESS: classroom 22/22, interaction 19/19, remote 14/14, unittest 787 OK + 1 skip, pytest 867 + 1336 subtests. RUN `20260822-2226` terminalized at 22:39, but successor RUN `20260822-2240` immediately started from that Product head, therefore touching DEV2 work remains IN_PROGRESS.

DEV2 successor P1 findings were independently source-confirmed on `8d9c7c...`: `_text()` does not reject unpaired Unicode surrogates although deterministic digest/JSON paths UTF-8 encode; `_revision()` accepts arbitrary non-negative Python ints although deterministic JSON serialization has a bounded integer-conversion surface. These remain DEV2-owned and must fail closed before exchange/digest boundaries. Coordination comments on PR #114: `5382258918`, `5382262187`.

DEV3 shippable Product remains PR #105 / `9c8a342e7dd98fee52c9776c0cb6a9b970d49296`, exact CI `32586785490 / 97064264493` SUCCESS. Later 100k Unicode work remains evidence-only.

## Selective intake map prepared during SAFE OVERLAP
DEV2 terminal Classroom delta from prior `7d525dd...` to `8d9c7c...` is clean 3 commits / 0 behind: Product `acs/classroom_domain.py`, focused `tests/test_classroom_domain.py`, plus lane CI metadata. Consume Product/test only after successor hardening terminalizes.

DEV3 delta from previously selected `6f90516a...` to current shippable `9c8a342e...` is 40 commits / 0 behind. Product paths requiring controlled overlay are `acs/analysis_service.py`, `acs/bookreader.py`, new `acs/game_review_service.py`, `acs/search_service.py`, `acs/student_progress.py`, `acs/student_progress_store.py` with corresponding focused tests. Exclude workflow/docs metadata and never whole-merge the DEV3 branch.

## Integration ruling
Persistent exact-GREEN authority remains `dd9ebf...`. DEV4 `acs/acsdb.py` overlaps accepted DEV3/current-green behavior and requires hunk-level reconciliation; preserve DEV2 `acs/gametree.py` canonical authority. No Product/test integration mutation this run.

PR #54/frozen refs untouched. Old rejected ZIP not reused. Windows release chain not started.

READY_FOR_AUDITOR_READBACK=YES
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
