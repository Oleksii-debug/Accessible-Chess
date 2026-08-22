# DEV4 RUN STATE

RUN_ID: 20260822-1900-full-product-repair
STATUS: COMPLETE_WITH_CI_UNOBSERVED
MODE: DEV4_PRODUCT_REPAIR
ROLE: DEV4 Product Developer — import/PGN/ChessBase/security ownership
DIRECTIVE: AUDIT-20260822-1900-01

## Exact state

- Product branch: `full5/dev4-import-security-repair-20260822`.
- Product code repair head before metadata synchronization: `6ebcca1dddfeafe2916936eaee0f6929ec56c2f2`.
- Draft Product PR: #100, base `manual5/dev4-platform-security-packaging-20260821`.
- Accepted Stage1 integration remains `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684`; not mutated.
- DEV5 PR #66 remains separate at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`; not mutated.
- QA evidence PR #67 remains separate and immutable evidence; strict tests were preserved.
- Exact Product-head Actions were not observed at checkpoint: `INCONCLUSIVE`, not GREEN.
- Local clean checkout/test execution is blocked by sandbox DNS resolution of `github.com`: `QA_OR_ENVIRONMENT_ONLY`.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## Product repairs completed in this campaign

1. Shared import fingerprinting now rejects symlink/reparse/special-file sources before payload read and verifies a stable source identity/snapshot across hashing.
2. PGN open/import now has a finite 64 MiB source/full-text safety boundary and uses bounded text reads.
3. Lossy UTF-8 PGN decoding is propagated into record-level WARNING quality instead of leaving aggregate counts false-green.
4. `ImportRegistry.inspect_batch()` isolates importer `RuntimeError` per source and continues later inputs.
5. ChessBase probe/integrity/manifest serialized report fields no longer expose absolute workstation directories; report payloads use safe filenames.
6. ChessBase companion-directory I/O failure is surfaced explicitly rather than converted to ordinary verified absence.
7. ChessBase integrity hashing rejects unsafe filesystem indirection, checks stable pre/post identity metadata, and normalizes unavailable evidence to domain-level RuntimeError.
8. ChessBase manifest collection rejects unsafe symlink evidence and `verify_manifest_unchanged()` records I/O-unavailable evidence in `(ok, problems)` instead of crashing.

## Still proven / not repaired in this branch

- PGN `expected_sha256` publication TOCTOU/lost-update race.
- PGN `overwrite=False` publication race.
- PGN export destination/ancestor path-indirection escape.
- ACSDB failed-import raw exception persistence/application exposure.
- Missing explicit PGN game-termination marker can still be synthesized as `*` and counted FULL; no GameTree semantic mutation was made because canonical GameTree ownership overlaps DEV2.

## Verification classification

- Product code changes are pushed and PR #100 is open/draft.
- No exact-head CI is observable yet -> `INCONCLUSIVE`, not GREEN.
- Local checkout/test inability is environment-only, not Product evidence.
- No tests were weakened.
- No Ctrl+A/Ctrl+C Product defect claim.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.

## Next action

Re-read PR #100 exact head and Actions. If machine execution becomes observable, consume exact failures before further mutation. Otherwise continue the next DEV4-owned coherent repair subset: ACSDB persisted error privacy, then PGN export path-indirection and publication races using an actually atomic/recoverable design rather than test-specific weakening. Keep GameTree semantic changes out of DEV4 unless Audit transfers ownership.
