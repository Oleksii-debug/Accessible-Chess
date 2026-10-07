# Section 6 — Books, Training, Exercises and ready learning content — closure audit

## Authority and scope

Canonical plan authority: **ACCESSIBLE CHESS — SECTION PLAN ДО ПОВНІСТЮ ЗАВЕРШЕНОГО ПРОДУКТУ**, live revision read on 2026-10-07.

Direct owner instruction on 2026-10-07 authorizes closing **Section 6** in this run. This finisher does not mutate chess rules, PGN, Library, Books, Training, UI, persistence, packaging, or starter runtime code. It binds and qualifies the already-integrated canonical implementation.

Exact accepted predecessor for this closure candidate:

- current shipping branch: `converge/current-shipping-recovery-hardening-v2-20261006-c2mbezb`
- predecessor: `bcb549e2edb1334b11d85c0af5cd65f866176a49`
- P0-F consumed-byte starter-corpus integrity PR: **#2226**, merged into that predecessor
- #2226 effective runtime/evidence delta before merge: exactly three paths

Root `AGENTS.md` Simplified Section Closure Protocol v3 applies: physical owner/NVDA acceptance is a final-whole-product gate and does not block an intermediate Section; queued/unstarted hosted CI is recorded honestly and is not called GREEN.

## Section contract mapping

### 6.1 Book Reader, Training collections, tactics/openings/endgames, Guess-the-Move, exercises and notes

Canonical authorities are already present on the predecessor, including `BookDocument`, `BookReader`, Books/Training presentation and workspace layers, canonical `book_training`, starter Books/Training release/runtime material, and semantic book indexing/navigation.

Executable evidence in the closure gate includes:

- `tests/test_bookdocument.py`
- `tests/test_bookreader.py`
- `tests/test_books_training_ui_integration.py`
- `tests/test_book_training_large_reading_journey.py`
- `tests/test_w3_p0f_starter_books_training_content.py`
- `tests/js/books_training_surface_dom_test.js`

### 6.2 Exercises from Books/PGN/Library/current canonical position

The canonical Books -> Training contract is exercised without a second chess-rules authority. Book exercises derive canonical move/position semantics and fail closed on stale, ambiguous, illegal, or mismatched material.

Executable evidence:

- `tests/test_d08_book_training_contract.py`
- `tests/test_p0f_starter_training_canonical_legality.py`
- `tests/test_books_training_ui_integration.py`

Agent/Teacher integration remains intentionally later and is not a hard dependency of Section 6 under the canonical plan.

### 6.3 Progress, mastery, resume, reading anchors, attempt/result history

Book progress and Training progress stores are inherited from the current product authority. Canonical resume replays/validates chess state rather than trusting stale snapshots; persistence paths fail closed on hostile or replaced ancestors.

Executable evidence:

- `tests/test_d08_training_canonical_resume.py`
- `tests/test_training_progress_ancestor_authority.py`
- `tests/test_training_progress_json_prehash_bounds_current.py`
- `tests/test_training_progress_passive_ingress.py`
- `tests/test_w2_training_progress_crash_recovery.py`
- `tests/test_book_training_large_reading_journey.py`

### 6.4 Lawful offline starter corpus

The current starter package includes substantial Books/Training learning material, lawful real instructional/sample games, deterministic project-authored stress content, a sample ACSDB, and canonical positions/FEN/variations.

Relevant durable evidence:

- merged starter Books/Training lineage includes the substantial-content contract originally qualified by PR #700 (24 substantial learning booklets and 144 position-specific Training exercises)
- `docs/V2_STARTER_CONTENT_PROVENANCE.md`
- `docs/P0F_STARTER_CONTENT_PROVENANCE.md`
- `tests/test_w3_p0f_starter_books_training_content.py`
- `tests/test_p0f_lawful_starter_bundle.py`
- `tests/test_stage_p0f_release_content.py`
- P0-F #2226 closes the known local-source consumed-byte/TOCTOU residual while retaining the pinned lawful corpus authority

For #2226, run 59 and run 60 bounded jobs stopped before focused tests on identified gate-only defects (trailing blank-line diff check, then stale PR-base metadata). Both defects were repaired. The real CC0 release-bundle job on run 60 completed **SUCCESS** using the retained production builder. Run 61 was queued/unstarted at the time of intake and is recorded as hosted-runner unavailability, not as GREEN.

### 6.5 Starter content works after clean install/extraction without user files

Packaged starter discovery/staging and first-run application behavior are covered by:

- `tests/test_p0f_packaged_starter_application.py`
- `tests/test_p0f_starter_content.py`
- `tests/test_stage_p0f_release_content.py`
- `acs/version2_packaged_starter_application.py`
- `acs/version2_starter_content_application.py`

The staging tests cover exact validated payload publication, missing executable, unexpected payload, source change during validation, rollback, and preservation of pre-existing release roots.

## Exact inherited runtime locks at closure-candidate creation

The closure workflow binds these inherited authorities so this evidence-only finisher cannot silently substitute another implementation:

- `acs/bookdocument.py` = `23249894e2e7d9c3b2c0602515188000ea846a41`
- `acs/bookreader.py` = `7afb17856686683c5cce5fd8f80ed00383d255a3`
- `acs/book_training.py` = `d7e54c4eb77240b76f80da648ad51c414d73efe1`
- `acs/book_progress_store.py` = `f110939f4cfda4bb24a76d01ea35ffbba7ad2b79`
- `acs/training.py` = `84d46662a1cbbfe80fe8d336dc7f8b1ad9f0dd20`
- `acs/training_progress_store.py` = `ba53f054cf8e00c519aeb008c25653ef2d64371f`
- `acs/starter_books_training_content.py` = `04bbc4aaf44bf9421f7e02adeb10c965ef3f1d9d`
- `acs/starter_books_training_release.py` = `c43123311921bddda0ea9500aab1fb6ceb1c5242`
- `acs/starter_books_training_runtime.py` = `28a054c84d867d51bfb9834e82d2e0ffd8855710`
- `acs/version2_starter_content_application.py` = `4603dac7b1ccdc7a408e5102ee10f8fd7a88ce77`
- `acs/version2_packaged_starter_application.py` = `67b83f8e605ef7534fc5834064e2c2427a4439b6`
- `tools/p0f_lawful_starter_bundle.py` = `8bc6017598eabc4eb4c377952d438f6528f6d0d7`
- `docs/P0F_STARTER_CONTENT_PROVENANCE.md` = `3298aed00ca000d27f607cd861abbba9483ff358`

## Closure rule

When this evidence-only finisher is accepted and the central `SEQUENTIAL_CLOSURE_STATE.md` record is changed to `DONE`, Section 6 and subsections 6.1–6.5 are terminal for ordinary autonomous work.

Normal workers MUST NOT re-enter Section 6 for audit, polish, reimplementation, duplicate testing, or speculative hardening. Reopening is allowed only for a demonstrated regression, invalid closure evidence, a changed acceptance contract, or a later integration that concretely breaks Section 6; the durable state must then explicitly record `REOPENED` and the reason.
