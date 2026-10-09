# ADR-002: Registration-based notation and semantic-sound extension points

Status: accepted for Worker 2 Engine/Core foundation.

## Context

Issue #7 requires new notation/localization profiles and sound/event outputs to be addable without editing unrelated chess or presentation code. The canonical SAN formatter and semantic `SoundEvent` policy already exist, but there was no explicit composition-root registration contract for additional profiles or output sinks.

## Decision

Add two small presentation-neutral registries:

- `NotationProfileRegistry` owns stable profile IDs, descriptors and formatter registrations. Built-ins delegate to `acs.notation.format_san`; they do not duplicate notation rules.
- `SoundEventSinkRegistry` owns named output-sink registrations and dispatches stable `SoundEvent` values. Output-adapter failures are isolated into delivery reports so infrastructure failure cannot mutate or invalidate chess state.

Both registries contain no WebView2, filesystem, audio API, database, subprocess or provider-specific implementation.

## Consequences

New notation profiles and sound/event adapters can be registered at the composition root. Existing chess rules, notation parsing, semantic event selection and UI contracts remain stable. Infrastructure chooses concrete playback/rendering implementations. Built-in notation profiles remain protected from accidental unregistration.
