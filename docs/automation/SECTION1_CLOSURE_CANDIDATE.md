# Section 1 closure candidate — FEN, positions, SAN and positional interchange

This file is durable closure evidence for the sequential product plan. It does
not declare Section 1 DONE by itself.

## Exact convergence lineage

- Section 1 composed parent: PR #2327 at
  `5d22793c9908831b144b3c62394424f8231738fe`.
- SAN/transition authority: PR #2337 at
  `ff7798bdec33393cdd6ad79c1e30e0dba12d7b94`.
- Lawful source-snapshot repair / current first parent: PR #2340 at
  `e604047873ec5de10db747e91f39eb36edab89c4`.
- Lawful receipt binding: PR #2335 at
  `f6a2c6df5705eadcca1070564c517e6d8c13a248`.
- Deterministic edge corpus: PR #2336 at
  `3825a153c3f2a79d1164a0b3001afc2c740cf23d`.
- Position interchange/resource boundary: PR #2338 at
  `9209f6cd06ac0cbc8a4ee9ff040797df76ec1ae1`.
- History-preserving convergence anchor:
  `7fc28a6cbe3224c843372e06b9b110be8ad94c94`,
  with #2340 as first parent and #2335/#2336/#2338 as additional parents.
- Canonical convergence branch:
  `converge/section1-whole-contract-20261007-sol56`.
- Released FEN/SAN lexical-ingress child PR #2347 at
  `a9822c819eaa2e5b53d178908c28f20b1ff987c9` is now in canonical
  #2344 ancestry by fast-forward, preserving its exact history without
  force-push/rebase.

No owner branch was rebased, force-pushed, deleted or overwritten. No second FEN
parser, SAN legality engine, Position model, GameTree or chess-rules authority is
introduced.

Section 0 is a hard plan dependency and must be honestly DONE before Section 1
can be marked DONE. At this convergence checkpoint the current Section 0
successor is PR #2346; its current same-lineage source/qualification repairs
are represented on its live head, but exact-head qualification is still
nonterminal. Queued CI is not PASS.

## 1.1 — complete FEN read/create/copy/edit/validate

The composed lineage retains:

- `acs.chesscore.Board` as playable FEN and legality authority;
- `acs.position_editor.PositionState` as the editable/interchange DTO;
- complete Position Editor flows for piece placement/removal, side to move,
  castling, en-passant and move counters;
- failure-atomic invalid direct/API/editor updates;
- copy/read/reload through canonical state;
- history, gameplay and analysis adjacency without a second board authority.

## 1.2 — FEN state fields and variant boundary

Standard-chess interchange covers side to move, orthodox castling rights,
en-passant, halfmove and fullmove fields. Canonical FEN ingress now requires
orthodox castling flags in relative `KQkq` order and canonical lowercase
en-passant square text on both `Board` and `PositionState`; the editor-facing
mutation helpers may still normalize user-entered rights/square text before
constructing a new immutable state. Manual transitions clear stale en-passant
where required and validation remains owned by canonical `Board` /
`PositionState`.

Chess960/Fischer Random is not silently reinterpreted as Standard chess. The
current product boundary explicitly fails closed for unsupported variant
semantics, including rook-file castling evidence. The deterministic edge
corpus includes a Shredder-FEN-style rook-file castling token and requires both
`PositionState` representation parsing and canonical `Board` publication to
reject it. The plan requires Chess960 only where planned; this conservative
boundary is therefore preferable to inventing another rules implementation.

## 1.3 — SAN, moves, transitions and canonical legality

PR #2337 supplies the canonical transition residuals:

- shared bounded SAN/coordinate-move ingress before normalization;
- explicitly supplied `+` / `#` must match canonical `Board.san(move)`;
- omitted suffix remains accepted as the existing human-input convenience;
- executable transition coverage binds
  `Move -> Board.san -> notation grammar -> Board.parse_move -> Board.push ->
  FEN -> undo/redo` across castling, en-passant, promotion, source
  disambiguation and checkmate;
