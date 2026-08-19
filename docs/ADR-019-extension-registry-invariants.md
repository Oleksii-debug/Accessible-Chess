# ADR-019: Notation and sound extension-registry invariants

Status: accepted as a hardening addendum to ADR-002.

## Context

The notation and semantic-sound registries are composition boundaries for
future extensions. Their original lookup helpers coerced arbitrary Python
objects with `str()`, and string enums allowed raw text to pass event filters.
Descriptor containers and Boolean metadata were not validated exactly.

Sound batch dispatch also delivered earlier events before discovering an
invalid later item. A sink exception whose `__str__` failed could escape the
fault-isolation boundary instead of producing a delivery report.

## Decision

1. Profile and sink IDs are exact lowercase ASCII slugs. Descriptor titles are
   exact, non-empty, single-line text and are trimmed once for stable display.
2. Notation locales are optional normalized ASCII language tags. Built-in
   ownership metadata and the registry's `include_builtins` switch are exact
   booleans.
3. Descriptor and registration inputs are validated before either registry map
   changes. Falsey callable formatters and sinks remain valid and are retained
   exactly.
4. Lookup keeps the bounded convenience of outer-whitespace removal and case
   folding, then applies the canonical ASCII grammar. Non-text identities are
   rejected rather than coerced.
5. Notation formatting accepts a non-empty single-line text token. Provider
   output must also be non-empty single-line text; an invalid result does not
   unregister or replace the formatter, so a later call may retry.
6. Sound filters accept only a non-empty `frozenset[SoundEvent]` or `None`.
   Filter selectors and emitted values require actual `SoundEvent` members, not
   equal raw strings.
7. `emit_many()` snapshots and validates the full iterable before invoking any
   sink. Invalid later members therefore cannot cause partial delivery.
8. Delivery reports enforce exact non-negative counters, immutable typed
   failures, and `attempted == delivered + failures`. Adapter exceptions remain
   isolated even when their textual representation is broken.

## Compatibility

Built-in notation IDs and ordering, canonical formatter delegation,
case-insensitive text lookup, locale filtering, custom formatter/sink
registration, built-in removal protection, sound sink ordering, event filters,
and per-sink failure continuation remain unchanged. Inputs that relied on
Python object-to-text coercion, mutable filters, raw string events, malformed
locale/identity text, partial invalid batch delivery, or invalid provider output
now fail explicitly.

## Ownership boundary

The registries own immutable descriptors and callable references only. They do
not discover extensions, instantiate plugins, select chess events, own audio
resources, or translate notation rules. The caller owns formatter and sink
lifecycle; sound delivery failures are returned as immutable evidence.

## Release boundary

This change does not activate plugins, change UI or sound assets, alter
packaging, touch QA-owned workflows or harnesses, merge Stage 1, create a
candidate ZIP, or claim NVDA verification. Stage 2 remains blocked while the
current candidate is QA-owned.
