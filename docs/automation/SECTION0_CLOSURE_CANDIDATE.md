# Section 0 — whole-contract closure candidate

Status: **PENDING_TERMINAL_CI — NOT DONE**

This file is durable convergence evidence for the numerically earliest unfinished live-plan Section. It does not promote Section 0 to DONE until the exact current successor passes its dedicated terminal qualification and the live plan, main, source heads, ownership and CI are rechecked immediately before closure.

## Current convergence authority

The current successor is PR #2346, stacked directly on the released whole-contract successor #2345.

Exact inherited checkpoints:
- #2345 whole-contract successor: `1bc2b88398d8ba76e43fd823e0693de99b7f06e1`;
- #2341 registration-time format-identity repair: `f087ee53a1b47faee1a517e52aea79fcacba65e0`;
- previous whole candidate #2332: `e9e0dceb21c1dc002b844c4e60563b3552f72744`;
- capability authority #2328: `6f8ae8547dfe7c0f15ed124bc0f44a6c660c0056`;
- ImportReport/passive-value lineage #2330/#2331 remains inherited through #2332;
- format-authority lineage #2329 and source formats/history apex #2326 remain inherited.

PR #2346 adds one demonstrated Section 0.5 runtime repair to that ancestry and refreshes the whole-Section gate/receipt on the same lineage. It introduces no second parser, chess rules engine, Position, GameTree, Library, provenance, report or capability authority.

## Section contract mapping

### 0.1 — one canonical authority

Executable contract: `tests/test_section0_format_authority_contract.py`.

Authorities remain:
- playable position / legal move / SAN / playable FEN: `acs.chesscore.Board` + `Move`;
- editable/interchange position: `acs.position_editor.PositionState`;
- EPD: `acs.epd` over the same PositionState;
- PGN structure: exact `acs.gametree` types;
- strict editable PGN persistence: `acs.pgn_roundtrip` over those exact types;
- Library publication: `acs.library_import_service`;
- semantic game identity: `acs.game_identity`;
- provenance remains outside semantic GameTree identity.

### 0.2 — bounded format application boundaries

`docs/FORMAT_AUTHORITY_BOUNDARIES.md` keeps dependency direction:

`untrusted format -> bounded adapter -> canonical PositionState/GameTree -> canonical validation -> publication`

and reverse export through canonical serializers/atomic publication. Format adapters may own lexical/container grammar and resource limits, but not chess legality.

### 0.3 — honest capability matrix

Typed authority remains `acs.format_capabilities.FORMAT_CAPABILITIES` with the closed vocabulary:
- SUPPORTED
- PARTIAL
- UNSUPPORTED
- BLOCKED

The checked projection remains `docs/automation/CANONICAL_FORMAT_CAPABILITY_MATRIX.md`. PARTIAL/BLOCKED states are valid product truth and are not promoted by convergence.

### 0.4 — convergence

This successor preserves #2345, #2341, #2332 and their reconciled Section 0 ancestry instead of opening a competing implementation.

Relative to exact #2345, the current successor is required to change exactly five paths:
- `.github/workflows/section0-import-batch-exception-isolation.yml`;
- `.github/workflows/section0-whole-contract-convergence.yml`;
- `acs/import_registry.py`;
- `docs/automation/SECTION0_CLOSURE_CANDIDATE.md`;
- `tests/test_import_registry.py`.

If #2345 moves before qualification, the gate must fail closed and this successor must be reconverged.

### 0.5 — malformed/partial input reporting

Canonical report authority remains `acs.import_contract.ImportReport`.