- wrong explicit check/mate claims fail without board mutation;
- canonical and all-zero legacy castling SAN remain accepted, while mixed
  zero/letter forms such as `0-O` / `O-0` are rejected consistently by the
  notation grammar and `Board` legality ingress without board mutation.

## 1.4 — positional interchange without a second rules authority

`PositionState` remains a DTO/edit boundary over canonical `Board`, not an
independent legality engine. The #2338 lineage additionally closes resource and
error-domain seams at this public boundary:

- direct halfmove/fullmove values are bounded before decimal rendering;
- repeated `to_fen()` revalidates exact type and field-specific minima even
  after low-level mutation;
- canonical FEN length remains bounded;
- long malformed coordinate-piece diagnostics are capped before accessible
  announcement and do not mutate the live board;
- `from_fen()` normalizes CPython integer digit-limit conversion failures to
  stable `PositionValidationError` messages for both counters rather than
  leaking runtime-specific `ValueError` text;
- direct `PositionState` values cannot retain noncanonical castling-order or
  en-passant spelling that `to_fen()` would publish differently from
  canonical `Board`.

EPD remains an adapter over the same position authority.

## 1.5 — lawful/open corpus and mass verification

The composed lineage contains both deterministic edge coverage and a real
lawful corpus gate.

Deterministic project-authored corpus:

- explicitly declares no external bytes;
- covers valid/invalid FEN representation and canonical-playability boundaries,
  including side to move, castling, en-passant, counters, promotion-ready
  state, adjacent kings, inconsistent castling, missing EP pawn, pawn on the
  first rank, duplicate castling, unsupported Chess960 rook-file castling,
  Unicode digits, zero fullmove and legacy four-field Board normalization.

Lawful real corpus:

- rebuilds the pinned CC0 real-game sample;
- requires at least 200 games and 5000 positions;
- requires both sides to move plus castling present/cleared, en-passant,
  non-zero halfmove and fullmove > 1 coverage;
- file ingress delegates to canonical
  `acs.import_contract.read_source_snapshot` with the canonical PGN byte
  limit;
- the manifest digest, exact current source bytes and emitted qualification
  report `source_sha256` must remain identical;
- each projected position must round-trip identically through canonical
  `Board` and `PositionState`.

Synthetic fixtures do not substitute for the real-corpus gate.

## Qualification workflow recovery

The Section 1 qualification surface also has to be executable through every
entrypoint it advertises. On the current canonical #2344 lineage:

- `.github/workflows/current-fen-history-section1-convergence.yml` preserves
  exact pull-request base/ref checks when PR event fields exist, while manual
  `workflow_dispatch` relies on the same exact checked-out head, expected-base
  ancestry, path geometry and blob assertions instead of requiring absent
  `pull_request.base.*` fields;
- `.github/workflows/section1-positionstate-counter-boundary.yml` uses the
  same dispatch-safe topology rule;
- `.github/workflows/section1-fen-corpus-source-snapshot.yml` now uses the
  same dispatch-safe topology rule;
- because the source-snapshot workflow was inherited from #2340, changing it on
  #2344 makes it an explicit member of the effective base-to-head convergence
  geometry;
- the consumed #2347 FEN/SAN lexical-ingress workflow is also an explicit
  convergence path and binds exact `Board`, `PositionState` and focused-test
  blobs. The whole-Section gate must include it, its focused test and
  `acs/chesscore.py`, and must pin the exact current blobs before its run can
  be closure evidence.

These are qualification-contract repairs only. They do not alter canonical
FEN/SAN/Position behavior, chess legality, corpus bytes or test expectations.

## Closure gate

Section 1 may be marked DONE only after all of the following are simultaneously
true on freshly re-read live authority:

- Section 0 is honestly DONE;
- #2327/#2337/#2340 and the consumed #2335/#2336/#2338/#2347 residuals have
  not moved away from the exact consumed heads without another
  history-preserving convergence;
- the canonical Section 1 whole-contract convergence head has terminal
  attributable successful Ubuntu and Windows qualification;
- the exact-head lawful CC0 corpus job is terminal successful and its receipt
  remains bound to the exact source bytes;
