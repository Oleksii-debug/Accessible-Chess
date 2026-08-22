# DEV4 RUN STATE

RUN_ID: 20260822-2200-full-product-repair
STATUS: COMPLETE_WITH_CI_UNOBSERVED
MODE: DEV4_PRODUCT_REPAIR
ROLE: DEV4 Product Developer — import/PGN/ChessBase/security ownership
DIRECTIVE: AUDIT-20260822-1900-01

## Live state

- Product branch: `full5/dev4-import-security-repair-20260822`.
- Product PR #100 remains OPEN/DRAFT/MERGEABLE against `manual5/dev4-platform-security-packaging-20260821`.
- Product candidate at run start: `05e85dbb794388afb390b2319e04b9f818c5ba1b`.
- New Product QA-maintenance commit: `95b6183b7190d689227789fb5fb061969f9c3862` — temp-permission instrumentation follows the real `os.link` no-clobber publication primitive; assertion strength unchanged.
- New Product cleanup-regression commit: `599b38577fe8b7fc017fd2397efba07bd2ba741e` — locks CAS snapshot/temp cleanup on expected-hash replace failure and temp cleanup on no-clobber hard-link failure.
- QA evidence branch maintenance commit: `4b365c46950413d43df9d3da49d83f45ef17b5e3` — same stale temp-permission instrumentation repair on QA PR #67; no safety assertion weakened.
- Accepted Stage1 integration remains `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684`; not mutated.
- DEV5 PR #66 remains separate at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`; not mutated.
- Exact Product-head Actions remain unobserved: `INCONCLUSIVE`, not GREEN.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## This run

No new Product defect was proven. The repaired publication implementation was audited for failure cleanup. A stale QA test was proven to be instrumenting `os.replace` after default no-clobber publication had moved to `os.link`; that would create a false RED (`observed_mode=None`) despite the underlying temp-file privacy assertion remaining valid. Classification: `QA_OR_ENVIRONMENT_ONLY` / QA harness defect, not Product defect.

The test now inspects the actual default publication primitive while preserving the exact POSIX privacy requirement: the temp file must have no group/world permission bits before publication.

Additional positive regression coverage now requires:
1. expected-hash `os.replace` failure preserves the existing destination and cleans both `.tmp` and `.cas-*.bak` files;
2. no-clobber hard-link publication failure publishes nothing and cleans its complete `.tmp` file.

## Product repair status

The DEV4-owned import/PGN/ChessBase/privacy/concurrency defects repaired in PR #100 remain repaired in source. The two previously proven publication races retain Product implementation plus deterministic regression coverage. Missing explicit PGN termination-marker quality remains proven QA evidence but overlaps DEV2 canonical GameTree ownership and is not changed here.

## Classification

- `QA_OR_ENVIRONMENT_ONLY`: stale temp-permission test hook followed obsolete `os.replace`; repaired without weakening assertion.
- `QA EVIDENCE`: CAS/temp cleanup and no-clobber failure cleanup are now locked by positive regressions.
- `INCONCLUSIVE`: exact PR #100 CI until commit-associated checks appear.
- `INCONCLUSIVE`: generic non-cooperative external atomic inode replacement in the narrow CAS window.
- `INCONCLUSIVE`: Windows-specific reparse/hard-link behavior until exact Windows execution.
- `HUMAN_ONLY`: exact fresh Windows/NVDA usability.
- No Ctrl+A/Ctrl+C Product defect claim. `NVDA_VERIFIED=NO`.

## Next action

Re-read PR #100 final exact head and CI. If no new directive appears, inspect post-publication verification/rollback failure semantics, directory durability only where a concrete contract can be proven, and consume exact CI failures. Stay out of DEV5 integration, strict Windows QA, Stage1 release and DEV2 GameTree ownership.
