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

Relative to exact #2345, the current successor is required to change exactly six paths:
- `.github/workflows/section0-import-batch-exception-isolation.yml`;
- `.github/workflows/section0-whole-contract-convergence.yml`;
- `acs/import_registry.py`;
- `docs/automation/SECTION0_CLOSURE_CANDIDATE.md`;
- `tests/test_import_registry.py`;
- `tests/test_dev4_import_batch_adapter_failure.py`.

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
- exact #2345 base and six-path successor geometry;
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

This remains the same six-path #2346 successor and introduces no new parser,
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

This stays inside the same #2346 six-path successor and does not change
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

This remains same-lineage Section-0.5 recovery work inside the exact six-path
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

This is the same six-path Section-0.5 lineage and adds no new importer API or
format authority.

### Exact-tuple acceptance-test convergence

After enforcing the declared exact tuple suffix contract, one older adversarial
test still expected a custom suffix iterator to execute before route-drift
detection. That expectation contradicted the new passive-container boundary.
The regression now attacks the suffixes property itself: it mutates host routing
and raises before returning metadata. Registration must restore the snapshot and
surface registration-change evidence while preserving the original RuntimeError
as the cause. Generic iterable hooks remain intentionally unreachable.

### Source-path coercion authority recovery

A later Section-0.5 audit found an ingress gap before adapter execution: a custom
PathLike could run code from __fspath__(), replace canonical suffix routing, and
return a valid-looking path before the registry captured its inspection
snapshot. That made the hostile route look like the baseline instead of a
mutation.

Path coercion now executes under the same host-owned registration snapshot used
for importer metadata and adapter execution. Any re-entrant suffix/format/token
mutation is restored before lookup or inspection. Ordinary PathLike conversion
failures remain isolated per source in batch preflight, while direct
KeyboardInterrupt/SystemExit still propagate after routing recovery. Regression
coverage exercises strict lookup, strict inspection, batch continuation,
ordinary-error sanitization, and process-control restoration without adding a
new format or chess authority.

### Canonical gate queue hygiene

The exact-head gates previously used the head SHA inside their concurrency key
while also declaring cancel-in-progress. Every successor SHA therefore entered a
different concurrency group, so superseded Section-0 runs could not be cancelled
by GitHub's concurrency mechanism and continued accumulating in the runner
queue.

The canonical focused and Whole V3 gates now key concurrency by pull-request
number (or ref for manual dispatch). Exact-head checkout, geometry, blob pins,
tests and matrix semantics are unchanged. A later head can now cancel the older
run for the same canonical PR instead of growing an obsolete exact-head backlog.
This is CI/release control only; runtime/import semantics are unchanged.

### Atomic route-selection snapshot

A final Section-0.5 TOCTOU audit found that inspection previously read the
selected importer from the live suffix map before capturing the registration
snapshot used to bind format identity and token. A concurrent `replace=True`
in that narrow interval could therefore leave the old importer selected while
the later snapshot represented the replacement. If the stale importer returned
the replacement's format label, the mismatch could be hidden and its report
accepted under the replacement registration.

Inspection now captures one host-owned registration snapshot first and derives
the importer, format identity and registration token from that same snapshot.
A replacement that linearizes before the snapshot is the importer that runs; a
replacement after it is caught by the existing registration-drift checks.

The deterministic regression injects a replacement exactly at the former
selection/snapshot boundary and proves the stale importer is never invoked,
the replacement is the accepted route, and source bytes remain unchanged.
Existing re-entrant route replacement tests continue to cover mutations after
the snapshot.

This remains the exact six-path #2346 Section-0.5 lineage and introduces no
new parser, format, report or chess authority.

### Passive registration projections

The passive registration-container boundary also applies to the registry's public
read-only projections. `registered_suffixes` and `registrations()` previously
iterated private routing maps directly, so a pre-corrupted/rebound active mapping
could execute provider `__iter__` / `items` hooks merely by asking the host to
describe its registered routes.

Both projections now derive exclusively from the same validated host-owned
`_registration_snapshot()` used by inspection. Any non-exact/inconsistent
routing container fails closed as `ImportRegistryError` before active mapping
hooks can run. Regression coverage poisons both the route and token maps with a
hostile dict subclass, proves zero hook execution, then proves canonical
projection values are unchanged after restoration.

This remains the exact six-path #2346 Section-0.5 lineage and adds no parser,
decoder, report, format or chess authority.

### Retained batch-runtime QA privacy convergence

