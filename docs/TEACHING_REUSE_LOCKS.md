# Teaching/Classroom Reuse Locks

Research date: 2026-08-16.

These are vetted candidates, not automatic runtime dependencies. Adoption requires adapter boundaries, tests, attribution and a package-level license review.

## LiveKit server

- Upstream: `livekit/livekit`
- Tag: `v1.13.1`
- Commit: `46c4309554d37d23ee8da88a8a7e02a68fba09c1`
- License: Apache-2.0
- Intended use: separate realtime media service behind `AudioRoomPort` / future classroom realtime adapter.
- Relevant capabilities verified from upstream/docs: multi-user WebRTC SFU, audio/video/data, JWT room permissions, moderation APIs, participant identity/name/metadata, publish permissions, server-side track mute, participant removal, UDP/TCP/TURN connectivity.
- Product policy: first Accessible Chess classroom slice enables microphone audio and data only. Camera publishing remains disabled until a later video feature.

## coturn

- Upstream: `coturn/coturn`
- Tag: `4.12.0`
- Annotated tag object: `66755283464837c9ab3625051b0590f388b76a17`
- Commit: `bfacd81627197c572b8678842110846d6de8479c`
- License: BSD-3-Clause style license in upstream LICENSE.
- Intended use: optional TURN/STUN infrastructure for NAT traversal if LiveKit embedded/external TURN configuration requires it.
- Integration mode: separate infrastructure service, never chess-domain code.

## gchessboard

- Upstream: `mganjoo/gchessboard`
- Tag: `v1.4.0`
- Annotated tag object: `6d1af9d510736e400a24fff5b18c5d4684cd9b71`
- Commit: `91323aebefa6efcd6647d1a4bc274a9697b377a1`
- Code license: MIT.
- Strengths: dependency-free Web Component, click/drag/keyboard interaction, rudimentary screen-reader support, extensive CSS customization, replaceable piece sets and custom square content.
- Critical asset caveat: bundled piece SVGs are adapted from Cburnett/Wikimedia and are CC BY-SA 3.0. Code license and artwork license must be treated separately.
- Intended use: reference/differential candidate for future shared web visual board; not authoritative chess state. If adopted for commercial distribution, prefer Accessible Chess original/permissively licensed piece assets unless a deliberate CC BY-SA asset decision is made.

## Adoption rules

1. No external board owns legal chess state; current shared Core remains authoritative.
2. Network/media provider types do not leak into domain DTOs.
3. No API secrets are stored in desktop client code.
4. Classroom token issuance is server-side.
5. Third-party art/audio provenance is audited independently from code libraries.
6. Any adopted dependency is added to `THIRD_PARTY_NOTICES`/inventory with exact version, license and update owner.
7. Accessibility behavior must be tested with our semantic/UI contracts; upstream accessibility claims are not sufficient for `NVDA VERIFIED`.
