# WordDeck Round 4 release, security and future-service acceptance contract

## Public Windows release

- Release output contains application/runtime assets only. Personal state/profile/backups remain under `%LOCALAPPDATA%\WordDeck` and must not be packaged.
- Application must run as a normal user; the manifest must not request administrator elevation.
- Paths containing spaces and Cyrillic must work.
- The shipped learning runtime must remain usable offline. Development-only acquisition tools do not create a runtime networking requirement.
- A self-contained published build must pass the same deterministic self-test as source execution.
- Validation workflows are read-only with respect to product source and never advance canonical refs.

## User-data continuity

- Recall, Spelling and Sentence state are one user-owned continuity domain even when stored in separate files.
- Risky migration/import/reset operations require recoverable backup behavior.
- Corrupt primary state may recover from a validated backup; corrupt primary and corrupt backup must fail closed with explicit recovery guidance.
- Profile import must validate before replacing live state and preserve a rollback path.
- Hiding a Recall word is reversible user state; it must never physically delete canonical dictionary/audio assets.
- SentencePack replacement uses immutable generations plus a small activation pointer. The previous active generation must stay usable until the new portable and SQLite candidates validate.

## Security and privacy cleanliness

Public source/release must not contain API keys, OAuth credentials, token files, Telegram/browser sessions, cookies, passwords, private logs, or hard-coded personal Windows user paths. CI scans tracked content for common secret formats and suspicious filenames. No telemetry or account identifier is collected by the current desktop runtime.

## Licensing and provenance

- Oxford and audio evidence remain subject to the project’s existing provenance/QA records; this lane does not regenerate accepted corpus/audio without a demonstrated defect.
- SentencePack import must validate pack and per-sentence license metadata before installation.
- Derived SQLite data must remain cryptographically tied to its validated portable source.
- Any future bundled third-party runtime or dataset requires an explicit distributable license/notice in the release package before public distribution.

## Future visual/web accessibility guardrail

If a later WordDeck UI uses Blazor Hybrid/web technologies, accessibility parity with the keyboard/NVDA desktop contract is a release prerequisite: semantic HTML, native controls where possible, deterministic focus, visible and screen-reader state, no pointer-only interactions, no canvas-only learning content, and automated browser accessibility checks plus physical screen-reader acceptance.

## Future WordPress/account/service security contract

WordPress/account/network service integration is not part of the current approved v1 runtime and must not be added implicitly. If authorized later, the minimum contract is:

- explicit opt-in network/account feature boundaries;
- least-privilege authenticated APIs and server-side authorization on every user-owned resource;
- no WordPress administrator credentials or long-lived secrets in the desktop client;
- TLS-only transport and revocable short-lived tokens stored in OS-appropriate protected storage;
- data minimization, explicit retention/deletion behavior, export capability, and no hidden telemetry;
- replay/CSRF protections appropriate to the chosen authentication flow;
- rate limiting, audit logging without secret/private payloads, backup/restore, and breach-response procedures;
- accessibility parity for every account and recovery flow.

These future contracts are guardrails only; they do not authorize adding networking, accounts, WordPress or telemetry to WordDeck v1.
