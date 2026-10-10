# Section 40 — canonical source-preserving continuation, 2026-10-10

**Parent:** 40 only. **Status:** PARTIAL / NOT TERMINAL DONE. **Protected DONE:** 40.2 and 40.5, unchanged. Other Sections 0–39 and 41–45 are not reopened.

## Accepted base / live recovery

- Current main at branch creation: `622ba9f69ae8dfd03d2a86d28a20e1d279bc4fb4`.
- Source of already authored and tested candidate work: [PR #2518](https://github.com/Oleksii-debug/Accessible-Chess/pull/2518) exact head `81e1fccbdf03c287b8e5d4f0520d1ba82fd75c7c`, divergent (20 ahead / 38 behind main when audited), **do not merge wholesale**.
- This strict one-parent convergence candidate: [PR #2545](https://github.com/Oleksii-debug/Accessible-Chess/pull/2545), branch `work/section40-source-preserving-convergence-20261010`.
- 32 original changed paths audited against current main: protected originals already integrated on main `acs/section40_advanced_licensed_dataset.py`, `acs/section40_advanced_training_runtime.py`, `acs/section40_extreme_licensed_dataset.py`, `tools/revised_sections37_38_offline_manifest.py`; all other existing modified canonical source must be diffed and reconciled, not overwritten.
- Original-file copies in #2545 preserve source Git blobs; notably `acs/section40_historical_reti_dataset.py`, `acs/section40_historical_reti_runtime.py`, `acs/section40_bilingual_master_workbook_runtime.py`, `tools/revised_section40_offline_test_library.py`, `tools/revised_section40_windows_qa_assembler.py`, `tools/revised_section40_user_library_seed_bridge.py`, `tools/revised_section37_bilingual_workbook_pack.py`, Section39/40 original source qualifiers and various original tests.
- `acs/version2_starter_content_application.py` was merged with 354/358 exact inherited main source lines preserved, and only four localized descriptions replaced. It now wires original advanced, extreme, Réti and 12-lesson bilingual workbook to existing canonical Books/Training. The distinct 25-genre professional book was deliberately **not** imported because its large original source was not yet restored, avoiding a missing-import runtime crash. No chess rules, format parsers, GameTree, or private Library owner modified.

## Actual test/CI truth

- Dual-OS `.github/workflows/section40-canonical-real-books.yml` created to execute historical Réti, real bilingual master workbook and protected starter content acceptance.
- At inspected PR head `d8f755e03fda9db0d77a10892c8b36752c853d82`, Section40 run `38013151933` was **IN_PROGRESS**, not PASS. Section39 original source tests `38013151908` and Library/Search `38013151874` separately succeeded on both OS. Three broad source-lineage workflows `38013151876`, `38013151904`, `38013151881` have **actual FAILURE**, specifically their ancestry/merge-diff proof steps for this new scope; don't call these green or waive without precise qualified compatibility decision.
- **Known regression to repair before merge:** older protected `tests/test_w3_p0f_starter_books_training_content.py` asserts exactly 24 Booklets + starter course (25 item list). New canonical app adds four new materials (29 list entries); update acceptance invariant narrowly to require exactly 24 *still original* Booklets + starter + four known additional materials (not weaken old Booklet assertion). Existing large-test write was rejected by connector; do not merge before repair.
- **Missing original-module blocker:** `tools/revised_section40_advanced_training.py` (protected original blob `de7bcda76fa045cc1d28c8bc1f2c7230cba2058c`) is still not restored; current `tools/revised_section40_offline_test_library.py` imports it at module loading. Restore intact original before any TEST_BUILD/PUBLIC_RELEASE executable qualification. Other original writes rejected include `tests/test_revised_section40_windows_qa_assembler.py`, `acs/section38_39_professional_catalog_book.py` and older workflow (replace that workflow with a scoped current-main compatible workflow rather than arbitrary raw branch copy). This is **not an executed test pass**.
- No real generated TEST_BUILD/Public release ZIP or Windows packaged QA acceptance in this continuation yet. Final owner NVDA remains whole-product gate under Simplified Closure v3.

## Remaining action queue / do not lie

1. Reuse original missing source without unsafe rewriting; avoid replacing accepted main source with branch 38-commit old version.
2. Repair old exact starter item-count regression and run targeted Book/Training and original-source tests in Actions Ubuntu/Windows; inspect actual failure logs.
3. Qualify lawful original sources and **real** TEST_BUILD/PUBLIC_RELEASE ZIP bytes, verify sha/rights/clean-up and import/restart/backup/Library/Training/Books, ensure no unlicensed originals in public.
4. Bring scoped candidate onto exact latest main, no force, post-merge readback; only then mark 40.1/40.3/40.4/40.6 terminal DONE in GitHub and Google Drive.

**This document is a crash-safe WORKING-LINEAGE handoff, not closure evidence.**
