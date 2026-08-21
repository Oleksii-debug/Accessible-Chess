# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0002
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T01:00:00+03:00
SNAPSHOT_SEMANTICS: Workers already running before the effective wave must ignore this directive until their next invocation.

## DEV1 — DIRECTIVE 0002
STATUS: accepted and integrated; no speculative Product churn.
NEXT WORK: remain in evidence/regression mode unless a concrete UI/accessibility/action-routing regression is returned by integration or DEV5 reconciliation. Pay particular attention to board bridge dependency/readiness ordering and retry/idempotency semantics while DEV4 security changes are being reconciled. Do not overwrite the accepted central routing semantics.

## DEV2 — DIRECTIVE 0002
STATUS: terminal package at 8b74ef94c91dbed8d9dfc73bcb39a9aa956a9afe; eligible for DEV5 intake after current DEV4 reconciliation reaches a validated final-state candidate.
NEXT WORK: no speculative churn. Preserve authoritative empty-square attackers() semantics, abbreviated FEN compatibility, en-passant provenance and atomic failure-without-partial-mutation. If new integration evidence exposes a concrete regression, provide a narrow fix and exact terminal evidence; otherwise remain stable.

## DEV3 — DIRECTIVE 0002
STATUS: final Stage1 backend package accepted and already integrated into e24ff85ff9a6ad3ea19d33f7035526c7bcdf2c8e.
NEXT WORK: regression/evidence only unless a new concrete backend defect is reproduced. Do not duplicate integrated lifecycle/takeback/sound hardening.

## DEV4 — DIRECTIVE 0002
STATUS: terminal source package a4209d005ea0a1476f8eafb4822f4d39ac50ee5a remains HOLD as a whole-branch intake. DEV5 has started final-state reconciliation on manual5/dev5-reconcile-dev4-20260822.
NEXT WORK: do not mutate Product unless DEV5 returns a concrete DEV4-owned defect. Treat these reconciliation corrections as authoritative for next evidence: explicit settings schema_version=0 must be rejected; missing schema key alone is the legacy path. Continue to preserve accepted DEV1 board-bridge semantics. Lane-only dev4-package-security-ci is evidence, not an integration artifact. Nuitka compilation report remains CI-only and must not enter user package content.

## DEV5 — DIRECTIVE 0002
First read exact conclusions for validation PR #66 head 09156cbca6bba0b6ba833cf3c867b127345014cf: Saturation run 32526672849 and UI Semantic run 32526672863. Do not move manual5/integration-20260821 unless the exact candidate has the required GREEN evidence. Continue DEV4 reconciliation in recoverable slices, then run a completed DEV4 final-state candidate through exact gates before integration. Only after DEV4 is settled, validate DEV2 terminal SHA 8b74ef94c91dbed8d9dfc73bcb39a9aa956a9afe against the resulting integration state. Never merge PR #54 or frozen release refs. Never reuse an old rejected ZIP. A fresh Windows candidate requires the full machine release chain. NVDA_VERIFIED remains NO until Oleksii personally verifies that exact fresh candidate.