The composed stack now requires:
- exact passive ImportReport ingress;
- exact SourceFingerprint provenance scalars;
- exact ImportedRecord scalar types and identifiers;
- explicit loss/damage/warning evidence for non-FULL records;
- repeatable validation of mutable report collections and exact record values before observation/publication;
- source-byte and provenance stability through ImportRegistry;
- source immutability is re-verified after ordinary adapter exceptions, so a source-changing adapter cannot hide mutation behind its decoder error;
- post-adapter source verification that becomes impossible (for example because the adapter deleted/replaced the source) fails closed as SourceMutationError;
- registration-time importer format identity to match returned reports exactly;
- the selected suffix/importer/format registration to remain one stable registration token across each inspection; re-entrant or concurrent replace/unregister/re-register of that suffix during adapter execution fails closed before report acceptance or before an ordinary adapter error can hide the route mutation;
- replace/unregister routing and identity maps to remain synchronized;
- format-identity rejection to be source-preserving and batch-recoverable;
- non-aborting `inspect_batch()` to isolate ordinary adapter/parser exceptions such as KeyError/IndexError per source and continue to later independent sources;
- failed batch items to carry a non-empty diagnostic even when an exception has empty text;
- registry-owned mutation/unverifiable/provenance diagnostics to expose only report-safe source identity, never private workstation parent paths;
- batch adapter exception text to remain untrusted: OSError evidence is reduced to bounded errno/safe filename context, while ordinary adapter diagnostics (including adapter-raised ImportRegistryError) become stable source-scoped messages instead of republishing private decoder/path text;
- strict single-source `inspect()` to remain strict and expose the original ordinary adapter exception;
- process-control exceptions derived directly from BaseException to remain unswallowed;
- trusted cooperative `SourceReadCancelledError` to remain control flow rather than per-source batch evidence, so Cancel stops later source inspection;
- no warning/recovery path may authorize publication of fabricated chess state.

The batch-exception repair changes only the shared import routing boundary and its tests. It does not claim proprietary decoder compatibility.

## Qualification required before DONE

The dedicated whole-Section dual-OS gate must be terminal GREEN on the exact current #2346 head. It checks:
- exact #2345 base and five-path successor geometry;
- #2341/#2332 and inherited capability/import convergence ancestry;
- exact batch-isolation workflow, registry, registry-test, ImportReport, authority and capability blobs;
- Section 0.1–0.5 executable contracts;
- format-identity and ordinary batch-runtime-failure regressions;
- retained EPD/PGN/FEN authority and source-object regressions;
- ChessBase capability/integrity boundaries;
- ACSDB and Version2 formats regressions;
- core chess selftest.

Queued, pending, cancelled, skipped, stale or absent CI is **not PASS**.

Immediately before any DONE marker, refresh:
- canonical ordered Section plan;
- current project plan where it supplies live acceptance context;
- main and `SEQUENTIAL_CLOSURE_STATE.md`;
- #2345/#2346 live heads/states and any newer overlapping Section 0 owner;
- exact current whole-gate CI.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI_AND_LIVE_REVALIDATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`

Physical NVDA evidence is not a hard dependency for this data-contract Section, but no human/NVDA claim is made here.


### Registry route-mutation containment

The canonical Section-0.5 registry boundary now treats importer registration as
host-owned authority for the entire inspection call, not adapter-owned mutable
state. Before adapter execution it snapshots all suffix routes, registered
format identities, and registration tokens. Any re-entrant replacement,
unregistration, or cross-suffix route mutation is restored before the failure
is published or a batch proceeds to another source.

Focused regressions cover successful and failing adapters that attempt to
replace their own route, later sources with the same suffix, and poisoning of
an unrelated suffix. The unauthorized replacement is never invoked for the
later source. Source mutation/unverifiable-source precedence and trusted
cancellation/BaseException behavior remain unchanged.

This repair is on the SAME #2346 lineage and does not introduce another import
registry, parser, report model, or format authority.


### Process-control route restoration

Process-control values derived directly from `BaseException` remain trusted
control flow and are still re-raised unchanged rather than converted into
per-source batch evidence. They can no longer be used by an adapter to retain
a re-entrant registry mutation: before propagating the signal, the registry
compares the complete suffix/format/token snapshot and restores host-owned
routing authority when it changed.

The focused regression mutates an unrelated registered suffix and then raises
`KeyboardInterrupt`; after propagation, both the interrupted adapter route and
the unrelated original route remain exactly as registered. Post-signal source
fingerprinting is intentionally not substituted for the process-control signal,
so cancellation/interrupt semantics remain authoritative while routing state is
recovered.

This is a narrow Section-0.5 recovery hardening on the SAME #2346 lineage. It
does not add a parser, decoder, chess authority, report authority or alternate
registry.
