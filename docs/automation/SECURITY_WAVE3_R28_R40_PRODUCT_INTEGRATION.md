# Security Wave 3 — R28–R40 Product Integration

Status: **implementation candidate**. This document describes the public Accessible Chess wiring only. Private capability mapping, trusted-state implementation, issuer/signing keys, managed-key provider configuration and private repository identity do not belong in this repository.

## R28–R30 — whole-product enforcement

Private runtime API v4 is required for advanced product protection.

Accessible Chess issues independent authorization requests for distinct service families before their authority is constructed:

- `engine.analysis`;
- `profile.local`;
- `library.database`;
- `books.training`;
- `classroom.local`;
- `formats.local`.

The public product never supplies a capability class, account/device identity, lease contents or trusted-state bytes. The private runtime owns the canonical capability matrix, distributed mapping and trusted local state. A denial at one boundary does not create a global unlock/deny flag for another boundary.

## R31–R33 — trust hierarchy and rotation

At protected startup, API v4 synchronizes private trust state before premium composition. The public product receives only a bounded semantic state and monotonic sequence. It receives no root/intermediate/private issuer key material. A required trust migration or compromise state fails closed into the existing accessible locked/recovery shell.

## R34–R37 — secure update path

The existing Accessible Chess `ReleaseUpdateCenter` remains the application/UI authority.

Its providers are now private-runtime adapters:

- channel: private R34–R37 staging;
- signature verification: private rotating update trust;
- trusted time: private non-regressing update time;
- installer: verified bytes are handed back to the private updater for revalidation/install.

Accessible Chess still independently verifies signed metadata, version policy, source URL, exact size/SHA-256 and retains a read-only verified stream immediately before install. There is no public metadata command/executable path input.

## R38–R40 — release trust

Accessible Chess retains its existing release-security authorities:

- fail-closed update verification;
- Authenticode signing/verification boundaries;
- deterministic SPDX SBOM;
- SLSA provenance construction and builder binding;
- strict Windows release/package qualification.

Wave 3 adds two reusable production boundaries:

- GitHub Artifact Attestations for build provenance and SPDX SBOM, using GitHub OIDC/Sigstore in the `production-signing` environment;
- Microsoft Artifact Signing for Windows binaries through Azure OIDC, SHA-256 Authenticode and HTTPS RFC3161/SHA-256 timestamping, followed by exact publisher/timestamp verification before the signed artifact can be uploaded.

Public source contains no private signing key or Azure client secret. The Microsoft signing account, federated Azure identity, certificate profile and expected publisher value remain environment configuration and identity-verification prerequisites; they are deliberately not fabricated in source.

## Compatibility

Runtime API v1–v3 remains accepted for the already integrated earlier waves. R28–R40 product features activate only on runtime API v4. This preserves existing protected packages while allowing the advanced trust/update layer to be deployed without weakening Wave 1 or Wave 2.
