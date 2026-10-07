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
