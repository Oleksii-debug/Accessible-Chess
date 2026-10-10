# Section 52: release qualification matrix

Authority: current Accessible Chess Sections 0–53 canonical plan on Google Drive.

Current state: SUPERSEDED BY TERMINAL CLOSURE. See `SECTION52_TERMINAL_CLOSURE.md`; this file retains the original gap matrix for audit history.

52.1: Reuse version2_package_assembler, version2_package_preflight, version2_portable_package. Real deterministic Windows candidate and clean-machine launch remain to be demonstrated.

52.2: Reuse authenticode_signing, update_security, release_update_center, SLSA provenance. Real signed release and rollback evidence remain outstanding.

52.3: Reuse spdx_sbom generator and notices. Bind a complete SBOM/license manifest to each actual release artifact.

52.4: Reuse security_support_policy. Actual support endpoint, publication commitments, commercial compliance and third-party legal review must be verified rather than invented.

52.5: Reuse release.status, release.check_update, release.apply_update semantic application actions and native Help menu. Actual packaged UI accessibility evidence remains to be collected.

52.6: Two independent deliveries are required: TEST_BUILD with legally transferable authentic books, games, databases, exercises and locally downloadable video; PUBLIC_RELEASE with only redistributable material and direct source links for other content. Never bundle API keys or credentials. Package each with the canonical preflight and verify actual Windows launch, source fingerprints, clean-machine format and multi-provider tests.

Historical disposition: the repository-controlled variant and release gates are now terminal. Neither a signed production package nor clean-machine/owner acceptance is falsely represented as LIVE; publication remains denied until that exact external evidence exists.
