# Section 38 — Release infrastructure closure audit

Status: **CANDIDATE — exact-head qualification and dependency late-bind required**

Canonical plan: Section 38 — Packaging, updates, signing, SBOM, licensing and commercial release infrastructure.

Base at branch creation: shipping PR #2184 @ `e00030a3672aca76fb3f4721bcac317867c22e4f`.

## 38.1 Deterministic Windows package / clean-machine launch

Reuses the single current shipping package architecture. No second packager was created.

Inherited authorities include:
- `acs/version2_package_preflight.py`;
- `acs/version2_release_payload.py`;
- `acs/version2_final_release.py`;
- `acs/version2_portable_package.py`;
- `acs/release_preflight.py`;
- the existing deterministic Windows candidate/re-readback lineage.

Section 38 qualification re-runs canonical release/package preflight and portable-package regression suites.

## 38.2 Signed builds, secure update / downgrade policy, integrity and provenance

Converged authorities:
- `acs/authenticode.py` — Windows signature verification;
- `acs/authenticode_signing.py` — signing operation with external certificate/private-key custody;
- `acs/update_security.py` — signed metadata, HTTPS source binding, semantic version/downgrade policy, trusted non-regressing time, package size/SHA-256 identity and TOCTOU-safe retained handle;
- existing `acs/slsa_provenance.py` — SLSA Provenance v1 release identity.

The update security source is the current-shipping successor from PR #2323, not the older #819 snapshot. It requires an explicit trusted-time provider and revalidates exact bytes at consumption time.

`acs/release_update_center.py` composes the update authority with replaceable channel and installer ports. A staged package can reach an installer only after signed metadata and exact bytes pass the canonical verifier; apply revalidates through the retained read handle. No signing private key, payment secret, provider credential or raw update pathname is exposed to UI.

## 38.3 SBOM, dependency/license notices and vulnerability handling

Converged:
- `acs/spdx_sbom.py` and `tools/generate_spdx_sbom.py` — deterministic machine-readable SPDX 2.3;
- inherited release payload / package preflight third-party notice and Stockfish/sound provenance checks;
- `acs/security_support_policy.py` and its generator — deterministic vulnerability/support lifecycle manifest.

SBOM and support-policy inputs fail closed on malformed, ambiguous or unsafe data.

## 38.4 Support/security-update lifecycle and commercial-compliance preparation

`security_support_policy.py` carries the established minimum support/security-update lifecycle contract and machine-readable disclosure/update/support endpoints. External legal review, production contact endpoints, certificate purchase/custody and actual publication-channel credentials are deployment/compliance inputs, not application source authority; this section does not manufacture them or claim a legal conclusion.

The release architecture remains provider-neutral so entitlement/billing/signing/update providers can change without rewriting chess, Library, Books or UI modules.

## 38.5 Accessible updater / diagnostics / Help

The canonical shared action registry now exposes:
- `release.status`;
- `release.check_update`;
- `release.apply_update`.

They are retained by the V2 release profile and exposed through the existing native **Help / Довідка** menu with English and Ukrainian labels. The canonical `Version2Application` boundary emits concise semantic status announcements suitable for keyboard/screen-reader use, rejects UI-supplied paths/payloads, and sanitizes release-provider failures.

If a distribution does not configure an external update channel, Status reports that fact accessibly; Check/Install fail closed rather than falling through to an unverified path. A configured channel is mediated by `ReleaseUpdateCenter`.

## Qualification

Dedicated gate: `.github/workflows/section38-release-infrastructure.yml`.

The gate runs on Ubuntu 22.04 and Windows 2025 and covers:
- signed-update verification and trusted-time/rollback protections;
- release-update coordinator and application/menu ingress;
- Authenticode verification/signing contracts;
- deterministic SPDX SBOM;
- security-support/vulnerability policy;
- inherited SLSA v1 provenance tests;
- canonical package/release preflight and portable-package tests;
- core selftest.

## Truth markers

- HUMAN_TESTED=NO
- NVDA_VERIFIED=NO
- FINAL_WINDOWS_ZIP=NO
- SIGNING_PRIVATE_KEY_IN_REPO=NO
- EXTERNAL_RELEASE_ENDPOINT_INVENTED=NO

Those markers are not intermediate Section 38 repository-work blockers under Simplified Section Closure Protocol v3. They remain final distribution/owner/provider gates where applicable.

## Closure rule

Do not mark Section 38 DONE until:
1. exact candidate CI is terminal green;
2. live dependencies Sections 14 and 29–37 are read back terminal under the current plan;
3. this candidate is late-bound to the then-current canonical shipping ancestry;
4. post-integration registry/audit evidence is durable.

After those conditions are met, record **DONE — TERMINAL — DO NOT REENTER** unless a demonstrated regression, invalid evidence, changed approved contract or later integration break requires reopening under AGENTS.md.
