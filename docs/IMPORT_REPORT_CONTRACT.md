# Section 0 ImportReport safety contract

Status: executable Section 0.5 convergence contract.

This contract is stacked on the canonical format-authority lineage from PR #2329 and
the canonical capability lineage from PR #2328. It does not add a parser, chess
rules engine, GameTree model, position model, database model, or provenance store.

## Boundary

External-format adapters are untrusted producers of evidence. Before an adapter
report may cross the shared import registry boundary, Accessible Chess requires:

- an exact passive `ImportReport`, not a subclass or lookalike;
- an exact `SourceFingerprint` for the bytes that were inspected;
- an exact `ImportedRecord` for every reported source record;
- unique non-blank source record identifiers;
- exact `ImportQuality` values: `full`, `partial`, `damaged`, or `warning`;
- explicit message/warning evidence for every non-full outcome;
- no published `game_id` on damaged or warning-only records;
- a positive exact integer when a full/partial record does reference a published game;
- exact warning containers and non-blank warning text.

A `partial` record may identify a canonical published game only when the report
also states what was lost or could not be represented. A `damaged` or
warning-only record cannot claim a published game identity.

## Source immutability on failure

The registry fingerprints the source before an adapter runs and again after it
returns. The same invariant now also applies when the adapter raises an ordinary
decoder/provider exception.

Therefore an adapter cannot mutate/delete/replace its source and hide that side
effect behind a subsequent decoder failure. Source mutation is promoted to the
shared `SourceMutationError` boundary.

The registry still does not swallow process-control exceptions. Batch inspection
records per-source adapter/report failures and continues to later independent
sources, preserving exact failure evidence instead of silently dropping inputs.

## Canonical chess-state rule

`ImportReport` is evidence only. It is not permission to publish chess state.

The format-authority contract remains binding:

`untrusted source -> bounded adapter -> exact ImportReport/evidence -> canonical PositionState or PgnGame/GameTree -> canonical chess validation where required -> atomic Library publication`

Malformed or partial input must never cause an adapter to invent a legal move,
guess a position, or bypass canonical GameTree/Position validation. The
Section 0 authority tests retain fail-closed malformed PGN and EPD behavior; the
ImportReport tests add fail-closed report/provenance semantics.

## Executable evidence

`tests/test_section0_import_report_contract.py` proves:

- PARTIAL/DAMAGED/WARNING outcomes require explicit evidence;
- DAMAGED/WARNING records cannot carry a published game id;
- PARTIAL can carry a game id only with explicit loss evidence;
- duplicate record identity is rejected;
- provenance/report subclasses are rejected;
- an invalid adapter report is rejected without changing source bytes;
- source mutation followed by adapter failure is still detected as mutation;
- batch inspection records one invalid report and continues to a later valid source.

The final Section 0 convergence workflow pins the exact two source lineages,
runtime blobs, contract tests, and runs retained canonical format regressions on
Ubuntu and Windows.

HUMAN_TESTED=NO
NVDA_VERIFIED=NO
