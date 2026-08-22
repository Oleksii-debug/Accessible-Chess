# WordDeck Round 4b — release/security acceptance

This document is an acceptance contract for the worker candidate. It does not change product scope.

## User data
- Personal progress belongs under `%LOCALAPPDATA%\WordDeck`, never inside the public ZIP/publish tree.
- Recall, Spelling and Sentence state/profile/backups must not be tracked or packaged.
- Import/reset/migration paths preserve recovery before destructive replacement and fail closed on incompatible data.
- Hidden words are reversible learning overlays, not dictionary/audio deletion.

## Repository and workflow safety
- Validation is source-read-only and bound to the exact worker SHA.
- Historical emergency, completed 1156 and accepted V0.1 workflows remain inert/manual and cannot silently mutate canonical source.
- The worker never writes `worddeck-bootstrap` or `main` and never merges another worker branch.
- Accepted V0.1 remains a separate historical release and is never overwritten by an unaccepted candidate.

## Secrets and privacy
- No API keys, OAuth credentials, token.json, cookies, browser profiles, Telegram/session files, private keys/certificates, `.env`, passwords or private logs in source or artifacts.
- No hard-coded personal Windows/Linux user paths.
- No new telemetry/network service is required for normal study.
- Future account/telemetry interfaces remain non-networking architecture only in this round; no plaintext passwords and no computer-name identity design.

## Windows portability
- Self-contained win-x64 publish.
- No administrator elevation (`asInvoker`).
- Exercise the published EXE from a path containing spaces and Cyrillic.
- Normal Recall/Spelling/Sentence behavior remains offline-capable except user-chosen import/source acquisition outside ordinary study.

## Accessibility release evidence
- Deterministic accessibility self-tests must pass.
- Actual Windows UI Automation must execute, not be skipped, and must cover Natalia Recall arrows, selector focus, menu/native arrows, F1 truth, shortcut settings, profile/import/reset dialogs, Spelling and Sentence keyboard surfaces.
- Physical NVDA acceptance is a separate human-only gate.

## SentencePack disclosure
The runtime/import/SQLite/provenance machinery may be release-ready while no independently accepted production SentencePack payload is bundled. The package/status must state that truth explicitly. Synthetic fixtures are not a production corpus. Any future bundled corpus requires exact source/license/provenance/attribution evidence and matching notices.

## Release decision
Machine green means the exact worker branch passed its automated acceptance contract. It is candidate evidence for independent audit and selective canonical integration; it is not an independent full-v1 PASS and not a manual NVDA PASS.