- deterministic edge-corpus, PositionState resource/error, canonical FEN
  castling/en-passant spelling, and SAN castling-glyph regressions pass on the
  same exact convergence head;
- no newer conflicting Section 1 owner exists;
- the live ordered plan, `main`, Section 0 state and this exact head are
  refreshed immediately before closure.

Queued, pending, cancelled, stale or absent CI is not PASS. Child CI is useful
evidence but does not substitute for the exact whole-convergence head.

`SECTION_1_DONE=NO_PENDING_DEPENDENCY_AND_EXACT_HEAD_QUALIFICATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`


## Prepared predecessor convergence — 2026-10-07

This branch now contains a **prepared, non-accepted** history-preserving cross-Section merge so Section 1 can qualify immediately after Section 0 reaches terminal acceptance.

Exact parents of the prepared merge:
- first parent / current Section 0 candidate: PR #2346 `3714172861b9bc2b28dbb4de58027aea522eba55`;
- second parent / current Section 1 successor apex: PR #2353 `dffbacbbb2ca52812774a20aa58341caad407898`;
- merge commit: `9fdaa587bbe7e95422f55b1eb437ecdeba13e132`;
- prepared branch: `prepare/section1-on-section0-20261007-sol56`.

Mechanical composition proof at merge creation:
- #2346 -> merge: ahead-only / behind=0 / exact merge-base #2346 / exactly 40 Section-1 paths;
- #2353 -> merge: ahead-only / behind=0 / exact merge-base #2353 / exactly 16 Section-0 paths;
- common-apex Section-0 and Section-1 changed-path sets have zero direct overlap;
- the merged tree retains Section-0 `acs/import_contract.py=d9855d173f8c73440e190482a107299be28949c5`;
- it retains Section-1 `acs/chesscore.py=5ba261b7b18d8a9c6cf8858d111d412035a7e5f4` and `acs/position_editor.py=5e5808cacc9dffff4d1c290d418c68d8345babca`.

The Section-1 corpus/source qualification is repinned on this prepared lineage to the exact Section-0 ImportContract and proves #2353 ancestry plus the complete Section-1 union relative to #2346.

This preparation does **not** accept Section 0 and does **not** close Section 1. If #2346 moves, fails qualification, or is not the accepted predecessor, this prepared line must fail closed and be reconverged before use.

Current predecessor condition:
`SECTION0_ACCEPTED=NO_PENDING_TERMINAL_CI`

Current Section-1 condition:
`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_PREDECESSOR_AWARE_WHOLE_QUALIFICATION`


### PositionState serialization successor converged

The prepared predecessor line additionally history-preservingly converges PR #2355:
- #2355 exact head: `a76a3cf1cca4b339e847cb333918ffd125692da2`;
- convergence merge into this prepared line: `05d5dad8fc26f6443ab921ab8e3dd75e7f1a74ea`;
- retained `acs/position_editor.py=8f1a41df8142bf7e7689f4c5f5cf335d8523a4a9`;
- retained regression `tests/test_section1_positionstate_serialization_boundary.py=a566cf563934037f523e7f25cd59ef83b0e910af`;
- retained focused workflow `.github/workflows/section1-positionstate-serialization-boundary.yml=8194108042e2f9fde5d25fcb8b1f679a90a4e893`.

Because `acs/position_editor.py` was already inside the Section-1 union, this adds two new paths, making the exact #2346-relative prepared union **42 paths**, not 43. The gate requires #2355 ancestry and revalidates the serialization regression before any closure claim.


### Predecessor-aware workflow registration repair

The first prepared predecessor-aware source/whole workflow edits used a generated shell heredoc whose payload lines were not indented inside the YAML `run: |` block. GitHub therefore did not register those two workflows on the exact PR head; generic PR workflows did register, making the absence attributable rather than an Actions queue condition.

The invalid form was repaired before qualification:
- source/corpus workflow syntax-repair blob: `fd37aa8850184f62b22dbb1392cc6d639b2bb8d9`;
- whole workflow syntax-repair descendant was created next and must be repinned after this receipt update.

