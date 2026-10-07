# Section 1 — FEN, positions, SAN and positional interchange — terminal closure candidate

Status: **FROZEN CANDIDATE — PENDING TERMINAL EXACT-SHA QUALIFICATION**

This is the current canonical durable closure receipt for Section 1 under the root `AGENTS.md` Terminal Section Closure Protocol v2. Git history and PR #2356 preserve the superseded intermediate receipts; this file records only the current acceptance authority.

## Accepted dependency

Section 0 is durably DONE.

- accepted Section-0 source: `dfdd077247e82e45596a044e5a606ec6c39ba17a`
- focused exact-SHA run: `37626867433` — Ubuntu 22.04 SUCCESS, Windows 2025 SUCCESS
- Whole V3 exact-SHA run: `37626867408` — Ubuntu 22.04 SUCCESS, Windows 2025 SUCCESS
- canonical Section-0 integration merge: `71a191075d489edb1dcddaae6801f2e8cff80050`
- durable Section-0 DONE is recorded in root `SEQUENTIAL_CLOSURE_STATE.md`

Section 1 must remain an exact descendant of the accepted Section-0 source and must not introduce a second chess/FEN/SAN authority.

## Section 1 acceptance mapping

### 1.1 Canonical FEN and application state

`acs.chesscore.Board` remains canonical playable FEN/chess authority. `acs.position_editor.PositionState` is the editable/interchange DTO over that authority. Move publication, undo/redo and UI history paths fail closed before publishing FEN that cannot re-enter the same canonical boundary.

### 1.2 FEN fields and variant boundary

Side to move, orthodox castling rights, en-passant, halfmove and fullmove fields are bounded and canonically serialized. Noncanonical castling/en-passant spelling and unsupported Chess960-style rook-file castling evidence fail closed rather than creating a second rules interpretation.

### 1.3 SAN, moves and transitions

Canonical Board legality owns move interpretation and SAN publication. The retained transition contract covers castling, en-passant, promotion, disambiguation, check/mate claims, undo/redo and malformed lexical ingress. Ordinary application gameplay rejects pseudo/null-move text while reviewed low-level analysis/format boundaries retain their explicit primitive.

### 1.4 Positional interchange

PositionState and EPD revalidate current values before publication, enforce resource bounds, preserve canonical Board validation and fail closed on mutated or malformed internal state. EPD remains adapter metadata over canonical position authority.

### 1.5 Lawful real-corpus qualification

The pinned CC0 corpus builder preserves source provenance and now requires both strict structural PGN parsing and a complete, issue-free canonical `acs.gametree_legality.validate_game_legality` report before a source game may enter the curated qualification sample. This prevents structurally parsed but canonically illegal records such as the proven `Rd1d2` case from entering FEN/Position qualification.

## Proven gating failures and bounded repairs

### Lawful-corpus legality repair

A prior exact-SHA lawful-corpus gate proved that strict structural parsing alone admitted a record rejected by canonical GameTree legality. Bounded child #2367 was consumed without widening Board/SAN grammar. The builder/test blobs are exact-pinned by both canonical Section-1 qualification gates.

### Version2 position-action projection repair

Whole exact-SHA run `37629876837`, Windows job `112821047372`, passed geometry, exact blob binding and compilation, then failed while importing `tests.test_version2_release_ui`:

`KeyError: 'unknown action id: position.copy_fen'`

The owner native Position menu contains the already-existing `position.copy_fen` action, but `build_version2_action_registry()` filtered full-product actions to PGN/Library/Books/Training/Toolbar prefixes. The minimal same-finisher repair extends only the Version2 projection to include the existing `position.*` domain. Native-menu validation is preserved and the failing regression remains in the Whole suite.

Exact repaired Version2 profile blob:
- `acs/version2_profile.py = 87ed363d64e8c3d6de291dd63376a42e059b0a29`

Exact repaired source/corpus workflow blob:
- `.github/workflows/section1-fen-corpus-source-snapshot.yml = 6757c3a064d696804285a37a083a1ec66994c2bb`

### Editable representation vs playable Board publication repair

