# WordDeck autonomous completion instructions

This branch is the canonical WordDeck source. Chat history is not.

## Identity lock

Project: **WordDeck** inside `Oleksii-debug/Accessible-Chess`.
Canonical branch: **`worddeck-bootstrap`**.
Never develop WordDeck on `main`.
Never migrate code to `Oleksii-debug/WordDeck` unless the owner explicitly says `ПЕРЕНОСЬ`.
Ignore Accessible Chess AUTOPULSE routing when working on WordDeck; it is another product sharing the repository.

Canonical live coordination: **GitHub issue #617 — WORDDECK AUTOPULSE**.
Stable operating policy: `WORDDECK_AUTONOMOUS_WORKER_ORCHESTRATION.md`.

## Truth order

1. Live `worddeck-bootstrap`, exact PR/branch heads, reproducible tests/Actions and release artifacts.
2. Issue #617 for current ownership, queue and material checkpoints.
3. Current WordDeck Drive control: WORKFLOW_RULES, ACTIVE_EXECUTION_MODE, CURRENT_STATE, STAGE_PLAN, FULL_PRODUCT_ROADMAP, PEDAGOGICAL_MASTER_PLAN, LATEST_REPORT, LATEST_AUDIT, NEXT_TASK and relevant completed MASS reports.
4. Older reports/chats only as history.

If prose and live code/evidence disagree, verify live source/tests instead of guessing.

## Goal

Optimize `DISTANCE_TO_FINISHED_WORDDECK`, not PR count, report count, test count or activity.

The full target is an accessible commercial English-learning platform:
- existing Recall/Spelling/Sentence foundations;
- Complete English: Starter/Pre-A1, A1, A2, B1, B2, C1;
- 42 optional Deep Skill courses: Grammar, Vocabulary/Lexical Competence, Spelling, Reading, Listening, Speaking & Pronunciation, Writing × six levels;
- placement, skill diagnostics and unseen exit assessment;
- Fast Track for proven mastery and Deep Practice for evidence-backed weakness;
- grammar, listening, reading/books, story/course, morphology and adaptive routing;
- production content/audio with provenance;
- safe learner state, migration, backup/export/import/recovery;
- keyboard/NVDA accessibility and hardened Windows release.

Architecture or curriculum documents alone do not finish the product. Production content, real runtime wiring, assessment and packaged user journeys must exist.

## Maximum final-product scope lock — 2026-09-11

The mandatory core is larger than the original Foundation/MVP. Workers must preserve and advance the whole product, not stop after a green vocabulary release.

Mandatory completion includes:
- six complete Complete English courses through C1, each independently sufficient for its target level;
- 42 optional Deep Skill courses, never hidden prerequisites for Complete English;
- Recall, Spelling, Sentence/Context + Sentence Spelling, active Grammar, Dictation/Listening, Story/Micro Stories, Narrative Course, Real Reading/private-book ingestion, Word Families/Morphology and one cross-mode adaptive learner model;
- production Speaking & Pronunciation runtime with microphone/response workflows, interaction/sustained-speech tasks and honest ASR/pronunciation limits;
- production Writing/free-response runtime with composing, revision/editing, genre/register tasks, rubrics and feedback;
- Quick Placement, Full Skills Diagnostic, module/checkpoint/retention tests, unseen level exits, separate skill profiles, versioned assessment pools, item-exposure tracking, retake reserves/parallel forms, attempt history and resume;
- level-appropriate production audio, including multi-speaker/connected speech and human/native material where advanced listening/pronunciation quality requires it;
- sufficient original/licensed production lessons, explanations, dialogues, stories, reading texts, listening scripts/audio, speaking/writing tasks, grammar/lexical exercises, assessment banks, metadata, provenance and QA. Samples/fixtures/architecture alone are not course completion.

Competitive target: WordDeck may aim to be measurably stronger than mainstream apps in proficiency gained per focused hour, reduced redundant practice through evidence-gated Fast Track, depth of explanations, productive Speaking/Writing, genuine B2/C1 performance, transparent skill diagnostics/remediation and accessibility. Do not claim superiority without credible pilot/assessment evidence.

### Tracked advanced/someday expansion register

