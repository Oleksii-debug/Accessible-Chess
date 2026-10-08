# Security Wave 4 — R41–R50, product-side dependency-safe integration

Status: **STACKED PRODUCT CANDIDATE; NOT MERGED, NOT RELEASE-APPROVED**.

Parent: canonical Wave 3 PR #2493 at its exact starting SHA `6b7c9ebfe9697574fda5c2f32dabe9533c45394c`; the parent must independently qualify and merge before this child can become shipping authority. Do not merge this child directly to main or bypass Wave 3.

R41 is a private crown-jewel inventory and R43 is a build/release stripping gate, not a client-side runtime check. This product-side work introduces one **private API v5** extension to the existing `ProtectionRuntimeClient`; it does not create a second licensing, device, or package authority. A packaged release with an available v5 runtime must pass independent verification of R42, R44–R50 before opening engine, Library, persistence, profiles or other premium application resources. Every missing/false/malformed/exception verdict locks startup and leaves pre-existing personal data alone. Versions v1–v4 keep their already supported protocol; no silent private-API promotion occurs.

The verifier runs only in the externally installed private runtime package. No keys, hardware details, account IDs, device IDs, license contents, private repository name, vendor config or resource decryption keys are passed to the public user-interface API. An app-side return of `True` is **not a signed release proof and never grants access to server-backed premium assets**. Real R42 native execution, R44 protected-resource delivery, R45 signed license binding, R46/R47 Windows CNG/TPM, R48 server challenge, R49 optional attestation and R50 snapshot/clone detection must be implemented and independently exercised by the private v5 runtime and supporting server; a stub cannot make those claims.

R51–R73 contain vendor evaluation, synthetic fixtures, private service operations and final independent red-team evidence. They are NOT silently considered product-integrated here. A real vendor SDK, Microsoft-signed release, live server endpoints and final Windows/NVDA acceptance are separate and unavailable. Do not claim production anti-debug, anti-dump, white-box protection or an uncrackable client on synthetic evidence.

Qualification: `python -m pytest -q tests/test_security_wave4_product_integration.py` on the exact candidate with full inherited Wave 1/2/3 and product composition gates. Queued/unexecuted CI does not equal PASS. No source-file import of the private repository is permitted in this public repository.

## 2026-10-08 current-shipping reconciliation

Upstream Wave 3 (R28-R40) qualified on its exact candidate and merged into canonical current shipping at `f04d6fcd736dfe05011c03180ac002628d0e8945` (PR #2493). The former Wave-4 stacked base is now historical, not an active integration authority. This Wave-4 candidate is reconciled against that exact shipping tree through one history-preserving two-parent commit on the existing PR #2497; the only product delta is the six Wave-4 paths listed in this PR. The v4 API-version strict-type fixes and R28-R40 tests remain intact. CI on the reconciled exact head and private v5 provider implementation/deployment are still separate qualifications: no automatic release approval, no vendor-protector/native attestation PASS, and no R51-R73 product-INTEGRATED claim.

## R43 product release-preflight wiring — 2026-10-08

The existing `acs.release_preflight.inspect_release_package` inventory gate now rejects loose native debug/build sidecars (PDB, ILK, MAP, dSYM, coverage/profiling/intermediate artefacts) and native C/C++/Rust source under the shipped product, including artefacts listed with a valid checksum. This is applied through the **existing** product release-preflight authority, not a second release/signing gate. The mandatory GPLv3 corresponding Stockfish source archive under `THIRD_PARTY_NOTICES` remains accepted; runtime web assets remain supported.

`tests/test_release_preflight.py` adds negative checksum-bypass, case-variant, dSYM and raw-source tests. The existing dual-OS Wave-4 workflow now runs these tests and compiles the preflight source/test. The exact-head hosted run result must be verified separately; queued/cancelled checks never mean PASS.

This stage check **does not** prove native PE/ELF debug-section stripping, use of a commercial protector, real TPM or private runtime v5 attestation. Those require the qualified native builder/provider and independent product release evidence. The Wave-4 PR remains a candidate until its remaining qualifications are met.
