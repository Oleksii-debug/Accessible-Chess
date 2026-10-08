# Section 30 — Server application boundary and authenticated API foundation

Status: terminal closure candidate for the canonical Section Plan.

Canonical scope:
- 30.1 server adapter over real application commands/queries;
- 30.2 durable session/workspace/entity IDs and versioned DTOs;
- 30.3 server-side validation of every state-changing request;
- 30.4 durable jobs with progress/cancel/retry/restart;
- 30.5 no chess/domain duplication in the server layer.

## Dependency boundary

Section 30 consumes the terminal Section-29 `ProductionSecurityPolicy` plus an exact
`SecurityGate`. Composition fails before serving any request if that gate is absent,
stale or mismatched. This is the executable 29.5 prerequisite.

Authentication/account issuance remains Section 31. Section 30 accepts only an
`AuthenticatedPrincipal` supplied by trusted server middleware. Actor, workspace and
session identity are never accepted from the JSON request as authority.

## Application adapter

`build_application_operations(snapshot=..., dispatch=...)` binds the already-existing
application snapshot and action-dispatch seams. The server neither parses chess
notation nor owns Board/GameTree/Library/Books/Training/Classroom state.

## Versioned DTOs and state-changing validation

API schema version is explicit. Requests carry bounded request/workspace/operation IDs,
JSON payload and optional `EntityRef(entity_id, revision)`. Every state-changing
request requires entity ID + expected revision before the canonical handler can run.
Cross-workspace requests fail closed. Every operation declares required permission and
the Section-29 security request is checked before delegation.

## Heavy jobs

`SqliteJobStore` provides durable generic job records independent of chess semantics:
stable job/request/workspace/operation/entity IDs, request-ID idempotency, queued /
running / succeeded / failed / cancelled states, monotonic progress, cancellation,
retry, and deterministic restart recovery of interrupted running jobs.

## Authenticated API transport

`AuthenticatedServerAsgi` is a strict provider-neutral ASGI foundation:
- trusted middleware injects `AuthenticatedPrincipal` into scope state;
- bounded UTF-8 JSON with duplicate-field rejection;
- `/v1/query`, `/v1/command`, `/v1/jobs/status`, `/v1/jobs/cancel`;
- no account/session issuance, bearer-token parser or provider SDK;
- no-store/nosniff/no-referrer responses and safe generic errors.

## Qualification

Dedicated dual-OS CI compiles Sections 29/30 and proves real application delegation,
mutation revision enforcement, cross-workspace/permission rejection, versioned DTOs,
Section-29 hard gating, durable enqueue/progress/cancel/retry/restart and the absence
of chesscore/GameTree/notation/FEN legality authority in the server layer.

Manual deployment, account-provider onboarding and human NVDA validation remain
later/final acceptance and do not alter internal Section-30 completion under
Simplified Section Closure Protocol v3.
