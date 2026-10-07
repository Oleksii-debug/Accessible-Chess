# Software Protection Security Sections 13–14 — Terminal Closure Audit

Canonical plan source: Google Drive document **ACCESSIBLE CHESS — SOFTWARE PROTECTION ARCHITECTURE AND SECURITY SECTIONS**. This is the separate software-protection workline and must not be confused with the main Accessible Chess numbered Product Section Plan.

## Closure identity

- Owner-directed closure date: 2026-10-07.
- Exact shipping base used to construct this candidate: `12cbc8883141b422719c715611fb1860fe0624d6`.
- Tracking issues: #2452 (Security 13) and #2453 (Security 14).
- Normal re-entry after integration: **FORBIDDEN**.
- Reopen only for a concrete demonstrated regression, invalidated closure evidence, materially changed security contract, or later dependency integration that demonstrably breaks this exact scope.

## Security Section 13 — Rollback / Clock Resistance v1

The closure adds `acs/entitlement_runtime_security.py` as a narrow consumer of a previously verified time-bounded lease. It does not mint/sign leases and does not create a second installation/device authority.

Implemented invariants:

1. Every protected lease observation carries a bounded installation ID, signed lease ID/nonce, signed issue time, signed server time and finite expiry.
2. The prior accepted authorization time is retained as a monotonic `effective_time_floor`; accepted authorization time never moves backward.
3. An obvious wall-clock rollback beyond the bounded five-minute skew tolerance fails closed.
4. A lease with an older issue time fails as stale replay.
5. An older signed server-time observation fails as stale replay.
6. A conflicting nonce at the same signed generation fails closed.
7. Durable state uses a monotonic generation anchor supplied by the protected/device-bound storage dependency. A state payload older than that anchor, or a missing payload behind a non-zero anchor, is treated as protected-state replay.
8. State publication is compare-and-swap. Concurrent stale writers, provider failures and false/unverifiable commit success fail closed.
9. The guard never lowers a previously accepted floor and never mutates user chess data.

Dependency seam: `ProtectedRollbackStateStore` deliberately requires the earlier security workline's protected/device-bound storage to keep its monotonic generation anchor independently from the sealed payload. This Section does not pretend that ordinary replayable plaintext storage is anti-rollback storage.

## Security Section 14 — Locked Shell and Safe Expiry

The closure converges the previously unintegrated #806/#813 entitlement hardening onto the live shipping authority and composes it with the rollback decision:

- `RemotePolicy.refresh_after` is an enforced TTL boundary.
- Signed `server_time` is a lower bound for entitlement evaluation.
- user-owned local `data.export` and `data.recovery` are explicit safety invariants, not paid grants;
- expired, revoked, update-required, unavailable, rollback/replay and protected-state failures lock premium capability fail-closed;
- locked state keeps these stable safe actions reachable:
  - `account.login`;
  - `account.recovery`;
  - `entitlement.refresh`;
  - `app.update`;
  - `help.open`;
  - `data.export`;
  - `data.recovery`;
  - `security.status`.
- `LockedShellDecision` and `ui_entitlement.semantic_contract()` both state `preserveUserData=true` / `destructiveAction=false`.
- UI projection remains presentation-neutral, keyboard/NVDA-compatible semantic state; no inaccessible mandatory modal or whole-page application role is introduced.

There is deliberately no destructive "self-defence": no deletion, encryption, corruption, quarantine of user files, or irreversible response to expiry/revocation/tamper suspicion.

## Exact bounded Product/Test blobs before closure-audit files

- `acs/entitlements.py` — `404c1670691d49e468be74e59bc502e08b5023f4`
- `acs/entitlement_runtime_security.py` — `a269ae9855b583477c93b142017c2fc485dd57c5`
- `acs/ui_entitlement.py` — `faf4cbbe728185bc3e9edd99bac3598213dd820c`
- `tests/test_entitlements.py` — `a0f717f0b0029aae6849867e87835e592ad59a51`
- `tests/test_entitlement_runtime_security.py` — `1b3351c5d3674b6d948e607c3cb4812e79de66dc`
- `tests/test_ui_entitlement_integration.py` — `21f11cbc34138de7b3e51a16f87e02be7f29767f`
- `.github/workflows/security-sections13-14.yml` — `51fc140d4fa357cdd366f7fc063f6ec48ea0bbb3`

The candidate was ahead-only / behind=0 from the exact construction base before these audit files, with exactly seven bounded implementation/test/workflow paths.

## Qualification contract

The dedicated dual-OS gate compiles and executes:

- `tests.test_entitlements`;
- `tests.test_entitlement_runtime_security`;
- `tests.test_ui_entitlement_integration`;

on Ubuntu 22.04 and Windows Server 2025, then statically proves the recovery action set and absence of destructive user-data operations in the Security 13/14 authority.

Queued/unstarted hosted jobs are not called GREEN. Under the repository Simplified Section Closure Protocol v3, genuine hosted-runner unavailability may be recorded as external unavailability after repository-controllable work and exact static/readback evidence are complete; any executed attributable RED blocks closure.

## Threat-model boundary

This is rollback/clock resistance **v1**, not an impossible claim that client DRM cannot be patched. A sufficiently privileged attacker who can replace executable code and also defeat the protected monotonic store remains outside this local v1 guarantee. Later security sections add stronger integrity, online and server-authorized layers. The concrete Section-13 claim is narrower and testable: simple local clock rollback and detectable stale lease/state replay are not normal authorization bypasses.

## Terminal result

`SECURITY_SECTION_13_DONE=YES`  
`SECURITY_SECTION_14_DONE=YES`  
`SECURITY_SECTION_13_TERMINAL_SKIP=YES`  
`SECURITY_SECTION_14_TERMINAL_SKIP=YES`  
`NORMAL_REENTRY=FORBIDDEN`  
`USER_DATA_DESTRUCTIVE_DEFENCE=NO`