A retained repository QA module still encoded the pre-privacy behavior for
ordinary adapter `RuntimeError`: it required the adapter's raw exception text
to appear in `BatchInspectionItem.error`. The current canonical Section-0.5
boundary intentionally treats that text as untrusted because it may contain
private workstation/decoder paths. Leaving the stale oracle outside the
canonical gates would allow the Section gates to pass while repository-level
unittest discovery still contained a contradictory regression.

`tests/test_dev4_import_batch_adapter_failure.py` now requires the stable
source-scoped message, proves private/provider text is absent, and still proves a
later independent source is inspected successfully. The focused and Whole V3
gates exact-pin, compile and execute this retained QA module.

The honest #2346 successor geometry therefore expands from five to exactly six
paths; this is test/evidence convergence only and does not change runtime
semantics.


### Passive batch-iterator and diagnostic-exception boundary

The latest Section-0.5 adversarial pass closed two remaining provider-code
entry points around non-aborting batch preflight.

First, `inspect_batch()` no longer lets the outer `Iterable` become a new
routing baseline. Iterator creation and every `next()` advance run under a
host-owned registration snapshot. Re-entrant route changes are restored and
fail closed as registration-authority evidence; a direct process-control value
still propagates only after canonical routing is restored.

Second, adapter-owned custom `OSError` subclasses are no longer introspected
for `filename`, `filename2` or `errno` while rendering bounded batch
diagnostics. Those attributes may be active provider properties. Only exact
built-in OSError-family instances may contribute bounded errno/safe-name
context; custom subclasses receive the stable source-scoped rejection message.

Regressions prove iterator creation mutation, iterator-advance mutation,
process-control restoration, and zero execution of hostile OSError attribute
hooks while a later independent source remains inspectable.

This remains the same six-path PR #2346 successor and introduces no parser,
decoder, report, format or chess authority.


### Provider-owned PathLike registry-error sanitization

A further Section-0.5 ingress audit found that a provider-owned `PathLike`
could deliberately raise `ImportRegistryError` (or a subclass) from
`__fspath__()`. Batch preflight previously caught that type as if it were
host-owned registry evidence and called `str(exc)`, allowing private provider
text or an active `__str__` hook to cross the reporting boundary.

Batch path coercion now has an explicit provider-failure envelope. Ordinary
conversion exceptions are sanitized to the stable `Invalid source path`
evidence regardless of their class; host-owned route-drift errors remain
distinct; direct BaseException process-control remains unswallowed. Strict
single-source inspection preserves its existing fail-fast exception behavior.

Regressions cover an exact provider-raised ImportRegistryError containing a
private workstation path and an active subclass whose `__str__` raises
KeyboardInterrupt. Batch evidence leaks neither and executes zero active string
hooks.

This remains the same six-path #2346 lineage and adds no parser, decoder,
report, format or chess authority.


### Strict multi-source iterable authority fence

A further Section-0.5 audit found that the non-aborting batch API already
protected provider-owned outer iterable creation/advance, but strict
`inspect_many()` still iterated the caller object directly. A custom iterable
could therefore replace a registered importer between yields and make the next
strict source execute under attacker-selected routing without any adapter-level
route mutation.

`inspect_many()` now reuses the same host-owned iterator authority fence as
`inspect_batch()`. Iterator creation, each advance, terminal StopIteration and
direct process-control all preserve the pre-advance registration snapshot:
ordinary route drift is restored and fails closed; KeyboardInterrupt/SystemExit
remain unswallowed only after canonical routing is restored.

Regressions cover strict iterable-creation mutation, mutation between two real
sources, and direct KeyboardInterrupt after route replacement. No new format,
parser, decoder, report or chess authority is introduced.

This remains the same exact six-path canonical PR #2346 lineage.

### Bounded importer format-name metadata

A further Section-0.5 resource audit found that registration validated
`format_name` with `.strip()` before applying any raw size limit. Because the
exact string is adapter-owned metadata, an arbitrarily large whitespace-heavy
value could force unbounded linear host work before the registration boundary
rejected it.

The canonical registry now applies a 256-character raw format-name fence before
whitespace normalization. Exact non-text values still fail closed, empty or
whitespace-only names retain the existing rejection, and no route is published
on failure.

Regression coverage supplies a 257-character whitespace-only exact string and
requires the size failure to occur before the empty-name normalization path,
with the registry remaining empty afterward.