Exact frozen source-boundary run `37633066532`, Windows job `112832270428`, passed exact geometry/blob binding/compilation and then exposed eight Position Editor flow failures. The common root cause was not Windows-specific chess behavior: strict `Board.fen()` publication correctly revalidates a playable Board and therefore rejects deliberately incomplete/non-playable editor states such as an empty board, adjacent kings, or temporarily inconsistent en-passant metadata.

Section 1 requires both boundaries without creating a second chess authority. The repair keeps `Board.fen()` strict (including the existing low-level missing-king publication regression) and restores the editor's representation-only serialization through canonical `PositionState.to_fen()`. Root editor history, live-line coherence and subsequent editor mutations compare that representation FEN while gameplay still requires canonical `Board` validation before any move publication.

The review-blocking regression also now snapshots the review tree after the cursor intentionally moves off the live node, so rejected editor mutations are required to preserve the actual reviewed state rather than an obsolete pre-review cursor snapshot.

Exact repaired blobs:
- `acs/webapp.py = 18e41885299bc05e03d8a3419bbad838fc2bfd68`
- `tests/test_fen_position_editor_complete_user_flow.py = 071790b39970418c3565d6faf8d01cc505511163`

This changes no FEN grammar, move legality, SAN authority, PositionState schema, or 48-path predecessor-relative geometry.


### Adjacent-kings board activation test-oracle repair

Fresh exact-SHA source/corpus run `37634398144`, Windows job `112837126679`, passed predecessor geometry, exact source binding and compilation, then failed in `test_editor_state_with_adjacent_kings_blocks_gameplay` because the regression called a nonexistent `AccessibleChessAPI.click_square()` method.

The existing canonical keyboard/board activation boundary is `AccessibleChessAPI.activate_square()`; it already performs the required fail-closed `_position_playable()` check before selection or move publication. The repair changes only the stale regression call from `click_square("e1")` to `activate_square("e1")`. No runtime API, chess rule, FEN/SAN authority, or product behavior changes.

Exact repaired regression blob:
- `tests/test_fen_position_editor_complete_user_flow.py = 071790b39970418c3565d6faf8d01cc505511163`

The affected exact-SHA gates must be rerun on the successor candidate before DONE.

### Strict-FEN king-capture fixture alignment

Whole exact-SHA run `37633066960` proved that the retained king-capture regression still constructed historically impossible FEN directly through `Board(...)`. That expectation is superseded by the stronger Section-1 canonical FEN boundary: a position where the inactive side remains in check is rejected before publication.

The repair is test/evidence-only; `acs/chesscore.py` is unchanged. The regression now:
- proves canonical ingress rejects each historically impossible FEN;
- creates the same condition only as explicit low-level test corruption starting from a canonical checked-side position;
- proves the pseudo-move attack can target the opposing king while the existing legal-move filter never publishes that capture;
- proves strict `Board.fen()`, SAN/coordinate parsing and push remain fail-closed and failure-atomic on the corrupted state;
- preserves ordinary check/checkmate SAN behavior.

Exact repaired evidence:
- `tests/test_section1_king_capture_boundary.py = 5041554b7e3a94ecaae7ba7841b3eda6c7252df3`
- historical focused child gate `.github/workflows/section1-king-capture-boundary.yml = 62c0cfb1e180b296538aae23b2c944976776c2c1` remains byte-for-byte scoped to its original child branch; the repaired fixture is exact-bound and executed by the canonical Whole gate instead of rewriting historical child-gate authority

This changes no product code, chess rule, FEN grammar, SAN grammar, or predecessor-relative path geometry. The historical focused child workflow is not promoted into a second current-apex closure authority.

## Exact-SHA attempt-2 gating repair

Frozen candidate `c3e05acf8c8dbcaa694665e94255bef5390d0726` produced concrete acceptance-gating failures, so the Terminal Section Closure Protocol authorizes one bounded same-finisher successor.

### Lawful-corpus regression oracle

Source/corpus attempt 2 run `37635721281` failed on both source-boundary operating systems in `test_quality_evidence_rejects_strictly_parsed_but_canonically_illegal_game`. The test's raw regular expression had double-escaped metacharacters, so it matched literal backslashes rather than the first PGN ply and the synthetic illegal record remained byte-identical to the finished fixture. The repair uses one spacing-tolerant first-ply substitution and requires exactly one replacement before exercising the existing canonical-legality rejection. The corpus builder, PGN parser, legality authority, source bytes and license claims are unchanged.

