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

### Semantic live-history / redo metadata fail-closed boundary

A Section-1 transition audit found a typed-but-semantic recovery gap in the
application history projection. Existing `move_sides` / `redo_meta` checks
proved shape and scalar types, while incremental move/edit/undo paths did not
require the stronger live-line validator. A structurally valid but wrong mover
side could therefore be consumed and only become visible as an invalid history
projection after publication. The redo path also did not bind its top metadata
entry to the canonical Board redo stack and preserved active History child.

The existing application boundary now:
- requires the exact validated live History lineage before move entry, board
  activation, position-editor publication, undo, or redo can mutate state;
- binds an advertised/executable redo entry to Board redo-stack cardinality,
  target FEN, SAN, side-to-move, active History child SAN/side/last-move;
- fails closed on any mismatch without consuming Board/History/redo state;
- keeps explicit FEN load as the intentional root-reset recovery path.

Focused composed-API regression coverage proves both semantic drift classes:
wrong live mover-side metadata blocks move/activation/editor/undo atomically,
and wrong redo-side metadata is neither advertised nor published. FEN recovery
then restores a valid one-root projection.

Exact successor blobs:
- `acs/webapp.py=c191634ce1394654f327e7c9513d8f54b9848bec`;
- `tests/test_ui_analysis_webapp.py=bf09ba906643377710f5025f17d888191a5fe92d`.

This remains on canonical PR #2356 and preserves the exact 45-path Section-1
delta relative to Section-0 predecessor
`7b172de1ace250e62cb9a077029c056f71d6f833`. Section 1 is still not DONE:
Section 0 acceptance and fresh terminal exact-head source/corpus + whole
qualification remain required.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`

### Complete redo-chain binding and unified incremental-mutation fence

Follow-up recovery audit extended the semantic-history fix across the entire
recoverable suffix rather than only the immediately executable redo entry.
Multiple undo operations retain a reversed Board/metadata stack and a forward
active History child chain; a deeper corruption must be rejected before the
first apparently valid redo or before a new branch silently clears the evidence.

The canonical application boundary now validates every redo entry, in execution
order, against Board target FEN/SAN, alternating mover side, and the matching
active History descendant. The chain must terminate exactly where the redo
stacks terminate. A shared strong mutation predicate now requires both the
validated live lineage and the complete redo-chain invariant before move entry,
board activation, position editing, undo, or redo.

A new negative regression performs two undos, corrupts only the deeper redo
entry while leaving the top entry valid, and proves that redo, a replacement
move, and position editing all fail without consuming or clearing any state.
Explicit FEN root reset remains the recovery route.

Exact successor blobs:
- `acs/webapp.py=ff382335de37dee2e88754dda14a948f826504c4`;
- `tests/test_ui_analysis_webapp.py=c529587bfc65fff315b3ca96c8f5a581ca7cab44`.

The exact #2346-relative Section-1 path union remains 45 paths. Section 0 and
Section 1 remain not DONE until their required terminal qualification conditions
are satisfied.

### Board recovery-pair semantic integrity

A canonical Board recovery audit found a remaining seam after target-FEN
failure atomicity was added. An undo/redo entry contains both a target FEN and
the SAN that is supposed to connect the two positions. The target could be a
fully valid FEN while the paired SAN was wrong, noncanonical, or active text;
the old recovery path validated only the target and could therefore transfer
poisoned move metadata to the opposite stack while changing the live board.

The same Board authority now validates each stored recovery pair before any
publication:
- target/source FEN values and SAN are exact passive text;
- SAN remains inside the shared bounded SAN ingress;
- replay starts from the stored before-position and uses canonical
  `Board.push_text()` legality;
- replayed SAN must equal the stored canonical SAN exactly;
- replayed FEN must equal the stored/live after-position exactly.

Undo and redo call this proof before `set_fen()` or stack transfer, so a valid
FEN paired with wrong SAN, annotation-normalized SAN, or active text fails
atomically. Focused regression coverage proves the board, undo stack, redo
stack and `last_move` remain unchanged on those failures. The existing
canonical null-move recovery pair remains accepted.

Exact successor blobs:
- `acs/chesscore.py=1aa84d1bf9a4fe0bb6b9027786da88393621d2f0`;
- `tests/test_dev2_fen_atomicity.py=cec1c374b3aa06fc499774b7bf88e29630e050fb`.

Compatibility decision: the concurrent semantic application-history work on
`acs/webapp.py` / `tests/test_ui_analysis_webapp.py` is retained unchanged.
This repair is a disjoint canonical Board recovery seam on the SAME #2356
lineage and introduces no second legality, FEN, SAN, or history authority.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`

