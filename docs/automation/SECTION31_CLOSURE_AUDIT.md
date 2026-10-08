# Section 31 closure audit — Accounts, authentication, workspaces and cloud synchronization

Canonical plan revision: `ACCESSIBLE CHESS — SECTION PLAN ДО ПОВНІСТЮ ЗАВЕРШЕНОГО ПРОДУКТУ`.

## Canonical scope

Section 31 depends on the privacy/security and authenticated-server boundaries of Sections 29–30 and requires:

1. authentication/session infrastructure outside chess core;
2. user/workspace isolation and authorization;
3. cloud Library/progress/Classroom state, notifications and backups;
4. sync conflict/migration/reconnect policy;
5. no static backend/API secret in desktop/browser clients.

## Implemented authority

`acs/account_cloud.py` is a server-side, chess-agnostic account/cloud authority.

### 31.1 Authentication/session infrastructure

- A deployment verifier is injected into `AccountCloudService`; untrusted authentication proof is never treated as identity directly.
- Only exact `VerifiedIdentity` output from that verifier can establish a session.
- Sessions use high-entropy opaque bearer values; persistent storage contains only SHA-256 token hashes.
- Sessions have bounded TTL, restart-safe persistence and explicit revocation.
- Authentication failures are generic and do not echo proof/token material.

### 31.2 Workspace isolation and authorization

- Every workspace operation re-authenticates the bearer and re-authorizes membership.
- Roles are `owner`, `admin`, `editor`, `viewer`; owner assignment cannot be forged through the ordinary member API.
- Cross-workspace resource, notification and membership access fails closed.
- SQLite foreign keys and workspace-scoped compound keys preserve tenant boundaries.

### 31.3 Cloud state, notifications and backups

- Durable versioned resource storage is provided for exactly `library`, `progress` and `classroom`.
- Notifications are workspace- and recipient-scoped.
- Backups are canonical JSON snapshots, SHA-256 digest bound, and intentionally exclude sessions/bearer material.
- Restore is owner-only, integrity checked and guarded by exact workspace revision CAS.

### 31.4 Conflict, migration and reconnect

- Every resource write uses exact entity-revision CAS.
- Stable operation IDs provide exact-retry idempotency and reject semantic reuse.
- Workspace revisions provide a reconnect cursor and ordered sync pulls; future/ahead cursors fail closed.
- Schema downgrade is forbidden. Migration advances exactly one schema version at a time and is guarded by source entity revision.

### 31.5 No static backend/API secret

`PublicClientConfig` contains only `server_base_url` and `public_client_id`; unknown secret/API-key/private-key/token fields are rejected. Production origins require HTTPS, with plain HTTP accepted only for literal loopback development endpoints. Server-side session bearer values are runtime credentials, not embedded client secrets.

## Dependency and authority treatment

This closure does not create a second chess rules, Position, PGN, GameTree, Library parser, Classroom chess-state, or engine authority. Section 31 persists opaque versioned cloud payloads and delegates identity proof verification to the authenticated deployment boundary.

The repository owner explicitly requested terminal one-run closure of Sections 31–32. If Sections 29–30 are not yet terminal in the durable ledger at merge time, this Section 31 closure is an owner-directed out-of-order closure against the stated interfaces above. Later Section 29/30 integration may reopen Section 31 only if it demonstrates an actual incompatibility or regression in this pinned contract; ordinary reimplementation/re-audit is forbidden.

## Qualification

Focused deterministic contract:
- authentication proof verification, token hashing, revocation and expiry;
- durable restart-safe session storage without plaintext bearer persistence;
- tenant/workspace role isolation;
- Library/progress/Classroom CAS and idempotent writes;
- reconnect cursor behavior;
- exact one-step migrations;
- recipient-scoped notifications;
- digest-bound backup and CAS restore;
- secret-free client configuration;
- caller-mutation detachment.

Isolated execution of the exact source/test content before publication: **10/10 tests PASS**.

The dedicated GitHub gate compiles and runs the focused contract on Ubuntu 24.04 and Windows 2025, checks the exact four-path candidate scope, proves no chess-authority import, and verifies the public client configuration shape. A queued/unstarted hosted run is recorded as unavailable rather than GREEN under Simplified Section Closure Protocol v3; any executed attributable failure blocks terminal closure.

`HUMAN_TESTED=NO`
`NVDA_VERIFIED=NO`