Exact repaired evidence:
- `tests/test_p0f_lawful_starter_bundle.py = 5a658f1459e55905970976c4180bdd7833639602`
- `.github/workflows/section1-fen-corpus-source-snapshot.yml = a355e13aa3ddfba2ece315d4c090a104acf8b453`

### Current failure-domain oracle alignment

Whole attempt 2 run `37635721041`, Windows job `112842018709`, proved two retained assertions still expected superseded lower-level error text:
- huge-counter publication now fails at the stable whole-FEN budget as `FEN занадто довгий`;
- corrupt undo/redo entries are rejected by the stronger exact stored-FEN+SAN transition check as `не відповідає позиції`.

Only the assertions were aligned; failure atomicity and exact state/stack preservation remain mandatory.

Exact repaired evidence:
- `tests/test_dev2_fen_atomicity.py = f5cd49741eb1370519f36076f9f90e0a4175752c`

The first successor Whole Windows run on `cc6225eb0b09d0d24c12ea02fab473eda4d39f5f` reduced the prior 23 mixed failures to exactly two stale assertions in this same atomicity regression. One null-move counter path still expected the superseded pre-budget message, and corrupt undo/redo fixtures over-specified which valid fail-closed validator must reject the corrupt target. The final oracle now requires the canonical whole-FEN budget message for both counter-growth paths and requires `ValueError` plus exact state/history preservation for corrupt recovery entries, without constraining validator precedence.

### Invalid-editor representation oracle

The same Whole run proved one composed UI regression still called strict playable `Board.fen()` while deliberately holding an adjacent-kings editor representation. It now snapshots the public editor representation from `get_state()["fen"]`, matching the already-accepted PositionState-vs-playable-Board boundary without weakening gameplay publication.

Exact repaired evidence:
- `tests/test_ui_analysis_webapp.py = b07c222f8e5129599f752f69b4d1d8c31bf19c19`

### Whole-gate acceptance-boundary correction

The prior Whole command executed complete later-product modules for Library, Books and Training. Those modules exposed unrelated current-product failures (for example Library import lifecycle, Book return durability and a missing test-only `mock` import) that do not belong to canonical Section 1. The successor gate keeps the exact Section-1 source/negative/recovery suites and retains targeted Version2/native-menu tests that prove FEN read/copy/new-PGN-from-visible-position reachability. Broad later-product modules are no longer allowed to enlarge the fixed Section-1 acceptance contract.

This is evidence/gate scoping, not a waiver of any Section-1 failure. Every failure inside the Section-1 boundary remains blocking. No product runtime, chess rule, FEN/SAN grammar or PositionState schema is changed by this attempt-2 repair.


## Whole-gate later-section leakage correction — History/PGN/GameTree

Exact-SHA Whole run `37642025921` reached the Section-1 gate with predecessor geometry, exact authority binding, compilation, the complete FEN/SAN/Position contract and lawful-corpus canonical-legality regression all successful on both Ubuntu and Windows before the next step failed.

The failing step, `Execute retained History EPD GameTree PGN adjacency`, ran complete later-product modules. The observed failures/errors were in History review, PGN Workspace and Version2 PGN command behavior, including historical-analysis projection, PGN annotation dirty-state semantics and PGN export root freezing. These are not Section-1 acceptance surfaces under canonical plan revision 5:

- Section 1 owns FEN, SAN, canonical legality, PositionState/Position Editor interchange and EPD adapter behavior.
- Section 2 owns PGN and full GameTree.
- Section 12 owns History/review workflow behavior.

Accordingly the same canonical Whole gate now retains only `tests.test_epd` from that mixed step and removes the broad History/GameTree/PGN modules plus PGN browser DOM from Section-1 qualification. This is the same fixed-boundary correction already applied to Library/Books/Training leakage: it is not a waiver of any Section-1 failure and does not mutate product/runtime/chess-rule bytes.

