# DEV4 RUN STATE

RUN_ID: 20260822-2000-full-product-repair
STATUS: COMPLETE_WITH_CI_UNOBSERVED
MODE: DEV4_PRODUCT_REPAIR
ROLE: DEV4 Product Developer — import/PGN/ChessBase/security ownership
DIRECTIVE: AUDIT-20260822-1900-01

## Exact state

- Product branch: `full5/dev4-import-security-repair-20260822`.
- New Product repair commits this run: `6a5a503d09e46ee9a0e502be6f05b77bf05d05e6` (ACSDB error privacy) and `cb533bb52943abc6da1ce23b4dcccfecaff6ccf8` (PGN export path indirection).
- Draft Product PR: #100, base `manual5/dev4-platform-security-packaging-20260821`.
- Accepted Stage1 integration remains `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684`; not mutated.
- DEV5 PR #66 remains separate at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`; not mutated.
- QA evidence PR #67 remains separate; strict tests are preserved.
- Exact Product-head Actions remain unobserved: `INCONCLUSIVE`, not GREEN.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## Product repairs completed

1. Shared import fingerprinting rejects symlink/reparse/special-file sources and unstable snapshots.
2. PGN import/open has a finite 64 MiB bounded source/text contract.
3. Lossy UTF-8 PGN decoding downgrades record quality.
4. Generic import batch isolates importer `RuntimeError` per source.
5. ChessBase report DTO path privacy and companion I/O observability are hardened.
6. ChessBase integrity/manifest collection rejects unsafe indirection and normalizes verification I/O failures.
7. ACSDB failed-import history now persists only failure class plus a generic public message; raw parser/provider exception text is re-raised to the active caller but is no longer stored in application-facing history.
8. PGN export now rejects lexical symlink/reparse indirection in existing ancestors or destination before/after directory creation and immediately before commit.

## Still proven / unrepaired

- PGN `expected_sha256` publication TOCTOU/lost-update race.
- PGN `overwrite=False` publication no-clobber race.
- Missing explicit PGN termination marker can still be synthesized as `*` and counted FULL; GameTree semantics remain outside DEV4 ownership while DEV2 owns that domain.

## Classification

- New ACSDB privacy and export-path repairs are pushed; exact-head CI is not observable yet -> `INCONCLUSIVE`, not GREEN.
- Windows-specific reparse behavior remains `INCONCLUSIVE` until exact Windows execution.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.
- No tests weakened. No Ctrl+A/Ctrl+C Product defect claim.

## Next action

Re-read PR #100 final exact head and Actions. The remaining DEV4 Product problem is publication concurrency: implement `expected_sha256` CAS and `overwrite=False` no-clobber at the actual commit boundary with recoverable atomic semantics. Do not substitute another preflight check. Stay out of DEV5 integration, strict Windows QA, Stage1 release, and DEV2 GameTree ownership.