Exact successor blobs:
- `acs/import_registry.py`: `a6bf046fc2dbd53b06891d372cbfa7b476bc9836`
- `tests/test_import_registry.py`: `acec064ede353d90c131f2e172a4ad5482c59010`

This remains the same six-path PR #2346 Section-0 lineage and introduces no new
parser, decoder, report model, format authority or chess authority.



### Cross-thread registry-authority serialization

A concurrency audit found that the existing registration snapshot/restore contract
contained re-entrant adapter mutation but did not linearize a genuinely parallel
host call. Another thread could complete `register()` while an inspection was
running; the inspection would then detect drift and restore its older snapshot,
silently erasing a registration that had already returned success to the other
caller.

Canonical `ImportRegistry` now serializes all public routing-authority
operations with one re-entrant host lock. Inspection (single, strict multi-source
and non-aborting batch), registration/unregistration, lookup and public
registration projections share that authority. Adapter code may still call back
into the registry on the same thread; the re-entrant lock preserves the existing
drift-detection/restore behavior for those hostile callbacks. A different thread
cannot publish a route change until the active inspection transaction finishes,
so a successful concurrent registration cannot later be rolled back invisibly.

A deterministic threaded regression holds an inspection open, starts a parallel
registration, proves that registration remains blocked while inspection owns the
routing transaction, then releases inspection and proves both the original and
new routes are present. The inspection report remains bound to the original
route and source bytes.

Exact successor blobs:
- `acs/import_registry.py`: `8734852047bdc9540ea79c5d062c340a5258a45f`;
- `tests/test_import_registry.py`: `b1061a06a4f61ccfdcde89742a99730d87c6e33e`.

This remains the same exact six-path canonical PR #2346 lineage. It adds no
parser, decoder, ImportReport, format capability or chess authority.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI_AND_LIVE_REVALIDATION`


### Deterministic threaded mutation oracle

The first threaded regression proved final state but still used a short completion
wait as part of its blocking oracle. The acceptance evidence is now stronger and
symmetric.

For concurrent `register()`, the candidate importer exposes a format-name
property that sets an event only when host registration has actually crossed the
authority lock and begun metadata observation. While inspection is held open,
that event must remain unset; after release it must become set and the new route
must persist.

For concurrent `unregister()`, an observed registry subclass marks entry into
the mutation helper. The helper is unreachable while inspection owns the routing
transaction, then runs after release; the in-flight report remains valid and the
route is removed only afterwards.

This removes a timing-only interpretation from the threaded acceptance oracle
and covers both publication directions without changing runtime semantics.

Exact updated test blob:
- `tests/test_import_registry.py`: `aff0a87a2c4161a7bd2ab6bce5e21bd2b3fefb2b`.

This remains the same six-path PR #2346 lineage.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI_AND_LIVE_REVALIDATION`

### Passive payloads inside exact built-in OSError diagnostics

A final diagnostic-boundary audit found that checking the exception object's
exact type was not sufficient to make all of its attributes passive. Python's
exact built-in `OSError` accepts an arbitrary third constructor argument and
stores it as `filename` without coercion. An adapter could therefore raise an
ordinary exact `OSError` whose filename object implements active
`__fspath__` / `__str__` hooks. The batch renderer then passed that object
to `report_safe_name()`, manufacturing provider code execution during error
reporting; a provider-raised `KeyboardInterrupt` there could escape ordinary
per-source isolation even though the adapter itself raised only `OSError`.

The canonical registry now treats `filename` / `filename2` as reportable
only when each payload is an exact passive `str` or `bytes`. Any other
payload is ignored and the already host-owned source safe-name is used instead.
Exact built-in errno evidence remains available. No provider path/string hook is
executed merely to construct diagnostics.

A deterministic regression raises exact built-in `OSError(5, ..., payload)`
with a payload whose `__fspath__` and `__str__` both raise
`KeyboardInterrupt`. Batch preflight must execute zero payload hooks, publish
bounded source-scoped filesystem evidence, and continue to a later valid source.

Exact successor blobs:
- `acs/import_registry.py`: `300ffdcec826983e181590961150728ed79f315e`;
- `tests/test_import_registry.py`: `380e30f28bc691df9eb76fee129e2e9d1fd5846c`;
- focused qualification workflow:
  `5a2bea96cf96b0b0db217d962410fc67c1d17a0e`.