### Passive recovery-pair container fence

A follow-up recovery audit proved that passive scalar validation alone was not
enough at the canonical Board boundary. `undo()` / `redo()` previously indexed
and unpacked the stored recovery entry before validating the pair container.
Consequently, a two-item list could be silently consumed as canonical recovery
metadata, while a tuple/list subclass could execute an overridden iteration,
length or indexing hook before the passive-value checks.

The Board recovery boundary now validates container identity before observation:
- the selected undo/redo stack must be an exact built-in `list`;
- an empty exact list remains the only no-op recovery state;
- a stored recovery entry must be an exact built-in two-item `tuple`;
- only after those checks are the exact passive FEN/SAN scalars passed to the
  existing canonical transition proof.

Negative regressions prove a list-shaped pair is rejected without mutation,
hostile tuple-subclass hooks are never invoked, hostile stack-subclass hooks are
never invoked for undo or redo, and the live FEN / `last_move` remain unchanged
on rejection. Canonical tuple/list recovery behavior remains covered by the
existing ordinary and null-move undo/redo tests.

Exact successor blobs:
- `acs/chesscore.py=fac7b89a4eb31976578ace4eb94f2d8f8ac079d1`;
- `tests/test_dev2_fen_atomicity.py=c5ce543be86b6a23850ba16a1042c34ffbdcc3ce`.

This is the same #2356 Section-1 lineage and the same 45-path delta relative to
Section-0 predecessor `7b172de1ace250e62cb9a077029c056f71d6f833`.
No second history, FEN, SAN or legality authority is introduced.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`

### Undo/redo destination-stack failure atomicity

The passive recovery-container repair also exposed the symmetric publication
boundary: validating only the source stack is insufficient. `Board.undo()`
publishes into `redo_stack`, and `Board.redo()` publishes into
`undo_stack`. If that destination had been replaced by a tuple or active list
subclass, the old order could validate the source transition, publish the target
FEN, consume the source entry, and only then fail or execute provider code at
`append()`.

Both recovery directions now require the destination stack to be an exact
built-in list before `fen()`, `set_fen()`, source `pop()`, or destination
`append()` can participate in the transaction. Focused regression coverage
proves passive tuple destinations and active list-subclass destinations fail
before Board/history mutation and without invoking destination hooks. Canonical
undo/redo behavior remains unchanged.

This is a same-lineage Section-1 recovery-integrity repair on PR #2356. It does
not alter Section 0, introduce a second chess authority, or make a DONE claim.
Terminal exact-head Ubuntu/Windows/lawful-corpus qualification is still required.

### Ordinary/null move history-container failure atomicity

The same passive-container invariant applies before creating history, not only
while consuming recovery metadata. Canonical `Board.push()` and
`Board.push_null()` previously appended a new undo entry and then cleared the
redo stack without first proving that both containers were exact built-in lists.
A tuple destination could therefore fail after the undo stack had already
changed, while a list subclass could execute provider-controlled
`append()`/`clear()` hooks at the transition publication boundary.

Both ordinary and reviewed null transitions now validate `undo_stack` and
`redo_stack` as exact passive lists before either history stack or Board state
can change. Focused negative coverage exercises both stack directions for both
transition families with passive tuples and active list subclasses, proving no
FEN/opposite-stack/`last_move` mutation and no active hook execution.

This remains same-lineage Section-1 transition/recovery hardening on PR #2356.
It does not change chess legality, expose null moves to ordinary gameplay, alter
Section 0, or claim DONE. Exact-head whole/corpus qualification remains required.

### Re-convergence after Section-0 registration-container and metadata hardening

Section 0 advanced on the SAME canonical #2346 lineage from
`7b172de1ace250e62cb9a077029c056f71d6f833` to
`85417931bb80c36d55878635110d4fa79c57f80a`. The new predecessor closes two host-routing residuals without
changing Section-1 product semantics: passive recovery from adapter-rebound
registration containers, and a bounded transactional read of adapter-owned
registration metadata/suffix iterables.

Prepared Section 1 is therefore history-preservingly reconverged onto exact
Section-0 predecessor `85417931bb80c36d55878635110d4fa79c57f80a` with a two-parent merge. The five Section-0
paths are inherited from that exact predecessor; no Section-1 runtime commit is
rebased, replayed, squashed or dropped. Relative to the new predecessor, the
effective Section-1 delta must remain the same 45 Section-1 paths.

The predecessor-aware source/corpus and whole gates are repinned to this exact
Section-0 head and require fresh terminal lawful/Ubuntu/Windows qualification.
Section 0 remains not DONE until its own exact-head focused + Whole V3 gates
succeed, so this reconvergence is dependency-safe preparation only.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`