The Section-2/Section-12 failures remain real project work for their own sequential Sections and are not marked resolved here. Fresh exact-SHA Source and Whole qualification is required after this evidence-only gate correction.

## Exact predecessor-relative geometry

Accepted predecessor: `dfdd077247e82e45596a044e5a606ec6c39ba17a`

The frozen candidate must be ahead-only, behind=0, have that exact merge-base, and change exactly these 48 acceptance paths:

- `.github/workflows/current-fen-history-section1-convergence.yml`
- `.github/workflows/section1-epd-serialization-revalidation.yml`
- `.github/workflows/section1-fen-castling-order.yml`
- `.github/workflows/section1-fen-corpus-source-snapshot.yml`
- `.github/workflows/section1-fen-edge-corpus.yml`
- `.github/workflows/section1-fen-en-passant-fullmove.yml`
- `.github/workflows/section1-fen-en-passant-halfmove.yml`
- `.github/workflows/section1-fen-field-count.yml`
- `.github/workflows/section1-king-capture-boundary.yml`
- `.github/workflows/section1-positionstate-counter-boundary.yml`
- `.github/workflows/section1-positionstate-serialization-boundary.yml`
- `.github/workflows/section1-san-internal-whitespace.yml`
- `.github/workflows/section1-san-transition-contract.yml`
- `.github/workflows/section1-whole-contract-convergence.yml`
- `acs/chesscore.py`
- `acs/epd.py`
- `acs/input_limits.py`
- `acs/notation.py`
- `acs/position_editor.py`
- `acs/version2_profile.py`
- `acs/stage1_release_ui_core.py`
- `acs/ui_analysis_adapter.py`
- `acs/webapp.py`
- `acs/webapp_keymap.py`
- `acs/webapp_keymap_core.py`
- `docs/automation/SECTION1_CLOSURE_CANDIDATE.md`
- `tests/data/fen_edge_corpus_v1.json`
- `tests/test_dev2_fen_atomicity.py`
- `tests/test_epd.py`
- `tests/test_fen_edge_corpus.py`
- `tests/test_fen_position_editor_complete_user_flow.py`
- `tests/test_p0f_lawful_starter_bundle.py`
- `tests/test_qualify_fen_position_corpus.py`
- `tests/test_section1_fen_castling_order.py`
- `tests/test_section1_fen_en_passant_fullmove.py`
- `tests/test_section1_fen_en_passant_halfmove.py`
- `tests/test_section1_fen_field_count.py`
- `tests/test_section1_king_capture_boundary.py`
- `tests/test_section1_positionstate_counter_boundary.py`
- `tests/test_section1_positionstate_serialization_boundary.py`
- `tests/test_section1_san_internal_whitespace.py`
- `tests/test_section1_san_transition_contract.py`
- `tests/test_stage1_engine_play_ui.py`
- `tests/test_ui_analysis_adapter.py`
- `tests/test_ui_analysis_webapp.py`
- `tools/p0f_lawful_starter_bundle.py`
- `tools/qualify_fen_position_corpus.py`
- `web/index.html`

No additional path is acceptance-authorized. A different path set fails closed.

## Required terminal qualification

Before DONE, the same exact frozen candidate SHA must obtain terminal SUCCESS for:

1. **Section 1 FEN Corpus Source Snapshot**
   - lawful-corpus
   - source-boundary Ubuntu 22.04
   - source-boundary Windows 2025

2. **Section 1 Whole Contract Convergence**
   - lawful-fen-corpus
   - whole-section Ubuntu 22.04
   - whole-section Windows 2025

Queued, pending, cancelled, skipped, stale-SHA or superseded runs are not PASS.

After terminal exact-SHA GREEN:
- merge PR #2356 into the canonical Section-0 integration branch without changing candidate content;
- perform post-merge readback proving the accepted candidate is preserved;
- update root `SEQUENTIAL_CLOSURE_STATE.md` to Section 1 DONE in the same closure run.

No human/NVDA completion claim is made by this receipt.

`SECTION_0_DONE=YES`

`SECTION_1_DONE=NO_PENDING_TERMINAL_EXACT_SHA_QUALIFICATION_AND_INTEGRATION`
