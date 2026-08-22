# DEV4 RUN STATE

RUN_ID: 20260822-2100-full-product-repair
STATUS: COMPLETE_WITH_CI_UNOBSERVED
MODE: DEV4_PRODUCT_REPAIR
ROLE: DEV4 Product Developer — import/PGN/ChessBase/security ownership
DIRECTIVE: AUDIT-20260822-1900-01

## Exact state

- Product branch: `full5/dev4-import-security-repair-20260822`.
- New Product implementation commit: `f37ce643f86871d3680f376ff220502a2390cdc2` — commit-boundary PGN no-clobber plus recoverable expected-hash publication handling.
- Product regression commit: `7d063008bb145a7a9012d442f6af13ef258b40c1` — regression coverage for both publication races.
- QA concurrency gate was preserved semantically and moved to the actual `os.link` no-clobber primitive on QA branch commit `1d90557905753b158b99b7d62321a5e1f1a423bb`; assertion strength is unchanged.
- Draft Product PR: #100, base `manual5/dev4-platform-security-packaging-20260821`.
- Accepted Stage1 integration remains `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684`; not mutated.
- DEV5 PR #66 remains separate at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`; not mutated.
- Exact Product-head Actions remain unobserved: `INCONCLUSIVE`, not GREEN.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## Product repairs completed in PR #100

1. Shared import fingerprinting rejects symlink/reparse/special-file sources and unstable snapshots.
2. PGN import/open has a finite 64 MiB bounded source/text contract.
3. Lossy UTF-8 PGN decoding downgrades record quality.
4. Generic import batch isolates importer `RuntimeError` per source.
5. ChessBase report DTO path privacy and companion I/O observability are hardened.
6. ChessBase integrity/manifest collection rejects unsafe indirection and normalizes verification I/O failures.
7. ACSDB failed-import history persists only failure class plus generic public text; raw parser/provider internals are not persisted.
8. PGN export rejects lexical symlink/reparse indirection across existing ancestors/destination.
9. `overwrite=False` now publishes with same-directory atomic hard-link creation, so a destination created by a competing writer is not replaced.
10. `expected_sha256` publication now creates a hard-link snapshot of the pre-publication inode, rechecks the expected digest at commit, and restores/raises if an in-place writer changes that inode in the final replacement window.

## Remaining classification

- The two previously proven DEV4 PGN publication race tests now have Product repairs and Product regression coverage.
- A fully generic non-cooperative external writer that atomically swaps a different inode during the narrow replace window is not claimed solved by a portable filesystem CAS primitive; broader cross-process atomic-replace semantics remain `INCONCLUSIVE`, not a proven residual failure in the current strict evidence.
- Missing explicit PGN termination marker can still be synthesized as `*` and counted FULL; this remains proven QA evidence but overlaps DEV2 canonical GameTree ownership.
- Exact PR #100 CI is `INCONCLUSIVE` until commit-associated checks appear.
- Windows-specific reparse behavior remains `INCONCLUSIVE` until exact Windows execution.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.
- No tests weakened. No Ctrl+A/Ctrl+C Product defect claim.

## Next action

Re-read PR #100 final exact head and CI. If no new Audit directive appears, independently inspect the repaired PGN publication paths for cleanup/durability/regression interactions and consume any exact CI failures. Stay out of DEV5 integration, strict Windows QA, Stage1 release, and DEV2 GameTree ownership.