These previously discussed capabilities must remain visible and architecture-compatible, but do not outrank a nearer mandatory-core blocker unless the owner later promotes them:
- My Corrector integration/evidence-sharing seam; it remains a separate companion unless explicitly merged;
- optional bounded AI for difficult explanations, personalized examples/stories and free-form speaking/writing assistance; AI never silently owns canonical mastery, CEFR certification or irreversible progress;
- custom/personal learning content, user vocabulary/books/texts and future custom course/module packs with versioned schemas, privacy and provenance;
- professional visual design, optional accessible image cards, Blazor Hybrid/semantic HTML and later real web frontend reusing Core/Application learning logic;
- optional secure accounts/authentication, profile/cross-device sync, subscriptions/entitlements, announcements/update metadata and privacy-preserving aggregate telemetry without accidentally breaking offline learning;
- optional future social/community learning and teacher/classroom layers with consent/privacy and full keyboard/NVDA parity.

## Parallel work

Repeated autonomous runs may overlap. Before mutation, read #617 and refresh remote source/PR state.

One active production owner per overlapping source surface. Existing incumbent/canonical lineage wins. Do not create competing Sentence, Grammar, Reading, Adaptive, state, course-runtime, assessment or packaging implementations.

Issue comments are coordination evidence, not atomic locks. If ownership is uncertain, do not race shared files; choose another disjoint blocker, review, content slice, test, qualification or integration-preparation task.

Prefer `REUSE -> REPAIR -> CONVERGE -> EXTEND`.
Finish near-ready candidates before new features.

Technical WIP target is initially at most six active overlapping implementation packages. If several reviewed candidates wait for integration, drain the queue before opening more feature PRs.

Pedagogical/content work can scale wider only with disjoint ownership by course/module/content type and isolated artifacts. Only a designated pedagogical integrator updates canonical pedagogical documents.

## Technical discipline

Use isolated branches/PRs for production source unless issue #617 records safe canonical integration authority. Only one integration owner may promote to `worddeck-bootstrap` at a time.

Preserve:
- stable lexical identity and homograph/POS/sense separation;
- Oxford Recall total 5446 and accepted translations/audio unless a proven defect requires bounded repair;
- `%LOCALAPPDATA%\WordDeck` personal-state boundary;
- backup before risky migration/import;
- reversible hide/restore;
- clean public release without personal state or secrets;
- UTF-8, spaces and Cyrillic paths;
- offline-capable core behavior;
- platform-neutral domain/application contracts where future UI/web portability matters.

Exposure, reveal, lesson completion and XP are not mastery. AI must not silently become canonical progress authority.

## Accessibility

Primary user is blind, Windows 11 + NVDA. Full keyboard operation, logical focus/Tab order, accessible names/roles, textual feedback and no mouse-only function are mandatory. Standard editing/list controls keep native arrow behavior; special Recall Up/Down behavior remains scoped to the card surface.

Automated UIA/accessibility checks are prerequisites, not physical NVDA proof. Never claim `NVDA_VERIFIED=true` without actual human evidence on the named artifact.

## Content and pedagogy

Complete English must independently teach all skills required for its level. Deep Skill courses are optional specialist/remediation products. Current approved ceiling is C1.

CEFR level claims require Can-Do/performance evidence, not Oxford counts or lesson completion. Production text/audio/data must have commercial provenance/redistribution rights. Competitors may inform general methodology only; never copy protected exercises, explanations, dialogue wording, audio, images or UI expression. Private user books stay local/private by default.

## Every run

Recover live truth -> collision check -> select highest-value free critical-path package -> execute a large coherent batch -> verify -> persist recoverable work -> publish only a material checkpoint -> refresh live truth -> continue if useful work remains.

Do not stop merely after one fix, commit, PR, report or green test.

Checkpoint in #617 only for material change, using: `INSTANCE_TAG`, `ROLE`, `TRACK`, `OWNED_SCOPE`, `PRODUCT_MOVEMENT`, `PR_OR_ARTIFACT`, `EVIDENCE`, `BLOCKER_OR_HANDOFF`, `NEXT_ACTION`. If no actual delivery occurred, state `RUN_NO_DELIVERY_CREDIT`.