### Re-convergence after Section-0 per-source path-ingress isolation

Section 0 advanced on canonical PR #2346 to
`e91315e53d93830240a5989005a7238df8849e76` by moving raw Path/PathLike coercion inside the per-source batch
failure boundary. Ordinary malformed path values can no longer abort the whole
batch or hide later independent sources; direct process-control remains
unswallowed. This is Section-0-only host/import recovery work.

Prepared Section 1 is history-preservingly reconverged onto exact predecessor
`e91315e53d93830240a5989005a7238df8849e76` with a two-parent merge. No Section-1 runtime commit is replayed,
rebased, squashed or dropped; the predecessor's five Section-0 paths are merely
inherited. Relative to this exact predecessor, Section 1 must remain the same
45-path effective delta.

The predecessor-aware source/corpus and whole gates are repinned and require
fresh exact-head lawful/Ubuntu/Windows terminal qualification. Neither Section
is DONE while those gates remain nonterminal.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`

### Re-convergence after exact importer suffix-tuple closure

Section 0 advanced on canonical #2346 to 977a0787df16184d98660c58c798af3e5655323e. The final internal
registration audit aligned runtime acceptance with the declared ReadOnlyImporter
contract: suffix metadata is now an exact built-in tuple, with stale iterator-
based acceptance evidence replaced by a property-level re-entrant mutation
regression. This is Section-0-only import-boundary work.

Prepared Section 1 is history-preservingly reconverged onto that exact
predecessor with a two-parent merge. No Section-1 runtime commit is replayed,
rebased, squashed or dropped. Relative to 977a0787df16184d98660c58c798af3e5655323e, the effective
Section-1 delta remains exactly 45 paths.

Fresh predecessor-aware source/corpus and whole qualification is required.
Section 0 remains BLOCKED_EXTERNAL_CI and Section 1 remains blocked on Section 0
plus its own exact-head terminal qualification.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`

### Re-convergence after source-path routing recovery

Section 0 advanced on canonical #2346 to 616d99003e855424d960e0096c3b37f6972c4320. The five-path Section-0
scope now also closes a source-ingress authority gap: custom PathLike conversion
cannot install or preserve a replacement suffix route before strict lookup,
inspection, batch preflight, or process-control propagation. Host-owned routing
is restored before bounded failure evidence is published.

Prepared Section 1 is history-preservingly reconverged onto that exact
predecessor with a two-parent merge. No Section-1 runtime commit is replayed,
rebased, squashed or dropped. The predecessor's five Section-0 paths are
inherited, and the effective Section-1 delta remains required to be exactly
45 paths.

Fresh predecessor-aware source/corpus and whole qualification is required.
Section 0 remains BLOCKED_EXTERNAL_CI until its exact-head gates are terminal
successful. Section 1 remains blocked on Section 0 acceptance plus its own
exact-head terminal qualification.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`

### Re-convergence after canonical gate queue hygiene

Section 0 advanced to 4fe389a813c44e681a98d28118b60e0c1bee25d1 without changing runtime/import semantics. Its two
canonical exact-head gates now use PR/ref-stable concurrency keys, so future
successor heads can cancel superseded gate runs instead of allocating one
non-cancellable group per SHA.

Prepared Section 1 is history-preservingly reconverged onto that exact
predecessor. Its predecessor-aware source/corpus and whole gates adopt the same
PR/ref-stable concurrency rule while retaining exact-head checkout, 45-path
geometry, blob binding, lawful-corpus qualification, and Ubuntu/Windows
qualification. No Section-1 runtime authority is changed.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`

### FEN product-action acceptance binding

