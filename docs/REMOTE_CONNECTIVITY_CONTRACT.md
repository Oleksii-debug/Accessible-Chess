# Accessible Chess remote connectivity contract

Status: **PROPOSED / COORD+D10 APPROVAL REQUIRED**  
Scope: post-freeze Full Product only  
Release impact: none until explicitly approved and selectively integrated  
Base used for this proposal: `#441@0b8fa275890cd82565eceece71063cb4353ea8c8`

## Purpose

Define the minimum Product contract that must exist before the already-registered actions `remote.connect`, `remote.reconnect`, and `remote.leave` can become reachable in a production V2/full-product composition.

This document deliberately does **not** choose a network transport, server product, hosting provider, authentication vendor, WebSocket library, or deployment topology. Those are implementation decisions that must satisfy this contract after one owner is assigned.

## Existing canonical authorities that must be reused

- `acs.remote_session.RemoteSessionLog` remains the canonical deterministic presentation-neutral remote replay model.
- `RemoteSessionEvent.event_id`, strict sequence ordering, replay validation, bounded event count and digest-bound snapshots remain authoritative for replay integrity.
- D10 education workspace/checkpoint persistence remains the durable checkpoint authority. A network implementation must hand off to it rather than create a second remote persistence model.
- `acs.classroom_presentation.RemoteLessonPresenter` remains presentation-only. It may project connection/recovery state and dispatch stable action IDs, but it must not own credentials, transport sockets, chess state, or persistence.
- `acs.full_product_actions` remains the stable action catalog. Presence of an action ID is not evidence that a network capability is implemented or safe to expose.

## Capability rule

Until an approved network provider satisfies this contract, production composition MUST treat remote network connectivity as unavailable and MUST NOT expose `remote.connect`, `remote.reconnect`, or `remote.leave` as a completed capability.

A UI may describe the capability as unavailable/deferred, but it must not simulate success, fabricate a session, or reuse the deterministic replay log as if it were a live transport.

## Security and identity contract

A connection implementation MUST:

1. Authenticate the participant before accepting any session mutation.
2. Bind one authenticated principal to an explicit Product role for the target lesson/session.
3. Verify that role and membership against canonical lesson/classroom authority before accepting participant-scoped events.
4. Keep access tokens, refresh tokens, cookies, passwords, private keys and equivalent credentials outside repository content, release ZIPs, user-facing snapshots, normal logs and NVDA announcements.
5. Treat browser/WebView payloads as untrusted presentation input. Browser content must not choose authoritative actor identity, role, sequence, session revision, checkpoint digest or credential material.
6. Minimize personal data. Network envelopes should carry stable opaque identifiers required by the domain contract, not names, local paths or unrelated classroom records.
7. Fail closed on expired/revoked credentials, unknown roles, role changes, removed participants and session identity mismatch.

Credential storage/provider choice is outside this contract, but it MUST use an operating-system or separately configured secure credential boundary; plaintext secrets in repository files or packaged defaults are forbidden.

## Versioned transport-neutral envelope

Whatever transport is selected, every application message accepted by the Product MUST be representable as a bounded, versioned envelope with at least these semantic fields:

- protocol/version identifier;
- stable session identifier;
- authenticated actor identifier and verified role derived from the trusted connection context, not trusted from browser text;
- message kind from a closed allowlist;
- monotonically ordered session sequence or an explicitly defined acknowledgement/control class that cannot mutate replay state;
- deterministic message/event identity for dedupe/idempotency;
- bounded payload validated by the owner domain before publication;
- when resuming, the last accepted sequence and canonical checkpoint/snapshot digest needed to prove the resume point.

Unknown protocol versions, unknown message kinds, duplicate-key encodings, oversized envelopes/payloads, invalid Unicode, malformed identifiers and non-canonical numeric values MUST be rejected before domain mutation.

The contract does not require JSON. If JSON is used, duplicate object keys and non-finite numbers must fail closed.

## Ordering, dedupe and idempotency

The network layer MUST preserve the stronger canonical replay guarantees rather than weaken them:

- accepted state-mutating events are applied exactly once at the Product boundary;
- exact retransmission is idempotent;
- same identity with different content is a conflict;
- stale sequence is rejected;
- unexplained gaps are not silently filled or reordered into a different history;
- bounded buffering may be used only if the selected protocol defines it explicitly and the Product can prove the resulting canonical order before publication;
- retry after an uncertain send must not create a second logical event.

`RemoteSessionLog` remains the final deterministic replay validator for remote lesson events that map to its domain.

## Connect contract

A successful `remote.connect` implementation MUST NOT report connected until all of the following are true:

1. authentication succeeded;
2. participant membership/role was authorized for the lesson;
3. a single canonical session identity is established;
4. protocol version negotiation is complete;
5. the initial canonical checkpoint/replay state is validated;
6. local durable handoff requirements are satisfied or the Product has an explicitly safe read-only state;
7. the UI state can be projected without exposing secrets/internal transport details.

Any failure before that point remains disconnected/error and must be retryable only when retry is safe.

## Reconnect/resume contract

Reconnect MUST be a resume operation, not an implicit new session.

It MUST bind:

- the same canonical session identity;
- the authenticated participant/role currently authorized for that session;
- the last locally accepted sequence;
- the last durable canonical checkpoint or snapshot digest;
- the server/peer resume point under the approved protocol.

Reconnect MUST fail closed on divergent same-sequence content, stale checkpoint identity, removed membership, changed role that invalidates pending actions, replay from an older accepted generation, or an unsupported protocol/version transition.

If automatic reconciliation cannot prove one canonical history, the Product must surface a concise recoverable conflict state and require an explicit safe path; it must not guess which history wins.

