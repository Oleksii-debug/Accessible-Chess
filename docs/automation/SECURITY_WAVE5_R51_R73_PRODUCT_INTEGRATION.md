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

## R55 first-party whole-binary readback (prepared)

`scripts/security_r55_whole_binary_gate.py` uses the accepted neutral
`continuum_runtime.whole_binary.check_whole_binary` and R53/R54 receipt chain
against real application EXE file bytes. This first product-specific boundary
allows only `AccessibleChess.exe`. It explicitly excludes GPL Stockfish and
other third-party Python/WebView2/.NET executables from proprietary wrapping.
Each candidate binds exact R55 plan, trusted build identity, product digest,
source and protected file bytes, externally injected build variation secret,
and whole-binary manifest. Missing/malformed/changed sources or receipts deny.
The comparison is structural PE and SHA integrity **only**; it cannot prove a
commercial protector was run. The candidate never issues release authorization
and never appears in the shipped executable.

The existing dual-OS Wave-5 workflow includes `tests/test_security_r55_whole_binary_gate.py`
covering synthetic PE candidate, tampering, cross-build/release reuse, receipt
forgery, symlink, source-copy bypass, and third-party scope rejection.

## R56 function-level candidate manifest (prepared)

`scripts/security_r56_function_candidate_gate.py` calls the already-verified
R55 AccessibleChess.exe verifier first. Only then can the canonical neutral
`continuum_runtime.function_protection.check_functions` validate an exact
build-only protected-function payload manifest and its R55 parent digest.
Accessible Chess permits only first-party `AccessibleChess.exe` targets;
neutral R56 explicitly refuses accessibility, screen-reader, input, keyboard,
UI, audio, startup and realtime function identifiers. No decryption loader,
plaintext key or separate client-side entitlement authority is introduced.
Tests cover parent tampering, ciphertext replacement/removal, a forged
function manifest and attempts to protect NVDA/input or third-party modules.
This is digest verification of supplied ciphertext only, not proof of real
native on-demand encryption, runtime key secrecy or approved release.

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

## R57–R60 private commercial runtime startup — source candidate only

The existing `acs.protection_hardened_boundary.HardenedReleaseBoundary`
now enforces four additional **independent private v5** verifier receipts,
in fixed order: R57 protected native-runtime integrity, R58 independently
verified instrumentation-clear policy, R59 scoped sensitive-memory admission,
and R60 ephemeral endpoint key assurance. The check IDs are fixed product
constants; the public client cannot select tests or supply trust verdicts.

`acs.version2_release_app` invokes this existing private boundary *after*
R42/R44–R50 and the existing R52 license-container gate, and *before* any
normal user-data recovery, local database, profile, Stockfish, or other premium
composition. A missing check, denied check, exception, mismatched build/check,
forged boolean or API version, or unsupported private runtime fails closed;
recovery/login/help/update/own-data rights remain under the original
`ProtectionDecision` rather than any new grant. Previous v1–v4 behavior
remains exactly on its existing path.

No client-side debugger detection, native page hook, plaintext decryption,
embedded key, secret exposure, anti-dump process termination, NVDA blocking
or secondary license issuance is introduced. All native R57–R60 validation,
independent signatures, replay/clock/proof checks and Windows accessibility
qualification must be implemented in a real independently verified private
provider. Its deployed implementation is **NOT AVAILABLE** and these fake
tests do **NOT** demonstrate actual commercial anti-tamper or white-box
protection. A mock provider is a contract test only.

`tests/test_security_r57_r60_product_runtime.py` covers check coverage,
exact-version and exact-boolean rejection, forged/replayed receipts, per-check
deny/recovery, private error sanitization, and startup short-circuit before
user-data or engine. The existing dual-OS Wave-5 workflow compiles and runs
this suite. CI registration is not a PASS; verify exact-head executed results.

R61 signed per-artifact attribution is a trusted build/issuer operation and R62
leak attribution / revocation is a trusted incident-response service; neither
may be converted into a public-client license check or a self-issued release
PASS. R63/R64 require independent provider-backed subscription/billing
authority and durable reconciliation; R66–R72 require independent physical or
operational evidence. Those capabilities are not proven deployed here.

## R61 independent post-protection attribution — build-only

`scripts/security_r61_attribution_gate.py` verifies a separately issued,
detached Ed25519 attribution envelope against the actual first-party protected
artifact's immutable file bytes and an independently pinned key inventory.
It reuses **the canonical** `continuum_runtime.watermark_attribution.verify_attribution`
and the same outside-pinned `verifier_public_keys` trust schema used by R73.
It reads a bounded regular file and rejects symlinks, race/substitution,
tampered artifacts, build mismatch, missing/forged signatures, unknown keys,
inventory swap, malformed and duplicate-key envelopes. Markers are not issued
inside the public client; customer allocation identifiers, issuer signing
secrets and tag values are not returned to product logs.

This neutral R61 verifier has a 16 MiB per-artifact ceiling: larger native
packages MUST be qualified through a separately designed signed component
manifest, not silently truncated or accepted. The receipt is only
`INDEPENDENT_SIGNATURE_BYTE_READBACK_ONLY`, always
`release_approved=false`; real vendor instrumentation, customer allocation
provenance, Windows/NVDA physical release and trusted R62 service actions
remain independent unverified requirements.

`tests/test_security_r61_attribution_gate.py` exercises signed synthetic
contracts and negative byte, signature, build, pinned-trust, malformed JSON,
symlink and missing-envelope cases in the existing Wave-5 dual-OS workflow.
No actual provider signature or release qualification is claimed until an
independent trusted issuer supplies it.

## R62 trusted operator-only incident/revocation boundary — staged contract

