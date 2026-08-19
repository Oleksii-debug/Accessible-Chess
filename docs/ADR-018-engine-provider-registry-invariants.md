# ADR-018: Engine provider registry invariants

Status: accepted as a hardening addendum to ADR-001.

## Context

The provider descriptor called `.strip()` on unvalidated values and accepted
truthy capability containers without checking their type or members. Because
`EngineCapability` is a string enum, raw text such as `"analysis"` could pass
membership checks in filter and requirement arguments.

Provider creation accepted any runtime-protocol match, including a provider
class rather than an instance. Invalid descriptor, factory, selector, and output
failures otherwise surfaced through incidental attribute or enum behavior.

## Decision

1. `EngineProviderDescriptor` requires an exact lowercase ASCII provider slug,
   non-empty single-line title, and non-empty `frozenset` of
   `EngineCapability`. Provider IDs allow letters, digits after the first
   character, underscore, and hyphen.
2. Display-title surrounding whitespace is normalized once. Provider identity
   remains immutable and never normalizes at descriptor creation.
3. Descriptor validation uses stable `EngineContractError(INVALID_CONFIG)` for
   scalar, container, member, identity, and title failures.
4. Registration requires a real descriptor and callable lazy factory before
   mutating either registry map. Falsey callable factories remain valid and are
   retained exactly.
5. Lookup preserves the existing bounded convenience of outer-whitespace
   removal and case folding, then requires the canonical ASCII slug. Non-text or
   malformed lookup identity fails with `INVALID_REQUEST`.
6. Capability filters and create requirements accept only
   `EngineCapability` or `None`. Raw strings fail before iteration or factory
   execution even when their text equals an enum value.
7. Factory output must be a non-class full `ChessEnginePort` with callable
   analysis, best-move, and close operations. Incompatible output fails with
   `INVALID_PROVIDER` and does not remove or replace the lazy factory, so a
   later creation request can retry.

## Compatibility

Lazy registration, insertion-order listing, case-insensitive lookup, capability
filtering, pre-factory requirement checks, explicit unregister, duplicate-ID
protection, and caller ownership of created providers remain unchanged. Inputs
that relied on Python attribute errors, mutable/non-frozen capability
containers, string-enum equality, Unicode lookalikes, punctuation outside the
slug grammar, or class-as-provider output now fail explicitly.

## Ownership boundary

The registry owns immutable provider metadata and lazy factories only. Every
successful `create()` transfers the new provider instance to its caller; the
registry does not cache or close it. Runtime singleton/process ownership remains
with `StockfishRuntime` or another composition component.

## Release boundary

This change does not discover or install plugins, instantiate a provider during
registration/listing, activate engine UI, launch a binary, alter packaging,
touch QA-owned workflows, merge Stage 1, create a candidate ZIP, or claim NVDA
verification. Stage 2 remains blocked while the current candidate is QA-owned.