Plan revision 5 Section 1.1 requires FEN reading, creation, copying, editing and validation to be product-reachable, not only present as domain helpers. The prepared lineage already retains the canonical `board.read_fen`, `position.copy_fen` and `pgn.new_from_position` actions with bilingual/native-menu/keymap surfaces. A closure audit found that the predecessor-aware whole-Section gate did not execute the inherited regression modules that qualify those user actions on its exact head.

The whole gate now executes `tests.test_version2_release_ui`, `tests.test_version2_application`, `tests.test_full_product_native_menu` and `tests.test_ui_keymap_adapter` together with the existing FEN/Position/SAN suites. This binds read/copy/create reachability and keyboard/native-menu registration to the same Ubuntu/Windows exact-head qualification without changing runtime authority or the 45-path Section-1 geometry.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`

### Re-convergence after atomic Section-0 route selection

Section 0 advanced on canonical #2346 to
`e3efb598c2315bee7f92be1664ea025702c50d86` after closing a route-selection TOCTOU: importer, format identity
and registration token are now derived from one host-owned snapshot instead of
selecting an importer before the snapshot. A deterministic regression proves a
replacement at the former race boundary cannot cause the stale importer to run
under the replacement identity.

Prepared Section 1 is history-preservingly reconverged onto that exact
predecessor with a two-parent merge. No Section-1 runtime or FEN product-action
acceptance commit is rebased, replayed, squashed or dropped. Relative to the new
predecessor the effective Section-1 delta remains required to be exactly 45
paths.

The source/corpus and whole gates are repinned to the exact predecessor and
retain PR-stable concurrency so superseded queued runs can be cancelled by the
new canonical head. Fresh lawful/Ubuntu/Windows terminal qualification remains
required.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`

### Re-convergence after passive registration-projection closure

Section 0 advanced on canonical #2346 to 2850ace45870b3e6c13f0d8584dcf309773c4728 by making the public
`registered_suffixes` / `registrations()` projections consume the same
validated passive routing snapshot as inspection. This is Section-0-only
host/import authority hardening.

Prepared Section 1 is history-preservingly reconverged onto that exact
predecessor with a two-parent merge. No Section-1 runtime commit is rebased,
replayed, squashed or dropped. The predecessor's five Section-0 paths are
inherited, while the effective Section-1 delta remains exactly 45 paths.

Fresh predecessor-aware source/corpus and whole exact-head qualification is
required.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`


### Re-convergence after retained batch-runtime QA privacy closure

Section 0 advanced again on canonical PR #2346 to `5a2f85c979d360693285c41c80fbe29c782ba3ce` by converging the retained batch-adapter QA with the current privacy-safe ImportRegistry contract. The predecessor delta is test/evidence-only: the two Section-0 qualification workflows now include and exact-pin `tests/test_dev4_import_batch_adapter_failure.py`, the Section-0 receipt records six-path geometry, and the retained QA rejects private/provider exception text while preserving later-source continuation.

This prepared Section-1 lineage is reconverged history-preservingly onto that exact predecessor. The four Section-0-only changed paths are inherited verbatim; the Section-1 source/corpus and whole gates are repinned to the new predecessor; no Section-1 runtime behavior is replaced, rebased, squashed or dropped. A final two-parent merge records the exact Section-0 head as an ancestor so the effective Section-1 delta can again be qualified as ahead-only with exact merge-base.

Fresh exact-head Section-1 qualification is mandatory after this convergence. Queued or pending Actions are not PASS.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`


### Re-convergence after Section-0 six-path receipt alignment

Canonical Section 0 PR #2346 advanced to `3c43fed03145f0227d73b71b771f7d7ba43da6cb` solely to correct durable acceptance evidence: the closure receipt now consistently describes the live six-path successor geometry, and Whole V3 exact-pins that corrected receipt. No new Section-0 runtime behavior was introduced by this evidence repair.

