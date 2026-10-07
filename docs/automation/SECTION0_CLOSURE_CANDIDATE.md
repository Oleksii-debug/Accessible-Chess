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
- canonical suffix declarations to remain bounded, path-separator-free, report-safe and exact-round-trippable through `Path.suffix` before registration, so unreachable routing keys such as `.` or `..foo` never enter host authority;
- unknown-source diagnostics to bound and sanitize hostile/control suffix text instead of republishing it into accessible batch evidence;
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

The focused regressions cover both an unchanged-source interrupt and hostile
process-control adapters that mutate or delete the source before raising
`KeyboardInterrupt` / `SystemExit`. Host-owned routing is restored first; the
source is then re-fingerprinted. An unchanged source preserves the exact
process-control signal, while changed or unverifiable bytes fail closed as
`SourceMutationError`, so process-control cannot bypass the read-only source
boundary.

This is a narrow Section-0.5 recovery hardening on the SAME #2346 lineage. It
does not add a parser, decoder, chess authority, report authority or alternate
registry.


### Cooperative cancellation route restoration

A cooperative `SourceReadCancelledError` remains authoritative control flow even
when the cancelling adapter attempted a re-entrant route mutation. The registry
first restores the complete host-owned registration snapshot and proves source
bytes are still unchanged; it then re-raises the exact cancellation before
ordinary registration-drift reporting can convert Cancel into per-source batch
evidence.

The focused regression mutates an unrelated registered suffix and cancels.
The original routes are restored, the cancellation propagates unchanged, and a
later batch source is not inspected. Source mutation/unverifiable-source
evidence still has precedence because the post-adapter fingerprint check remains
before cancellation propagation.

This is a narrow Section-0.5 recovery fix on the SAME #2346 lineage and adds no
new parser, decoder, registry, report model or chess authority.


### Bounded canonical suffix/error boundary

The same Section-0.5 registry now rejects importer suffix declarations that are
over the 64-character routing budget, contain slash/backslash path syntax,
contain report-control text, or fail an exact `Path.suffix` round trip. This
aligns registration keys with the actual single-suffix router and prevents
unreachable values such as `.` / `..foo` or control-bearing format routes from
entering host authority.

Unknown-source errors use the same bounded/report-safe boundary. A hostile or
extreme suffix is reported as `<invalid>` rather than being copied verbatim
into batch/accessibility diagnostics. Ordinary short unknown suffixes keep their
specific extension evidence.

Focused regressions cover newline, Unicode line-separator, path-like,
non-round-trippable (`.` / `..foo`) and over-budget declarations plus strict and
batch unknown-source diagnostics. The
repair stays on PR #2346 and changes no decoder, chess semantics, provenance
model or capability classification.

### Passive registration-container recovery

A further Section-0.5 adversarial audit found that route restoration still
trusted the identity of the registry's private mapping containers. An adapter
can capture the registry and rebind a routing map to a `dict` subclass or
another active object during inspection. The previous drift check would then
iterate/query that hostile container, while restoration called `clear()` and
`update()` on it. Adapter-owned hooks could therefore execute inside the
host-owned recovery path and prevent authoritative routing from being restored.

The registry now treats container identity and passive shape as part of the
routing invariant:
- all three routing maps must be exact built-in `dict` values before use;
- routing keys and bound format-name/token scalars are checked passively before
  set/membership/equality operations;
- drift detection returns failure without invoking methods on a rebound
  container;
- restoration replaces the three attributes with fresh built-in dict copies
  of the pre-adapter snapshot instead of mutating attacker-supplied containers;
- public register/unregister/importer lookup and inspection fail closed if
  pre-existing registration state is not passive/canonical.

Negative regressions cover a successful adapter, an ordinary failing adapter,
cooperative cancellation, and direct `KeyboardInterrupt`, each rebinding a
different routing container to a hostile dict subclass whose iteration or
mutation hooks raise. No hostile mapping hook is executed; canonical routes are
restored; ordinary batch work continues when appropriate; cancellation and
process-control remain control flow.

This remains the same five-path #2346 successor and introduces no new parser,
decoder, ImportReport, chess, provenance or reporting authority.

### Bounded registration-metadata transaction

The next Section-0.5 audit found that host-owned routing could still be changed
while `register()` was reading adapter-owned metadata. `format_name` and
`suffixes` are Python attributes/iterables and may execute provider code.
The previous passive-state check happened only before those reads, so a
property/iterator could mutate registry routing and make later collision/write
logic operate on the changed authority. The suffix iterable was also
materialized without a count bound.

Registration metadata is now a bounded transaction:
- `replace` must be an exact boolean, so no active truthiness hook is invoked;
- host routing is snapshotted before observing importer metadata;
- suffix iteration is capped at 65 observations for a hard maximum of 64
  declared suffixes;
- every suffix still passes the existing exact-text/canonical-extension fence;
- metadata errors restore any re-entrant routing mutation before propagation;
- a routing mutation is authoritative over an ordinary metadata exception, so
  provider failure cannot hide changed host state;
- successful metadata observation is followed by an exact routing-snapshot
  check before collision detection or registration writes.

Regressions cover format-name property poisoning with a hostile route map,
suffix-iterator route mutation followed by a runtime failure, an infinite
suffix iterator with an exact 65-call bound, and an active non-boolean
`replace` argument whose coercion hook must never run.

This stays inside the same #2346 five-path successor and does not change
format capability truth, parser/chess semantics, ImportReport, provenance or
reporting authority.

### Per-source batch path-ingress isolation

The non-aborting batch contract still had one pre-adapter escape hatch:
`inspect_batch()` converted each raw source with `Path(raw_path)` before its
per-source `try` block. A malformed scalar such as `None`, or a PathLike
whose `__fspath__` raises an ordinary exception, therefore aborted the entire
batch and hid later independent sources.

Path coercion is now part of the per-source ingress transaction. Ordinary
conversion failures produce one stable `Invalid source path` item using a
non-private placeholder path and the batch continues. The provider exception
text is never republished. Direct `BaseException` process-control raised by a
PathLike remains unswallowed, matching the existing adapter control-flow rule.
Strict single-source `inspect()` remains fail-fast.

Regressions cover a `None` item between two valid sources, a PathLike that
raises a private-path RuntimeError, and a PathLike KeyboardInterrupt. Later
valid sources are preserved only for ordinary failures.

This remains same-lineage Section-0.5 recovery work inside the exact five-path
#2346 successor; no format/parser/chess/report authority is added.

### Exact ReadOnlyImporter suffix-container contract

The canonical ReadOnlyImporter protocol declares suffixes as tuple[str, ...],
but the registry still accepted any iterable. A scalar string such as "x"
could therefore be interpreted as one character and silently register .x;
arbitrary iterator/provider code also expanded the registration surface beyond
the declared passive contract.

Registration now requires an exact built-in immutable tuple before observing
its contents. Tuple subclasses, lists, strings and generators are rejected
without invoking container iteration/length hooks. The 64-suffix count fence
remains and every tuple element still passes the canonical suffix-text boundary.

Regressions prove scalar string/list/generator/active tuple-subclass rejection,
zero active tuple hooks, no accidental .x route publication, and the 65-element
count rejection. This keeps the registry aligned with ReadOnlyImporter instead
of broadening its API.

This is the same five-path Section-0.5 lineage and adds no new importer API or
format authority.
