# WordDeck Round 4 release, security and future-service acceptance contract

## Public Windows release

- Release output contains application/runtime assets only. Personal state/profile/backups remain under `%LOCALAPPDATA%\WordDeck` and must not be packaged.
- Application runs as a normal user; `app.manifest` must use `asInvoker` and must not request administrator elevation.
- Paths containing spaces and Cyrillic must work for publish and launch.
- The shipped learning runtime must remain usable offline. Development-only corpus/audio acquisition tools do not create a runtime networking requirement.
- A self-contained published build must pass the same deterministic self-test as source execution.
- The exact published EXE used for the worker acceptance must also pass Windows UI Automation; a skipped UIA run is not acceptance.
- Validation workflows are read-only with respect to product source and never advance canonical refs.

## User-data continuity

- Recall, Spelling and Sentence state form one user-owned continuity domain even when stored in separate files.
- Risky migration/import/reset operations require recoverable backup behavior before replacement.
- Corrupt primary state may recover only from a validated backup; corrupt primary and corrupt backup must fail closed with explicit recovery guidance.
- Complete profile import validates before replacing live Recall/Spelling/Sentence state and preserves rollback copies.
- Legacy profiles must not erase newer-mode state that they do not contain.
- Hiding a Recall word is reversible user state; it must never physically delete canonical dictionary/audio assets.
- SentencePack replacement uses the current canonical immutable-generation/active-manifest recovery implementation. Round 4 acceptance must not re-port stale recovery code from earlier worker branches.

## Security and privacy cleanliness

Public source/release must not contain API keys, OAuth credentials, token files, Telegram/browser sessions, cookies, passwords, private keys, private logs, or hard-coded personal Windows user paths. CI scans tracked content for common secret formats and suspicious filenames. No telemetry or account identifier is collected by the current approved desktop runtime.

Acceptance additionally checks that the public executable/evidence directory contains no state/profile/backup/history-shaped personal files and that no direct runtime networking API has been introduced into the desktop source without explicit product authorization.

## Licensing and provenance

- Oxford dictionary and accepted offline audio evidence remain subject to the project’s existing provenance/QA records; this lane does not regenerate accepted corpus/audio without a demonstrated defect.
- SentencePack import validates pack and per-sentence license metadata before installation.
- Derived SQLite data remains cryptographically tied to its validated portable source.
- `THIRD_PARTY_NOTICES.md` and any data-specific notice required by a bundled candidate are part of release-content audit.
- Any future bundled third-party runtime or dataset requires an explicit distributable license/notice before public distribution.

## Performance and resilience

- Exact release validation retains deterministic self-tests for full Oxford 5446 scopes, Spelling/Adaptive, Sentence/SQLite, unified profile and state-failure recovery.
- UIA acceptance must exercise repeated selector changes and repeated mode open/close cycles rather than only one happy-path interaction.
- Release acceptance must not mutate tracked source files; post-test source immutability is a hard gate.

## Future visual/web accessibility guardrail

If a later WordDeck UI uses Blazor Hybrid/web technologies, accessibility parity with the keyboard/NVDA desktop contract is a release prerequisite: semantic HTML, native controls where possible, deterministic focus, visible and screen-reader state, no pointer-only interactions, no canvas-only learning content, automated browser accessibility checks and physical screen-reader acceptance.

## Future WordPress/account/service security contract

WordPress/account/network service integration is not part of the current approved v1 runtime and must not be added implicitly. If explicitly authorized later, the minimum contract is:

- explicit opt-in network/account feature boundaries;
- least-privilege authenticated APIs and server-side authorization on every user-owned resource;
- no WordPress administrator credentials or long-lived secrets in the desktop client;
- TLS-only transport and revocable short-lived tokens stored in OS-appropriate protected storage;
- data minimization, explicit retention/deletion behavior, export capability and no hidden telemetry;
- replay/CSRF protections appropriate to the chosen authentication flow;
- rate limiting, audit logging without secret/private payloads, backup/restore and breach-response procedures;
- accessibility parity for every account, authentication and recovery flow.

These future contracts are guardrails only; they do not authorize adding networking, accounts, WordPress or telemetry to WordDeck v1.
