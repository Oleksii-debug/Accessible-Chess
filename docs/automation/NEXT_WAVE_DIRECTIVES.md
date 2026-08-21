# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0003
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T02:00:00+03:00
SNAPSHOT_SEMANTICS: Workers already running before the effective wave must ignore this directive until their next invocation.

## DEV1 — DIRECTIVE 0003
STATUS: accepted/integrated; canonical Release UI/accessibility/action-routing semantics preserved through final Stage1 integration 0fa442330bc2bb03636ff9297512da4c29e38684.
NEXT WORK: evidence/regression only unless a concrete UI/accessibility defect is reproduced. Preserve board.current central routing, apiAction/document prerequisites, readiness-after-render ordering, retryability and reinjection idempotency. Do not churn accepted board bridge behavior speculatively.

## DEV2 — DIRECTIVE 0003
STATUS: terminal pre-cutoff continuation 8b74ef94c91dbed8d9dfc73bcb39a9aa956a9afe has been selectively integrated through validated DEV5 head 0fa442330bc2bb03636ff9297512da4c29e38684.
NEXT WORK: evidence/regression only unless a new concrete core/history/position defect is reproduced. Preserve all-controller empty-square attackers semantics, side-to-move defender projection, 4/5/6-field FEN compatibility, exact scalar validation, atomic rejection and en-passant double-push provenance.

## DEV3 — DIRECTIVE 0003
STATUS: accepted Stage1 backend package remains represented in final integration 0fa442330bc2bb03636ff9297512da4c29e38684. Post-cutoff handoff mutations from the 00:08 wave were deliberately not consumed by DEV5.
NEXT WORK: remain within assigned backend lane. Any next-wave terminal delta must be evaluated against 0fa4423; do not assume work performed during the prior wave was already integrated merely because its handoff advanced later.

## DEV4 — DIRECTIVE 0003
STATUS: pre-cutoff terminal source a4209d005ea0a1476f8eafb4822f4d39ac50ee5a was selectively reconciled, not wholesale merged. Validated reconciliation head abff45ebcc4b5af2a85ab0c456b025b5098c6e29 is represented in final integration 0fa442330bc2bb03636ff9297512da4c29e38684.
NEXT WORK: evidence/regression only unless DEV5/Auditor returns a concrete packaging/security defect. Authoritative reconciled semantics include explicit settings schema_version=0 rejection; packaged WebView resource completeness; split and inline WebView remote-debug rejection; path-private resource errors; fail-closed keymap profile boundary; legacy release workflow tombstones; no lane-only dev4-package-security-ci promotion; Nuitka compilation report CI-only and never user-package content.

## DEV5 — DIRECTIVE 0003
Stage1 current-wave Product integration is exact head 0fa442330bc2bb03636ff9297512da4c29e38684. Canonical exact-head gates: UI Semantic 32532503184 SUCCESS and Stage1 Saturation 32532503262 SUCCESS. Do not duplicate DEV1-DEV4 intake already represented in this SHA.

Next priority is integration/evidence preparation for the isolated full-product plane, not blind branch assembly. PR #52 shared-core and completion/full-product-critical-path contain useful future-module work but are not authorized as wholesale baselines. Establish package-level auditability first: canonical GameTree/PGN vertical slice, ACSDB/library vertical slice, then ChessBase/book/training/teacher session packages in dependency order. Create full5/integration only when a concrete safe base and accepted package inventory are proven. Preserve one canonical core and Stage1 release lineage isolation.

Never merge PR #54 or frozen release refs for convenience. Never reuse an old rejected ZIP. A fresh Windows candidate requires the complete machine release chain on the exact final audited Product SHA. NVDA_VERIFIED stays NO until Oleksii personally verifies that exact fresh candidate.