`acs/protection_incident_response_boundary.py` stages a server-only
`TrustedIncidentBoundary` that delegates signed marker verification,
independent corroboration and specifically approved R22 effects to the existing
`continuum_runtime.leak_response.LeakResponseService`. Its caller must inject
an independently authenticated operator-authorizer and an ACID durable case
journal; the product does NOT provide these production services, incident
credentials, public browser routes, a second revocation authority or a signing
key. A journal reserves an exact context digest in UNKNOWN *before* any
revocation, permitting only literal NEW. On denial/partial commit/exception
the case remains UNKNOWN and **must** undergo trusted reconciliation; replay
never repeats the mutation. Successful canonical R22 effect must be durably
recorded and read back before the bridge acknowledges it. Account-wide
revocation and client-issued entitlement remain forbidden.

`tests/test_security_r62_incident_response_boundary.py` uses a deliberately
in-memory test journal and synthetic Ed25519 marker solely to exercise role
denial, signed proof, independent review, target-only effect, replay, forged
input and uncertain-write cases. It is wired to the existing Wave-5 dual-OS
workflow. **Not deployed**: production trusted operator credentials, durable
journal, real R22 backend, commercial watermark allocation/forensic evidence,
appeal/recovery, protected Windows release and independent release approval.
The R62 product state is **STAGED ONLY / NOT SHIPPING / NOT INTEGRATED**.

## R63/R64 shared billing state into existing R65 server admission — staged

`acs/protection_paid_server_binding.py` is a thin server-side composition
over the EXISTING neutral `BillingAdapter`, `SubscriptionPolicyBackend`,
`ServerPremiumGuard` and current Chess `ServerApplicationBoundary`.
One injected R64 atomic store supplies R63 subscription readback; no browser
payment confirmation, client license issuer or alternative subscription
database is created. The optional `CanonicalPaidOperationCallback` accepts
only authenticated SERVER-RESOLVED transport, checks authenticated actor and
session identity and delegates exact payload bytes/device/build/request to
canonical R65. Only a literal NEW `OperationAdmission` from the identical
canonical R65 ledger can start work; UNKNOWN/CONFIRMED/forged/cross-account
or unconfigured context deny. The existing paid-heavy queue refusal remains.

The product itself does NOT contain the provider-specific webhook verifier,
a signed API snapshot implementation, durable transactional billing/payment
store, production session/device resolver, an ACID premium ledger or a
deployed paid endpoint. Test fixtures explicitly use only an in-memory
billing store and synthetic verifier; they are not production integration.
No payments, customer changes, entitlement grants or release authorization
are executed by these source changes.

`tests/test_security_r63_r65_paid_server_binding.py` covers current-state
billing replay, revoked/expired grant denial, stale sequence, strict
trusted-transport binding, NEW-only admission, UNKNOWN/replay denial and
exception redaction. W5 dual-OS tests are registered but not presumed to PASS.
**R63–R65: STAGED CONTRACT, NOT DEPLOYED / NOT SHIPPING.**

## R69/R71 adversarial evidence intake against exact protected release — staged

`scripts/security_r69_r71_adversarial_evidence_gate.py` verifies exact
protected-artifact file SHA-256, separate SHA-256 pinned independent
verifier-key inventory, strict versioned JSON and replay floors.
R69 dispatches to canonical `continuum_runtime.offline_crack_qualification`;
R71 dispatches to canonical `continuum_runtime.protector_release_qualification`
with fixed Windows x64 / exact build identity. These are the ONLY signed-evidence
authorities. No vulnerable binary probing, key issuing, commercial protector,
new neutral verifier, self-issued PASS or automatic release acceptance occurs.
Synthetic evidence is categorized `FIXTURE_EVIDENCE_ONLY`, missing or mixed
evidence `INCONCLUSIVE`, forged/stale/replayed/altered bytes DENIED, real
PHYSICAL attestations still independently require verified execution and
final human release decision. `release_approved` is always `false`.

The dual-OS Wave-5 workflow includes focused synthetic/negative tests from
`tests/test_security_r69_r71_adversarial_evidence_gate.py`. Actual
protected Windows image, physical adversarial campaign, verifier independence,
Windows/NVDA/AV approval and independent release verdict do not exist in this
repository. **Candidate tooling only; R69/R71 product physical status
NOT_VERIFIED; this does NOT unblock PR #2497 or release.**

## R72 independently signed incident-response evidence and update gate — staged

`scripts/security_r72_incident_evidence_gate.py` is a release/operations
readback adapter over canonical `continuum_runtime.incident_response.assess_incident`
and the existing R34 update metadata verifier. All reviewer, effect witness and
update signing public keys come from one independently SHA-256-pinned inventory
outside untrusted evidence. R72 intake authenticates exact source hash, actual
incident evidence file bytes, signed incident case, unique effect receipts and
emergency update metadata. Missing effects remain PENDING, UNKNOWN cannot be
replayed or turned into CONFIRMED without an independently signed later witness.
Actual compromised key/build, expiry/sequence/rollback and update floor are
verified by the neutral R72/R34 authority. There is NO outbound key rotation,
revocation, installation, account recovery or second mutation authority.

`tests/test_security_r72_incident_evidence_gate.py` supplies isolated fake
Ed25519 issuers to demonstrate signed receipt format, strict trust-pin binding,
wrong source/evidence, forged case, replay, unfinished and UNKNOWN outcomes.
Any complete synthetic signed receipts remain **NOT verified physical operator
execution**, and `release_approved=false` in every result. No production
incident, independent verifier, signed physical Windows shipping evidence or
real emergency update deployment is claimed. **R72 source staged; not shipping
or terminal product integration.**
