# Security Wave 5: first product-boundary integration, R51–R73

Status: **DRAFT / STAGED / NOT SHIPPING / NOT PHYSICALLY QUALIFIED**.
Stacked on the existing canonical Wave 4 PR #2497. The first existing unmerged
security wave remains a mandatory predecessor. This document does not replace
the canonical neutral R00–R73 security plan or its terminal ledger.

## R51 independent vendor PoC

The build-only scripts/security_r51_vendor_poc_gate.py binds a vendor trial to
the *actual* protected product artifact digest and exact build SHA-256.
Reviewer public keys come only from a separate approved key inventory with
an independently pinned SHA-256, never from the vendor report. A detached
Ed25519 signature covers the complete canonical report and reviewer identity.

The evaluator itself remains the existing neutral
continuum_runtime.vendor_evaluation.assess_vendor. No duplicate vendor
selection, native protector, license issuer or alternative proof authority.
Even a QUALIFIED independently signed vendor PoC is **not** a selected vendor
or approved product release. Synthetic, forged, stale, revoked, incomplete
NVDA/Windows/performance/cost/support evidence cannot become release PASS.

## R52 license transport

The existing Version 2 production composition now requires
acs.protection_license_container_boundary.require_private_license_container
when the already canonical private runtime reports API v5.
The request supplies only exact release build/package/state roots; it does NOT
allow browsers/users to supply account IDs, device IDs, transport modes,
subscription state or signatures. The private runtime must use the existing
neutral R52 license-container contract and R08/R45/R29 authorization.
Missing operation, failed trust, malformed/forged boolean/API/build, transport
outage and unavailable medium fail closed before premium data construction.
Previous v1–v4 private runtime behavior remains unchanged.

The private API v5 implementation and a real commercial vendor backend are
**not** deployed in this public PR. This is a product-side contract candidate,
not proof of working machine/cloud/hardware/enterprise provider access.

## R53–R62 and R63–R72

The neutral source components are terminally closed in continuum-runtime
for repository-controlled scope. They are not automatically integrated into
Chess by importing their synthetic fixtures. Real protector integration,
commercial attestation, signed server subscriptions, durable per-operation
billing/quota storage, production migration, independently run physical
offline/online red-team and incident response remain NOT CONFIGURED/
NOT VERIFIED. No unconditional PASS, silent fallback or release override.

## R73 signed release-convergence intake

The build-only scripts/security_r73_product_evidence_gate.py reuses the single
canonical neutral R73 evaluate_convergence. Its trusted independent Ed25519
verifier keys are provided via a separately SHA-256-pinned protected inventory.
It binds each physical/source/simulation attestation to actual shipped
AccessibleChess artifact bytes, source SHA-256, scope, residual-risk SHA-256,
build/channel, freshness and sequence. All 13 existing R73 control families
must have independently signed INTEGRATED/ACCEPTED evidence for a physical
assessment. Even a valid physical result returns
PHYSICAL_EVIDENCE_REQUIRES_INDEPENDENT_RELEASE_DECISION and
release_approved=false. Missing or fake proof fails closed. This verifier
does not perform release publishing, licensing or generate signatures.

The workflows/security-wave5-r73-product-evidence.yml exact-head workflow
executes negative contract tests on Windows/Linux and pins the existing
neutral R73 verifier to continuum-runtime SHA
95f46b0dbcace6b3139c01afa50830f803c954e8.
Fixture results remain synthetic. No real Windows/NVDA user acceptance,
commercial protector PoC, private provider deployment, independent signed
release decision, shipping merge, or R51–R73 terminal product integration
is claimed.