No missing or unregistered run is PASS. Only a fresh exact-head run registered after this repair may qualify the prepared lineage.


### EPD serialization successor converged

The prepared predecessor-aware line additionally history-preservingly converges PR #2357:
- exact #2357 head: `4df2d1870f74dd279218f054e97c6ae781e92808`;
- convergence merge: `67fac0083e7bd6c0e75931bbeb771dcbcf6e9918`;
- retained `acs/epd.py=c1454f2af145729874283fa3b2c9cc29ecac6250`;
- retained `tests/test_epd.py=10fa838c7c44497da9b106b823851535471086cf`;
- retained focused workflow `.github/workflows/section1-epd-serialization-revalidation.yml=88c9880aed687330dfb3cac5ac07c92813af289d`.

All three EPD paths are new relative to the previous 42-path predecessor-aware union, so exact #2346-relative geometry is now **45 paths**. The source/corpus gate current blob after adding #2357 ancestry/geometry is `c836fa1573396fbc8314c53961207be9d19ab885`.

The EPD repair remains representation/publication hardening only. It does not create a second chess-legality authority, and its exact runtime/test/workflow blobs must be pinned by the whole-Section gate before any acceptance claim.


### Re-convergence after Section-0 route containment

Section 0 advanced on the SAME #2346 lineage to
`42309b84e76942c73af86a13cc950d862ea6973c` to contain importer registry route mutation before a batch can
continue. Prepared Section 1 was therefore no longer exact-predecessor-aware.

The existing branches were history-preservingly reconverged through merge-only
PR #2358, producing merge commit
`7f80c73fd67f6c0edd940829cb94cec411348c6d` on the existing
`prepare/section1-on-section0-20261007-sol56` branch. No Section-1 runtime
change was replayed or rewritten.

Fresh geometry from exact #2346 `42309b84e76942c73af86a13cc950d862ea6973c` is ahead-only / behind=0 with
exact merge-base and exactly 45 Section-1 paths. The predecessor-aware source
and whole gates are repinned to this exact predecessor and must receive fresh
terminal attributable qualification. Section 1 remains OPEN until Section 0 is
honestly accepted and those exact descendant gates are GREEN.


### Re-convergence after Section-0 process-control recovery

Section 0 advanced again on the SAME #2346 lineage to
`83f976e5f07a9e68c13bdb55925989221287fe71` so host-owned importer routing is restored before
`KeyboardInterrupt` or another direct `BaseException` is propagated. The
prepared Section-1 lineage was therefore reconverged history-preservingly onto
that exact predecessor rather than treating the previous `42309b84e76942c73af86a13cc950d862ea6973c`
checkpoint as accepted.

The new merge retains all existing Section-1 runtime/corpus/EPD/serialization
history and adopts the exact five-path Section-0 successor. Relative to
`83f976e5f07a9e68c13bdb55925989221287fe71`, the effective Section-1 product delta remains exactly 45
paths; no Section-1 runtime path is dropped or duplicated. The source/corpus
and whole gates are repinned to the new predecessor and must qualify the final
descendant head before Section 1 can be accepted.

Section 0 remains OPEN until its own exact-head terminal qualification succeeds,
so this re-convergence is dependency-safe preparation only and is not a DONE
claim.



### Re-convergence after Section-0 cooperative cancellation recovery

Section 0 advanced again on the SAME #2346 lineage to
`dbbe1c88f399e458df0417ef43ece4a9e32db12d` so a cancelling adapter cannot turn
`SourceReadCancelledError` into ordinary batch evidence after mutating registry
routes. The complete route snapshot is restored, source integrity is checked,
the exact Cancel signal is propagated, and later batch sources remain untouched.

Prepared Section 1 was history-preservingly reconverged through merge-only #2359
without rebasing or replaying Section-1 source. Relative to exact Section-0
predecessor `dbbe1c88f399e458df0417ef43ece4a9e32db12d`, the effective Section-1 delta remains the existing
45-path union. Section 1 remains OPEN until Section 0 is accepted and fresh
exact-head source/corpus plus whole qualification is terminal GREEN.


