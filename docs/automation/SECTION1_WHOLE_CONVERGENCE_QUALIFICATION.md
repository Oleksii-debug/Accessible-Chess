# Section 1 whole-convergence qualification receipt

This is durable qualification evidence for the sequential Section plan. It does
not mark Section 1 DONE by itself.

## Exact composed source

Current whole-convergence base:
`8da328ed6186a714bd19d4c1d85a840cc35bd68c` on
`converge/section1-whole-contract-20261007-sol56`.

Its runtime/history composition anchor is
`7fc28a6cbe3224c843372e06b9b110be8ad94c94`; the newer base adds the durable
converged Section 1 closure contract without changing runtime bytes.

That commit history-preservingly composes these live Section 1 lineages:
- #2337 SAN/FEN transition contract at
  `ff7798bdec33393cdd6ad79c1e30e0dba12d7b94`;
- #2335 lawful-corpus receipt binding at
  `f6a2c6df5705eadcca1070564c517e6d8c13a248`;
- #2336 deterministic FEN edge corpus at
  `3825a153c3f2a79d1164a0b3001afc2c740cf23d`;
- #2338 PositionState resource/interchange hardening at
  `9209f6cd06ac0cbc8a4ee9ff040797df76ec1ae1`;
- #2340 canonical source-snapshot repair at
  `e604047873ec5de10db747e91f39eb36edab89c4`.

The shared product parent remains #2327
`5d22793c9908831b144b3c62394424f8231738fe`.

No second FEN parser, SAN legality engine, Position model, source reader,
GameTree, or chess-rules authority is introduced by this qualification lane.

## Section 1 acceptance mapping

### 1.1 FEN read/create/copy/edit/check

Canonical `Board` remains playable FEN/legality authority and
`PositionState` remains the editable/interchange DTO. Complete editor/user
flow, atomic failure, history, analysis, and copy/reload regressions are executed
by the exact-head whole gate.

### 1.2 FEN fields, bounds, and variant boundary

Side to move, orthodox castling, en-passant, halfmove, and fullmove semantics
remain on the existing Standard-chess authorities. The converged #2338 repair
prevents direct huge counters and long malformed coordinate diagnostics from
escaping canonical resource/error bounds.

Chess960/Fischer Random remains explicitly unsupported/fail-closed rather than
being silently interpreted as Standard chess; the live plan requires Chess960
only where planned.

### 1.3 SAN/move transitions

The #2337 contract binds SAN length and explicit check/mate claims to canonical
`Board` behavior and proves legal Move -> SAN -> parse -> push -> FEN ->
undo/redo across castling, en-passant, promotion, disambiguation, and mate.

### 1.4 Position interchange

`PositionState` continues to delegate playable-position validation to
canonical `Board`; EPD remains an adapter, not a second rules core. The
converged counter/diagnostic hardening is requalified on both hosted OSes.

### 1.5 deterministic and lawful corpus qualification

The project-authored edge corpus covers valid/invalid representation and
playability boundaries without third-party bytes. Separately, the whole gate
rebuilds the pinned lawful CC0 source and requires at least 200 games and 5000
positions plus side/castling/en-passant/counter edge coverage.

The file-backed qualifier uses canonical
`acs.import_contract.read_source_snapshot`. The whole lawful gate carries
#2335's receipt rule: manifest digest, pre-qualification bytes,
post-qualification bytes, and emitted report `source_sha256` must identify the
same source, after which all acceptance floors are reasserted.

## Closure conditions still outstanding

Section 1 remains NOT DONE until refreshed live authority proves all of:
- Section 0 is honestly DONE;
- this exact qualification head has terminal successful Ubuntu and Windows
  whole-contract jobs;
- its lawful CC0 job is terminal successful;
- the composed source head and relevant parents have not moved without explicit
  reconvergence;
- no newer conflicting Section 1 owner exists;
- the ordered Drive plan, main coordination state, and exact CI are re-read
  immediately before recording DONE.

Queued, pending, cancelled, stale, or absent CI is not PASS.

`SECTION_1_DONE=NO_PENDING_DEPENDENCY_AND_EXACT_HEAD_QUALIFICATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`