This remains the same exact six-path canonical PR #2346 lineage and introduces
no parser, decoder, ImportReport, format capability or chess authority.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI_AND_LIVE_REVALIDATION`

### Process-control mutation precedence in non-aborting batch preflight

Exact-head hosted qualification exposed a real retained regression:
`test_process_control_cannot_hide_source_mutation` failed because batch
preflight correctly converted source mutation into `SourceMutationError`, but
then treated that error as ordinary per-source evidence and continued. A direct
`KeyboardInterrupt` / `SystemExit` raised only after mutating or deleting
the source could therefore be downgraded into the normal non-aborting batch
path.

The canonical registry now preserves direct process-control as the explicit
cause of source-integrity failure. `inspect_batch()` continues to record
ordinary adapter/source mutation per source, but re-raises
`SourceMutationError` when its cause is direct process-control. This keeps
ordinary batch isolation intact while preventing control-plus-mutation from
being swallowed. If post-signal fingerprinting fails because the source was
deleted or became unverifiable, the original process-control signal remains
the explicit cause instead of being replaced by the verification exception.

The retained mutation regression now has executable semantics again, and a new
deletion regression proves that `SystemExit` + source deletion raises
`SourceMutationError`, aborts later batch work, preserves the later source
bytes, and retains `SystemExit` as the cause.

Exact successor blobs:
- `acs/import_registry.py`: `76be5deb299db67caaa4a3ed999936980b17eeb8`;
- `tests/test_import_registry.py`: `ed0c9515977847700e19ce9ea298795a3c21512c`;
- focused workflow: `4dcafa3b0ef03da5b3d3e79812f58f6449242a5c`.

This remains the same six-path PR #2346 Section-0 lineage and introduces no
new format, parser, ImportReport, capability or chess authority.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI_AND_LIVE_REVALIDATION`

### Cooperative Cancel mutation precedence in non-aborting batch preflight

A follow-up audit found that the process-control repair did not cover the
project's trusted cooperative `SourceReadCancelledError` signal. If an adapter
mutated the source and then raised Cancel, `_inspect()` correctly converted the
integrity violation into `SourceMutationError`, but batch preflight treated
that wrapper as ordinary per-source evidence because Cancel subclasses
`Exception`. If the adapter deleted the source, fingerprint verification also
replaced Cancel as the explicit cause. Either path could therefore continue to
later sources after the caller had cancelled.

The canonical registry now preserves cooperative Cancel as the explicit cause
of mutation/unverifiable `SourceMutationError` and aborts the batch whenever
that trusted cause is present. Ordinary source mutation without cancellation
remains bounded per-source evidence. Two deterministic regressions cover both
changed bytes and deletion, assert the retained Cancel cause, and prove that no
later source is inspected.

Exact successor blobs:
- `acs/import_registry.py`: `bc4188937966d4bacdf56df98a6735bd505d7def`;
- `tests/test_import_registry.py`: `878e00578f81f2a966e4949cdd4b2aded7cc9ab7`;
- focused workflow: `5078455b4802367c62deae03dc02c11b727c7f1e`.

This remains the same six-path PR #2346 lineage and changes no parser, decoder,
ImportReport schema, capability or chess authority.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI_AND_LIVE_REVALIDATION`

### Host-owned accepted ImportReport snapshot

The successful registry boundary previously validated an exact passive
`ImportReport` and then returned the adapter-owned object itself.
`ImportReport.records` and `global_warnings` are intentionally mutable while
an adapter assembles evidence, so an adapter retaining that object could rewrite
already accepted evidence after validation.

The registry now reconstructs a host-owned accepted snapshot after validation:
the `SourceFingerprint`, every `ImportedRecord`, the records list and global
warnings list are detached from adapter-owned aliases. Format identity and
source provenance are checked against this accepted snapshot and callers receive
that snapshot, not the adapter's retained object graph.

A regression retains the adapter's original report, then after `inspect()`
mutates its source fingerprint and record via retained references, changes its
format label, clears its records and rewrites its global warnings. The accepted
report remains valid, unchanged and bound to the original immutable source.

Exact successor blobs:
- `acs/import_registry.py`: `1a95d321d1c965567cd13d53355597b3b9589280`;
- `tests/test_import_registry.py`: `e08c5d14e58ed1433aa496477ef0f222546edeee`;
- focused qualification workflow: `6e01082f3ca2e06133f6b6dc72036e0ca4b95bc9`.

This remains the same exact six-path canonical PR #2346 lineage. No parser,
decoder, ImportReport schema, format capability or chess authority is added.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI_AND_LIVE_REVALIDATION`