### Re-convergence after Section-0 bounded suffix/error hardening

Section 0 advanced on the SAME canonical #2346 lineage to
`5d0f190f6214675868aed2df5a2361c6dd4f3cda`. That checkpoint retains the
complete route-restoration/cancellation behavior and additionally bounds
canonical importer suffix declarations plus unknown-suffix diagnostics; its
closure receipt formatting is corrected and its focused/whole gates are
repinned to the exact new blobs.

Prepared Section 1 was history-preservingly reconverged through merge-only
PR #2360, producing merge commit
`a0b4e2f06bac1e4e53f7b63b1731b1f91bb4e3aa` on the existing
`prepare/section1-on-section0-20261007-sol56` branch. No rebase, force-push,
source replay or second Section-1 authority was introduced.

Relative to exact Section-0 predecessor
`5d0f190f6214675868aed2df5a2361c6dd4f3cda`, the effective Section-1 delta
remains ahead-only / behind=0 with the same 45 Section-1 paths. The source/corpus
and whole gates must bind this predecessor and obtain fresh exact-descendant
terminal qualification.

Section 0 remains `BLOCKED_EXTERNAL_CI` and is not accepted. Section 1 remains
OPEN pending Section-0 acceptance plus its own exact-descendant source/corpus and
whole qualification.


### Re-convergence after canonical suffix round-trip enforcement

Section 0 advanced on the SAME #2346 lineage to
`c185073927f17d51db8eb9f0893d4c6ed09af401` after proving that sanitized
suffix declarations such as `.` / `..foo` are still unreachable routing keys
unless they round-trip exactly through `Path.suffix`. The registry now rejects
those keys before registration, with focused negative coverage and repinned
Section-0 exact-head gates.

Prepared Section 1 was reconverged through merge-only PR #2361, producing
`c3e10fc2843ca4332cd2ab994f3e24df465562e4` on the existing prepared branch.
The merge carries only the same five Section-0 paths relative to the previous
predecessor; it does not replay or rewrite Section-1 semantic source.

Relative to exact predecessor
`c185073927f17d51db8eb9f0893d4c6ed09af401`, the effective Section-1 delta
remains ahead-only / behind=0 / exact merge-base with exactly 45 Section-1
paths. Fresh source/corpus and whole gates are required on the final descendant
head. Section 0 is still BLOCKED_EXTERNAL_CI, so neither Section is DONE.

### Re-convergence after Section-0 process-control source-integrity hardening

Section 0 advanced on the SAME canonical #2346 lineage to
`7b172de1ace250e62cb9a077029c056f71d6f833`. In addition to restoring
host-owned routes around direct `BaseException` control flow, the registry now
re-fingerprints the source before propagating an unchanged-source
`KeyboardInterrupt` / `SystemExit`. A process-control adapter that mutates or
deletes the source therefore fails closed as `SourceMutationError` instead of
bypassing the read-only source boundary.

Prepared Section 1 was history-preservingly reconverged through merge-only
PR #2362, producing merge commit
`b71f8f1f48f36dfb7fc7458572607090ac8c8e41` on the existing
`prepare/section1-on-section0-20261007-sol56` branch. No Section-1 semantic
runtime source was replayed, rebased, or duplicated.

Relative to exact Section-0 predecessor
`7b172de1ace250e62cb9a077029c056f71d6f833`, the effective Section-1 delta is
again ahead-only / behind=0 / exact merge-base with exactly 45 Section-1 paths.
The source/corpus and whole gates are repinned to this predecessor and require
fresh terminal exact-head qualification.

Section 0 remains `BLOCKED_EXTERNAL_CI`; Section 1 remains
`BLOCKED_ON_SECTION0_AND_CI`. Neither Section is DONE.



### Ordinary gameplay null-move containment

Canonical `Board.push_text("--")` remains available as the reviewed
format/analysis null-move primitive required by existing format integration.
Section 1 ordinary gameplay no longer exposes that pseudo-move through
`AccessibleChessAPI.make_move`.

