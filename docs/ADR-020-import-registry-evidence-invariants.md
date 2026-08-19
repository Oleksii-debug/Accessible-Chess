# ADR-020: Import registry and evidence invariants

Status: accepted as a hardening addendum to ADR-0001.

## Context

`ImportRegistry` promises read-only source inspection and non-aborting batch
evidence. The original exception path did not fingerprint the source after an
adapter raised, so a decoder could mutate or delete a file and hide that fact
behind its own exception. A normal `RuntimeError` also escaped `inspect_batch()`
instead of becoming evidence for that source.

Importer metadata, suffixes, fingerprints, records, and reports additionally
accepted Python scalar/container coercion or mutable aliases. A returned report
was the same mutable instance owned by the adapter, and its format identity was
not checked against the registered adapter.

## Decision

1. An importer is a non-class instance with stable single-line format identity,
   an exact tuple of unique canonical ASCII suffixes, and a callable inspection
   operation. Registration validates all metadata before changing routing.
2. `replace` is an exact boolean. Replacement remains explicit and atomic.
   Unregister is identity-based and reports an unknown instance instead of
   silently doing nothing.
3. Source paths accept only text or `Path`; plural operations snapshot and
   validate the whole iterable before inspecting the first source.
4. Inspection fingerprints the source before and after every adapter call,
   including calls that raise. Mutation or disappearance has priority over the
   adapter exception and is reported as `SourceMutationError`.
5. An unchanged-source adapter exception is wrapped as
   `ImporterInspectionError`. Batch inspection records every ordinary adapter,
   routing, validation, provenance, and filesystem exception and continues.
   Unprintable exception objects receive a stable fallback message.
6. Adapter output must be `ImportReport`, match the registered format name, and
   contain valid typed evidence for the exact inspected bytes. The registry
   returns a detached report snapshot rather than the adapter-owned list
   containers.
7. Fingerprint size/hash/suffix, record quality/game ID/warnings, report source
   and containers, registration DTOs, and batch DTOs enforce exact immutable or
   detached shapes. Raw string enums, bool-as-int values, mutable warning
   tuples, invalid digests, and contradictory delivery shapes fail explicitly.
8. Fingerprint chunk size is an exact positive integer; zero can no longer
   produce a false empty-file digest for a non-empty source.

## Compatibility

Case-insensitive suffix routing, optional leading dots in importer declarations,
explicit verified-adapter replacement, strict and non-aborting batch modes,
source fingerprint semantics, PGN and ChessBase-placeholder adapters, quality
counts, and registration ordering remain available. Inputs that relied on
implicit object conversion, mutable suffix containers, silent unknown
unregister, partial invalid-path preflight, malformed reports, or hidden
mutation on adapter failure now fail closed.

## Ownership boundary

The registry owns suffix routing and detached inspection evidence. Adapters own
their internal decoder state but never source bytes; callers own returned report
copies. Recognition remains distinct from verified decoding, and no importer is
discovered or activated automatically.

## Release boundary

This change does not activate import UI or plugins, decode proprietary formats,
write source data, alter ACSDB migrations, touch QA-owned workflows or harnesses,
merge Stage 1, create a candidate ZIP, or claim NVDA verification. Stage 2
remains blocked while the current candidate is QA-owned.
