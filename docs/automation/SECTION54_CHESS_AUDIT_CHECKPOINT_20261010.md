# Section 54.4 — Canonical chess structure audit checkpoint

Parent: **Section 54 ACTIVE / PARTIAL / NOT DONE**. This checkpoint is a narrow implementation record; it is neither a new section index nor an alternative plan. Preserve existing PR #2530 source and all baseline Sections 0–53.

## Committed files

- `acs/format_factory_chess_audit.py`: bounded BookDocument snapshot and chess-structure audit using only the existing canonical `chesscore.Board`, `book_game_content.resolve_book_game` / `resolve_book_variation` and `gametree_legality.validate_game_legality`. Games and all variations are checked against the canonical legality engine. Variation starting positions follow the canonical BookBoardWorkflow detached FEN-tag binding.
- `tests/test_section54_factory_chess_audit.py`: six direct canonical-model checks for legal/illegal mainline chess, unsupported chess variant, explicit variation root, FEN diagrams, document tampering, deterministic results and batch limits.
- `.github/workflows/section54-source-intake.yml`: exact Python source/tests compiled and all `test_section54_*.py` discovered on Ubuntu and Windows.

## Acceptance boundary

Reports separate `CHESS_LEGAL_ONLY`, `INVALID_CHESS_STRUCTURE`, counters and canonical issue codes; the two flags `source_verified` and `ready_for_publication` are **always false**. Structural chess legality alone never certifies agreement with scanned diagrams, an author, a particular edition, page anchors, external libraries, rights, accessibility, or print-ready output. The code neither opens internet sources nor runs an API model/engine.

At checkpoint creation, the new exact-head CI run had not yet concluded successfully; **DO NOT claim PASS or DONE** without confirmed current source exact-SHA GitHub Actions checks. Completing 54.4 still needs genuine source-anchored position/diagram fidelity, independent verification and full application integration. The Section54 intake PR remains separate from Section55 Braille PR #2529.

## Resumption

Use the latest **live** PR #2530 head and inspect the current GitHub checks before any further edit. The shared branch has parallel writers, so re-fetch blob SHA and update narrowly; do not overwrite the main Section54 checkpoint when changed concurrently. If tests fail, fix only the actual failing assertion/source defect and repeat exact-SHA qualification.
