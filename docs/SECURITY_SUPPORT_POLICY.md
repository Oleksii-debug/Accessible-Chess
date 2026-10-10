# Security and release support policy

## Reporting security issues

Use the repository's private [security-advisory form](https://github.com/Oleksii-debug/Accessible-Chess/security/advisories/new). Do not place credentials, private user data, unpublished exploit details or signing material in a public issue.

## Supported release evidence

A distributable build is identified by its exact SHA-256, integration commit, immutable release receipt, SPDX 2.3 SBOM, SLSA provenance and independently verified timestamped Authenticode signature. A version string, branch name or successful build alone is not release authority.

The public package may include only content marked `PUBLIC_REDISTRIBUTION`. Owner-only authentic test material is confined to `TEST_BUILD`; it is never silently copied into a public release. API keys, tokens, certificate private keys, user profiles and provider caches are prohibited from both variants.

## Updates and rollback

The accessible update surface must expose status, check and apply actions. Update metadata and package bytes are revalidated before effect. Failure preserves the installed version and owner data; support staff must not ask users to disable signature or checksum verification.

## Accessibility and privacy

Security fixes must retain keyboard and screen-reader access. Public reports should contain the smallest reproducible information and no private chess documents, student/classroom data or provider prompts.