## Leave/close contract

`remote.leave` MUST:

- stop new local mutations for the departing connection;
- complete or safely cancel in-flight work under a bounded timeout;
- persist any required final canonical checkpoint before declaring a durable close, or explicitly report that durable close failed;
- prevent later background callbacks from republishing state into a closed/replaced generation;
- release network resources deterministically;
- clear credential/session material that is scoped only to the departed session.

A closed canonical remote session must not silently reopen through delayed callbacks or retries.

## Offline, timeout and recovery behavior

The implementation MUST define bounded behavior for:

- initial connection timeout;
- read/write timeout;
- disconnect during an event send;
- disconnect after remote acceptance but before local acknowledgement;
- process restart while disconnected/reconnecting;
- network unavailable at application startup;
- server/peer unavailable;
- authentication expiry/revocation;
- provider shutdown during application close.

Retries require bounded delay/backoff and cancellation. No unbounded thread, task, reconnect loop, queue or memory buffer is permitted.

Offline mode must preserve non-remote chess, PGN, Library, Books and Training functionality. Failure of remote connectivity must not make the rest of Accessible Chess unusable.

## Persistence boundary

Network code MUST NOT introduce a second durable classroom/remote database.

When live remote state becomes durable Product state, publication must use the canonical D10 education/checkpoint authority and its CAS/atomicity rules. A failed durable publication must not be presented as successfully checkpointed.

Transport-owned ephemeral queues/cursors may exist in memory or provider-specific storage only when their lifecycle, bounds and privacy contract are explicit and they cannot become a second source of Product truth.

## Presentation and accessibility contract

Connection state must be expressible through the existing semantic presentation states: disconnected, connecting, connected, reconnecting and error, extended only through owner-approved typed state if the existing enum is insufficient.

Essential requirements:

- keyboard-only connect/reconnect/leave path;
- no mouse-only recovery path;
- no color-only status;
- deterministic focus after connection, failure, reconnect and leave;
- concise user-facing error text with no token, URL credential, stack trace, provider internals, local path or raw protocol payload;
- status changes available through standard accessibility semantics without background live-region spam;
- normal text-editing shortcuts remain native in editable controls;
- sighted and blind users receive equivalent capability/state information.

Automated UIA evidence may prove semantics and keyboard operation, but MUST NOT set `NVDA_VERIFIED=true`. Only Oleksii's physical NVDA test may do that.

## Resource and abuse bounds

Before implementation is approved, the owner must state concrete limits for at least:

- maximum encoded message size;
- maximum domain payload size;
- maximum outstanding unacknowledged messages;
- maximum reorder/dedupe window if any;
- maximum reconnect attempts/window;
- maximum session lifetime or renewal behavior where relevant;
- timeout/cancellation bounds;
- per-session event/checkpoint compatibility with existing `MAX_REMOTE_EVENTS` and snapshot size bounds.

Exceeding a bound fails closed with a stable sanitized Product error.

## Logging and observability

Logs may contain bounded technical correlation identifiers, protocol version, sanitized state transitions, timing and error category. They MUST NOT contain credentials, cookies, authorization headers, full private classroom payloads, private student answers unless an explicitly approved protected audit requirement exists, or user-local filesystem paths in normal user-facing logs.

User-facing messages remain separate from diagnostic logs.

## Packaging and configuration

The Windows package MUST contain no embedded service credential or user token.

Environment/service endpoints and provider configuration must be externalized from code/package secrets and validated before use. A missing provider configuration must fail as capability unavailable, not crash the application.

If an external runtime/service dependency is required, the release manifest/notices and package validator must make that dependency and its version/license boundary explicit.

## Required automated acceptance before reachability

At minimum the eventual implementation owner must prove on the exact candidate head:

1. authentication/authorization allow and deny matrices;
2. actor/role spoof rejection at the browser/network boundary;
3. version/message-kind/schema/resource rejection;
4. duplicate/idempotent resend and same-id-different-content rejection;
5. stale/out-of-order/gap/replay rejection;
6. disconnect-before-send, disconnect-after-accept-before-ack and duplicate retry recovery;
7. reconnect from exact durable checkpoint and fail-closed divergent checkpoint;
8. revoked/expired credential and removed participant behavior;
9. bounded timeout/cancellation/shutdown with no orphan worker/task;
10. application restart/resume with canonical D10 persistence;
11. privacy/log redaction and no secret/package leakage;
12. Windows packaged runtime connect/disconnect/reconnect/leave journey using a deterministic test provider or approved test service;
13. keyboard/UIA state/focus/error recovery evidence;
14. broad regressions proving Board/engine/PGN/Library/Books/Training remain usable when remote is unavailable.

Real external-service evidence, if the final architecture depends on a real hosted service, must be separately scoped so tests do not require committing credentials.

## Human acceptance boundary

Physical Windows/NVDA acceptance remains a separate final gate after machine evidence. `HUMAN_TESTED` and `NVDA_VERIFIED` remain false until Oleksii tests the exact packaged candidate.

## Approval decisions still required

COORD + D10 must record before implementation begins:

- `REMOTE_NETWORK_AUTH_OWNER=<lane/PR>`;
- approved transport/provider architecture or an explicit transport abstraction plus the first supported provider;
- authentication/credential provider and secure storage boundary;
- protocol version identifier and compatibility policy;
- concrete resource/time/retry limits;
- endpoint/configuration policy;
- whether a hosted service is in release scope and its deployment/operations owner;
- test-service strategy for deterministic CI and packaged Windows acceptance.

Until those decisions are durable, this document is a requirements proposal only and remote network actions remain non-reachable production capabilities.
