# Accessible Chess — owner-approved post-55 operating requirements (2026-10-10)

**Status: REQUIREMENTS ONLY / NOT DONE.** Canonical Google Drive plan: https://docs.google.com/document/d/1ITsUBFwwETRICctcOWLd6atuMcCFZg6v5-wVFumIyxE/edit
Do not use this as a second status authority and do not override accepted main or terminal section locks.

## Placement and immutable identities
New sections immediately after 55: 55A account registration/auth, 55B lossless update, 55C lawful analytics and diagnostics, 55D production site/licensing/operations. Existing localization section IDs 56–60 (77 languages/82 menu choices) are unchanged to preserve cross-worker references. Language-work gate is now terminal DONE Sections 0–55 PLUS 55A–55D with evidence in accepted main and canonical Drive. Sections 53, 54 and 55 remain at their current status; none is reopened or marked DONE by this scope registration.
Use REUSE → REPAIR → CONVERGE with Sections 29–35 and 51–52. An earlier pending account-network design does NOT license automatic decentralized password replication.

## 55A Identity and login
Release must require accessible signup/verify/login before normal network-based use, support user profile, remember/revoke sessions, MFA for privileged accounts, password recovery, child/guardian controls and one canonical secure server-side identity across Windows/Web. Offline existing owner-data export and safe recovery remain possible. Never transmit plaintext password or user API secrets to owner email/admin page.

## 55B Preserved user data across updates
Verified signed manifest, secure delivery, accessible update prompt/changelog, staged installation and rollback. Durable separate user data storage preserves imported books, private games, settings, lessons, progress, provider credentials in OS vault, model/API profiles, and account state. Test populated old profile → new version → rollback/restart/reinstall/portable migration, including interrupted update and invalid package. No unintended duplicate accounts or erased libraries.

## 55C Analytics and diagnostics with MANDATORY official notice
Prior to any real registration-based processing and telemetry, publish versioned accessible privacy notice on site and within Windows/Web; this is a required release gate, not evidence of already providing notice. Explicitly explain controller identity/contact, data fields, distinct processing purposes and legal bases, recipients/processors, international transfers, retention, security, data-subject rights and children's safeguards. Separate essential redacted security/operational diagnostics from optional detailed person-linked usage profiling. Where consent is required: informed, specific opt-in BEFORE collection, accessible withdrawal and logged policy-version receipt. Refusal of optional tracking must not block basic use. Never covertly track individuals, ingest full book text/game content/messages/voice/prompts, or log passwords/API tokens. Prefer aggregate/pseudonymized metrics, corrected idle-time accounting, role-limited audited dashboard, bounded queue/sample/retention and global nonessential kill switch. Apply GDPR/ePrivacy, appropriate DPIA/legal assessment and child/guardian rules; evaluate US COPPA for relevant launch markets.

## 55D Commercial site, licensing, rights, security, support
Establish true copyright/software/licensor legal entity, data controller/processor, site operator, merchant of record, applicable tax/VAT and permitted IP use; do not claim unverified brand registration or world-ranking. Public HTTPS site offers accessible downloads and signed verified release metadata, terms/EULA/privacy/cookie notices, support/accessibility statement, security disclosure, data-rights portal, correct third-party notices/SBOM and lawful content licences. Payment/entitlements only after user-approved commercial model: free/paid tiers, consumer info, refunds, cancellation, accessible checkout, secure PSP payment flow, chargeback handling and processor agreements. Security program includes secret rotation, MFA/RBAC, backup-restore/incident tests, staged rollout and server quotas. Evaluate EU Cyber Resilience Act reporting duties already effective 11 September 2026, GDPR/children protection/COPPA where applicable, accessibility obligations and qualified legal review. Do not mark externally unperformed security certificate, Windows/NVDA, processor-live or legal clearance as done.

## Cloud-worker pytest rather than Actions queue
Existing Accessible-Chess Actions already install/run pytest. No duplicate workflow or global PC install is needed. Worker with an isolated allowed cloud Python checkout should run the relevant existing suite, e.g.:

    python -m pytest -q tests/test_acsdb.py

Broader suites remain mandatory where relevant. If pytest is missing, report a missing runner prerequisite, optionally use a genuinely compatible unittest suite (not a silent zero-test PASS) and preserve the hosted exact-SHA CI as independent evidence. Do not install system-wide packages or incur unapproved paid-provider/test-matrix costs. PR/commit/local green ≠ terminal DONE.
