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

## R53 vendor-protector candidate byte intake (build-only, not product deployment)

The existing Wave-5 PR now also stages
`scripts/security_r53_protector_candidate_gate.py` as a **build-only**
candidate-readback adapter. It reuses the canonical neutral
`continuum_runtime.commercial_protector.ProtectorProfile`,
`ProtectedCandidate`, and `check_candidate`, without another protector,
vendor-selection authority, license issuer, or client runtime. The adapter
requires externally pinned source, protector-tool, recipe SHA-256 and exact
build ID; parses bounded strict-schema candidate/profile receipts; verifies
both the real original-file and protected-file bytes; and rejects malformed
JSON, duplicate fields, symlinks, substitution, mutated/oversized images,
forged integer fields, status escalation, tampered protected bytes, and an
unchanged source image passed off as protected. It deliberately does not
sign anything, approve releases, or supply an actual vendor SDK.

A passing readback is only `CANDIDATE_BYTE_INTEGRITY_ONLY` and explicitly
reports `release_approved=false`, `independent_vendor_qualification=REQUIRED`,
and `protected_windows_nvda_qualification=REQUIRED`. The independent
R51 vendor evidence authority remains separate, as do R54–R62 actual
production protector qualification and real Windows/NVDA acceptance.
`tests/test_security_r53_protector_candidate_gate.py` exercises synthetic,
tamper, trust-binding and path-substitution cases in the existing dual-OS
Wave-5 workflow. No real commercial protector is claimed installed.
Workflow registration is **not an executed CI PASS**; verify exact-SHA
hosted results independently before advancing this candidate.

## R54 protected-build diversity readback (build-only)

The existing canonical `continuum_runtime.protection_diversity`
`check_diverse_candidate` is now exposed to the product's **build-time
qualification** only by
`scripts/security_r54_diversity_candidate_gate.py`. This requires an
already-qualified **R53 candidate** against the actual source and protected
bytes, an externally pinned opaque product SHA-256, the existing exact
protector profile and a confidential per-build secret injected by the trusted
build provider. The private variation secret never appears in source,
command-line arguments, result receipts, logs or release files.

The canonical neutral verifier checks both separated variation commitments,
protected image hash, product/build context and secret-key identity; missing
parent, copied/tampered bytes, wrong secret, forged status, schema drift,
duplicate-key JSON and receipt substitution all deny. This module does not
invent protector logic or alternate licensing authority. Tests in
`tests/test_security_r54_diversity_candidate_gate.py` exercise synthetic
positive/negative fixtures on the existing dual-OS Wave-5 workflow.

The only permitted success label is
`DIVERSITY_CANDIDATE_READBACK_ONLY` with
`release_approved=false`. Real independent native vendor diversity,
actual deployed protector, Windows/NVDA binary qualification and third-party
release approval are still MISSING. No fixture may promote them to PASS.

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

## R65 server-side paid operation dispatch (prepared)

The existing canonical acs.server_application_boundary.ServerApplicationBoundary
now supports per-operation trusted-server paid authorization, without creating
a second subscription issuer or reading browser "paid" flags. Paid operations
are explicitly registered by a trusted server as premium_required=True.
Missing authoritative premium_guard prevents that server configuration from
starting. The guard executes after principal/workspace/permission validation
but before a synchronous handler's side effects; only literal True proceeds.
Exceptions, truthy impostors, or no guard fail closed. Heavy queued premium
operations are refused until the worker-time entitlement/UNKNOWN reconciliation
boundary exists, so an authorized enqueue cannot become an unverified
post-expiry execution. Existing nonpremium operations retain their behavior.

The trusted callback must be backed by the pre-existing continuum R63/R64/R65
subscription/billing/quota authorities and durable production stores. The
public product does **not** synthesize that backend, issue paid receipts,
implement a billing provider, or declare LIVE server deployment.

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
