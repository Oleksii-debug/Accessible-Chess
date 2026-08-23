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

The last completed V0.2 Foundation candidate before the current post-Foundation integration cycle passed the authoritative Windows build/self-test, self-contained published-EXE checks, clean-public-package checks and integrated Windows UI Automation. Manual physical Windows 11 + NVDA acceptance remains a separate human gate and is not claimed by automation.

The current integration cycle has additionally incorporated:

- protected Spelling migration/recovery startup and fail-closed unreadable-state handling;
- fair finite Spelling review cycles with restart/resume coverage and read-only learning evidence;
- the Stage-11 Context foundation already present in canonical;
- the Stage-18 morphology foundation with exact stable-ID relations, provenance/license gates, bounded lookup and deterministic practice seams; no real production morphology dataset is activated;
- canonical morphology self-tests in the normal `WordDeck.exe --self-test` release path;
- the Stage-13 Grammar foundation: stable skill graph, deterministic bounded exercises/checking, error taxonomy, granular mastery/history SQLite persistence, migration/import backups, weak-vocabulary planning and privacy-tagged sentence evidence;
- one canonical cross-mode Grammar reference resolver that normalizes approved legacy aliases against the live `GrammarSkillCatalog` and fails closed on unknown IDs, preventing Story/Course from maintaining a drifting copied grammar registry.

Exact canonical Windows/release gates must be green again after each canonical product integration before the resulting head is treated as a release candidate.

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

Stage numbers describe the product roadmap, not a prohibition on safe isolated additive foundations being integrated out of order. Stage 13 and Stage 18 foundations are now present in canonical, but their complete end-user product modes/data remain unfinished.

Current validated planning baseline remains approximately **99% Foundation developer-side machine readiness before the newest post-Foundation integrations** versus approximately **46% full-product readiness**. Do not raise either number merely because an isolated foundation landed; exact current gates and independent re-estimation/audit are required. These percentages must never be conflated.

## Stage 11 context status

Canonical already contains the proven Stage-11 context foundation:

- stable-ID-aware 1/2/3-target planning;
- learner-known-vocabulary difficulty ranking;
- 30/100/200/full study-pool planning;
- bounded read-only SQLite lookup;
- exact 5446-entry coverage/gap accounting and deterministic remediation seams;
- privacy-safe interfaces for future Sentence/Grammar/Story/Reading/Book consumers.

A historical attributed EN-UA corpus is currently **measurement/evidence input only**. It is not approved as a redistributable production SentencePack and must not be bundled or relabelled as one without explicit source/license/provenance/attribution approval.

Rolling Audit A requires a strict distinction between physical written-form coverage and exact lexical-item/sense coverage. Homographic rows sharing the same spelling must remain unresolved unless POS/sense evidence disambiguates them; ambiguous surface matches must not inflate stable-ID mastery or coverage claims.

The active DEV02 successor is the only current Stage-11 worker candidate. Older DEV02 alternatives are historical evidence only. The successor must pass BOTH its exact Stage-11 Windows gate and exact attributed full-5446 SentencePack gate on the same head, then receive a fresh independent Audit-A recheck before integration. Internal technical evidence must never self-grant corpus redistribution approval.

## Stage 13 Grammar status

The additive Grammar foundation is integrated and protected by self-tests. Canonical now owns the authoritative grammar skill IDs and the cross-mode resolver. Story/Course and later modes must consume this canonical resolver or an explicit parity test; they must not carry an independent copied skill-ID registry as production truth.

This does not yet mean the full Grammar Coach UI/course experience is complete. The current foundation provides deterministic learning contracts and persistence seams for later product activation.

## Stage 18 morphology status

The additive morphology foundation is integrated and fail-closed:

- exact stable-ID relations only; equal surface spelling never merges lexical identities;
- source/license/provenance/attribution required for accepted real packages;
- invalid or uncertain rows quarantine instead of being guessed;
- deterministic bounded practice/integration projections;
- synthetic relations remain test-only;
- canonical release self-test now executes morphology regressions.

No real production morphology relation pack is approved or bundled yet.

## Active swarm integration rules

The autonomous swarm consists of isolated specialist worker branches, one canonical INTEGRATOR and two independent rolling AUDITORS.

- Only the INTEGRATOR writes `worddeck-bootstrap`.
- Workers never write canonical or `main` and never self-merge.
- Auditors remain source-read-only and do not implement fixes.
- Integrate only green, non-conflicting work after reviewing exact diffs, CI and current audit findings.
- Do not blind-merge stale worker branches.
- Worker-only CI/configuration should not be carried into canonical unless it is intentionally useful as a canonical/PR regression gate.

## Current integration blockers / cautions

- **Production SentencePack / Stage 11:** exact homograph/stable-identity correction, both successor gates and independent Audit-A recheck are still required; redistribution remains separately controlled.
- **Book/Reading:** current worker candidate remains non-integrable until its build and ambiguous-familiarity defects are corrected; exact original-source preservation should be retained.
- **Listening:** current worker candidate is still draft and its exact Listening gate must be green before integration; sentence dictation remains fail-closed without approved real sentence audio.
- **Story/Course:** current worker candidate has a previous green worker gate but remains draft; before integration it must consume the newly canonical Grammar resolver/parity contract and complete its own profile/integration readiness.
- **Morphology production data:** foundation is integrated, but no real relation dataset may ship without independently verified source/license/provenance/attribution.
- **Physical NVDA:** never claim a manual NVDA PASS until the user actually tests the exact build on a physical Windows 11/NVDA setup.

## Safety / user-data invariants

- Public releases contain no personal state/profile, secrets, credentials, private logs, browser/session data or personal hard-coded paths.
- Risky state/profile migrations or imports require backup/rollback and fail-closed handling.
- Update/reinstall must not erase progress.
- “Delete word” means reversible hide/restore, not physical removal from the canonical 5446 dictionary/audio set.
- UTF-8 and Windows paths with spaces/Cyrillic remain supported.
- Offline core learning remains functional without connected services.

## Exact next integration action

1. Re-read exact canonical Windows and V0.2 candidate results for the current product-code checkpoint; repair any regression before calling the head a release candidate.
2. Keep the DEV02 successor isolated until both exact gates are green on one head and Audit-A rechecks A-001/data/release boundaries.
3. Continue reviewing newer green non-conflicting work; do not merge draft, red, queued-only or stale candidates.
4. Reassess Story/Course only after it binds to the canonical Grammar reference resolver; retain independent auditor review before formal stage advancement.
5. Keep rolling audits current and require an independent exact-candidate PASS for formal Foundation/stage advancement.