The application transaction boundary normalizes the incoming move with the
canonical SAN normalizer and rejects a value that resolves to `--` before
cloning or publishing Board/history state. Focused UI regression coverage proves
both sides of the boundary: direct reviewed Board null-move behavior remains
available, while ordinary move entry (including annotation-normalized `--!`)
fails without changing FEN, GameTree/history, SAN history or side metadata.

This preserves one chess authority and prevents a format-only transition from
becoming a user-visible legal move.


### Inactive-side FEN legality and failure-atomic publication

A final canonical-legality audit found a representation/playability seam that the
existing structural FEN checks did not cover: a six-field FEN could place the
king of the side that just moved under attack while giving the move to the
opponent. Such a position is structurally representable but cannot be the result
of a legal chess move.

The canonical `Board.set_fen` boundary now validates the parsed candidate before
publication using the existing Board attack/check authority. The side to move is
still permitted to be in check, while the inactive side must not remain in
check. This validation occurs on an unpublished candidate copy, so a rejected
FEN cannot partially replace board state, side-to-move, counters, undo/redo
history or `last_move`.

Exact implementation/evidence blobs at this checkpoint:
- `acs/chesscore.py=56dd09605a8f048b23a40676de2087fec84f3e78`;
- `tests/test_dev2_fen_atomicity.py=f03b77f3329dc3f2ab8995cc156f0e4f7419e5c4`;
- `tests/data/fen_edge_corpus_v1.json=11126036c582a37a3e0b7bb9a279889eaf96f6d3`.

The deterministic corpus now covers both legal checked-side-to-move directions
and both impossible inactive-side-in-check directions. The focused atomicity
regression additionally starts from a non-empty move/undo history and proves
that both rejected directions leave the complete live Board/history tuple
unchanged.

This remains Section-1 work on the existing predecessor-aware #2356 lineage.
Section 0 remains a hard dependency, and terminal exact-head whole/corpus CI is
still required before any DONE claim.


### Null-move reloadability after FEN legality hardening

The inactive-side legality fence exposed one adjacent invariant in the existing
format/analysis null-move primitive. A null move from a position where the side
to move is in check would leave that same king checked after flipping the turn,
creating a state that canonical `Board.set_fen` correctly refuses on reload.

`Board.push_null` now fails atomically in that circumstance before touching
history or counters. Ordinary supported null moves remain available: the focused
regression proves a normal `--` transition still serializes through FEN,
reconstructs through a fresh `Board`, and survives undo/redo back to the exact
same null-move position. A checked-side null attempt raises without changing FEN,
undo/redo history or `last_move`.

Exact successor blobs:
- `acs/chesscore.py=d40d049670f0261673f206bc8bd0e13e9c7f852c`;
- `tests/test_dev2_fen_atomicity.py=1d2090a5edaa99634f89fe7c98acd1f3b047023f`.

This is compatibility hardening caused by the same canonical-legality residual;
it does not expose null moves to ordinary user gameplay and does not create a new
format or chess authority.

### Undo/redo stored-target failure atomicity

A recovery-path audit found that canonical `Board.undo()` and `Board.redo()`
transferred their history-stack entries before `set_fen()` validated the stored
target. A stale, corrupt or newly-invalid target could therefore raise after
partially consuming undo/redo metadata even though the live board itself stayed
unchanged.

The existing canonical Board authority now peeks the stored target, validates
and publishes it through `set_fen(..., clear_history=False)`, and only then
transfers the history entry to the opposite stack. Rejected targets leave FEN,
undo stack, redo stack and `last_move` unchanged.

Focused regression coverage injects an impossible inactive-side-in-check target
into both undo and redo history and proves exact failure atomicity.

Exact successor blobs:
- `acs/chesscore.py=10cf720c4010d701635cab746fb6b53a047f5d0d`;
- `tests/test_dev2_fen_atomicity.py=10e50793c794010d724cfaf19b72d4cb8c0f3614`.

The whole-Section gate is repinned to these exact blobs and this updated receipt
in the same atomic branch commit. This is Section-1 recovery hardening only; it
does not alter Section-0, create a second chess authority, or claim DONE.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`