This prepared Section-1 branch inherits the corrected Section-0 workflow/receipt, repins both predecessor-aware qualification gates to `3c43fed03145f0227d73b71b771f7d7ba43da6cb`, and records that exact head as an ancestor in a history-preserving two-parent merge. Section-1 runtime/test payload remains the same effective delta relative to the corrected predecessor.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`


### Reconvergence on passive batch-iterator/diagnostic predecessor

Canonical Section 0 PR #2346 advanced to `f94df7def9d2e365b96e5a5da16fca021f721b7c` on the same
six-path lineage to close two host-routing residuals: provider-owned outer batch
iterators can no longer establish a mutated routing baseline, and custom
adapter-owned OSError subclasses are no longer introspected through active
diagnostic properties.

Prepared Section 1 remains on canonical PR #2356 and is reconverged
history-preservingly onto that exact predecessor. The five newly changed
Section-0 paths are inherited verbatim; no Section-1 runtime/FEN/SAN commit is
rebased, replayed, squashed or dropped. The predecessor-aware source/corpus and
whole gates are repinned to the exact new Section-0 head and require fresh
exact-head qualification.

`SECTION0_ACCEPTED=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`


### Reconvergence on PathLike provider-error sanitization predecessor

Canonical Section 0 PR #2346 advanced to `98208cce4bf01575e84a8f58736ae75e4395875b` on the same six-path
lineage to distinguish host-owned source-path authority errors from
provider-owned ordinary PathLike conversion exceptions. Batch preflight now
sanitizes provider-raised ImportRegistryError values and never executes active
provider `__str__` hooks; strict single-source fail-fast behavior is preserved.

Prepared Section 1 remains on PR #2356 and is history-preservingly reconverged
onto that exact predecessor. No Section-1 runtime/FEN/SAN source is replayed or
rewritten. The predecessor-aware source/corpus and whole gates are repinned and
must qualify the exact descendant before any acceptance claim.

`SECTION0_ACCEPTED=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`


### Reconvergence on strict multi-source iterator-fenced predecessor

Canonical Section 0 PR #2346 advanced to `3f5d33ba7ab54d67e85ea951beede188e3626454` on the same six-path
lineage so strict `inspect_many()`, not only non-aborting batch inspection,
holds host-owned routing authority across provider-owned iterable creation and
each iterator advance.

Prepared Section 1 remains PR #2356 and is reconverged history-preservingly
onto that exact predecessor. No Section-1 FEN/SAN/runtime source is replayed,
rebased or squashed. Predecessor-aware source/corpus and whole gates are
repinned to the exact current ancestor.

`SECTION0_ACCEPTED=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`

### PREVIOUS LIVE AUTHORITY — reconvergence on bounded Section-0 metadata predecessor

Canonical Section 0 PR #2346 is now `ada59caab1365b1fc90cdc99071cd36acdd780d8`.
That same six-path lineage adds a raw 256-character importer `format_name`
fence before whitespace normalization, with exact negative regression and
repinned Section-0 focused/whole gates.

Prepared Section 1 remains PR #2356. Its existing FEN/SAN/position source and
history are preserved history-first: the current Section-0 commit is the first
parent of the reconvergence and the previously prepared Section-1 head is the
second parent. No Section-1 runtime, FEN/SAN source, corpus, or test history is
rebased, squashed, or replayed.

The Section-1 source/corpus and whole-section gates are rebound to exact
predecessor `ada59caab1365b1fc90cdc99071cd36acdd780d8`; their own exact-head
terminal qualification remains required after the final pin update.

`SECTION0_ACCEPTED=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`



### CURRENT LIVE AUTHORITY — reconvergence on corrected six-path Section-0 evidence

Canonical Section 0 PR #2346 advanced on the same lineage to `17de5b9cd6e512bbc8a979dc189fe223c977f826`.
The delta after `ada59caab1365b1fc90cdc99071cd36acdd780d8` is acceptance-evidence/gate binding only: the Section-0 closure receipt now consistently says six-path geometry and Whole V3 exact-pins that corrected receipt. No Section-0 runtime/import/chess behavior changed in this predecessor advance.

Prepared Section 1 remains PR #2356. It inherits the corrected Section-0 receipt and Whole V3 workflow verbatim, repins its predecessor-aware source/corpus and whole gates to `17de5b9cd6e512bbc8a979dc189fe223c977f826`, and records that exact predecessor as an ancestor without rebasing, squashing or replaying the existing 45-path Section-1 runtime/test delta.

Fresh exact-head lawful-corpus plus Ubuntu/Windows qualification is mandatory. Section 0 remains not DONE while its exact-head gates are nonterminal; Section 1 remains dependency-safe preparation only.

`SECTION0_ACCEPTED=NO_PENDING_TERMINAL_CI`

`SECTION_1_DONE=NO_PENDING_SECTION0_ACCEPTANCE_AND_EXACT_HEAD_QUALIFICATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`
