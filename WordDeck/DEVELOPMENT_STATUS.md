# WordDeck development checkpoint

Last updated: 2026-08-23
Canonical branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Current product truth

WordDeck is no longer in the old Oxford-5000 acquisition phase. The canonical lexical/audio foundation is complete and must not be reopened without a demonstrated defect.

- Oxford 3000 baseline: **3308** stable entries.
- Oxford 5000 additions: **2138/2138** integrated; remaining **0**.
- Total Recall corpus: **5446**.
- Study scopes: **All=5446; A1=900; A2=872; B1=809; B2=1461; C1=1404**.
- User-supplied translation package: **1156/1156 integrated**.
- British offline Oxford-5000-additions audio: **2138/2138**.
- Personal learning state remains outside public release under `%LOCALAPPDATA%\WordDeck`.
- Accepted first-usable **V0.1 remains preserved**.

Do not return to the obsolete `982 activated / 1156 remaining` checkpoint. Do not restart mass translation or full audio generation unless a new reproducible defect proves it necessary.

## Foundation / release state

The Foundation release line includes Recall, Spelling, deterministic/statistical local Adaptive behavior, Sentence/Sentence Spelling foundations, complete Oxford lexical/audio data, profile continuity, migrations/backups, reversible hide/restore, study history, keyboard/NVDA contracts and Windows release hardening.

The last completed V0.2 Foundation candidate before the current integration cycle passed the authoritative Windows build/self-test, self-contained published-EXE checks, clean-public-package checks and integrated Windows UI Automation. Manual physical Windows 11 + NVDA acceptance remains a separate human gate and is not claimed by automation.

The current integration cycle has additionally incorporated green Recall/Spelling hardening:

- normal Spelling startup now uses the protected migration/recovery path instead of bypassing schema migration safety;
- pre-migration backups and fail-closed unreadable-state behavior are preserved;
- long Spelling sessions use fair shuffle-bag sequencing so active cards are covered before repeats;
- restart/resume avoids immediately re-serving the restored card while preserving the rest of the active set;
- a read-only stable-ID learning-evidence boundary is available for later cross-mode adaptive integration.

Exact canonical Windows/release gates must be green again after each canonical integration before the resulting head is treated as a release candidate.

## Full-product roadmap

Foundation completion is not whole-project completion. The approved long-range WordDeck learning system continues through:

1. Stage 11 — real Context Practice / Sentence corpus completion;
2. Stage 12 — private local Book/Text ingestion;
3. Stage 13 — Grammar Coach;
4. Stage 14 — Dictation / Listening;
5. Stage 15 — Story Engine;
6. Stage 16 — Narrative Course;
7. Stage 17 — Real Reading;
8. Stage 18 — Word Families / morphology;
9. Stage 19 — cross-mode Adaptive Mastery Router.

Current planning baseline remains approximately **99% Foundation developer-side machine readiness before the latest integration** versus approximately **46% full-product readiness**. These percentages must never be conflated.

## Stage 11 context status

Canonical already contains the proven Stage-11 context foundation:

- stable-ID-aware 1/2/3-target planning;
- learner-known-vocabulary difficulty ranking;
- 30/100/200/full study-pool planning;
- bounded read-only SQLite lookup;
- exact 5446-entry coverage/gap accounting and deterministic remediation seams;
- privacy-safe interfaces for future Sentence/Grammar/Story/Reading/Book consumers.

A historical attributed EN-UA corpus is currently **measurement/evidence input only**. It is not approved as a redistributable production SentencePack and must not be bundled or relabelled as one without explicit source/license/provenance/attribution approval.

A current independent audit also requires a stricter distinction between physical written-form coverage and exact lexical-item/sense coverage. Homographic rows sharing the same spelling must remain unresolved unless POS/sense evidence disambiguates them; ambiguous surface matches must not inflate stable-ID mastery or coverage claims.

## Active swarm integration rules

The autonomous swarm consists of isolated specialist worker branches, one canonical INTEGRATOR and two independent rolling AUDITORS.

- Only the INTEGRATOR writes `worddeck-bootstrap`.
- Workers never write canonical or `main` and never self-merge.
- Auditors remain source-read-only and do not implement fixes.
- Integrate only green, non-conflicting work after reviewing exact diffs, CI and current audit findings.
- Do not blind-merge stale worker branches.
- Worker-only CI/configuration should not be carried into canonical unless it is intentionally promoted to a canonical gate.

## Current integration blockers / cautions

- **Production SentencePack:** redistribution/release approval and exact stable-ID/sense ambiguity handling remain open.
- **Grammar ↔ Story/Course:** worker lanes currently need one shared grammar-skill ID registry/validation contract before those parts can be integrated together.
- **Book/Reading:** the current worker candidate is not integrable while its exact Windows build is red; lexical ambiguity/source-preservation audit requirements also remain hard gates.
- **Morphology:** architecture is promising and fail-closed, but no real production morphology dataset may ship without approved source/license/provenance/attribution and exact green integration evidence.
- **Physical NVDA:** never claim a manual NVDA PASS until the user actually tests the exact build on a physical Windows 11/NVDA setup.

## Safety / user-data invariants

- Public releases contain no personal state/profile, secrets, credentials, private logs, browser/session data or personal hard-coded paths.
- Risky state/profile migrations or imports require backup/rollback and fail-closed handling.
- Update/reinstall must not erase progress.
- “Delete word” means reversible hide/restore, not physical removal from the canonical 5446 dictionary/audio set.
- UTF-8 and Windows paths with spaces/Cyrillic remain supported.
- Offline core learning remains functional without connected services.

## Exact next integration action

1. Wait for/re-read exact canonical Windows and V0.2 candidate results triggered by this current product-code checkpoint; repair any regression before further canonical integration.
2. Continue reviewing active worker PRs from highest product priority to lower priority: Stage 11, then Stage 12/13, while respecting audit findings and exact CI.
3. Integrate only the next green, non-conflicting slice; keep red/draft/unproven worker work isolated.
4. Keep rolling audits current and require an independent exact-candidate PASS for formal Foundation/stage advancement.
