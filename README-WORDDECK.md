# WordDeck

WordDeck is an accessible Windows-first English-learning platform designed for keyboard-only operation and screen readers such as NVDA.

Canonical WordDeck source in this repository is **only** the `worddeck-bootstrap` branch. Do not develop WordDeck on `main` and do not migrate it to the separate `Oleksii-debug/WordDeck` repository unless the owner explicitly says `ПЕРЕНОСЬ`.

## Autonomous coordination

- Live multi-worker control: GitHub issue **#617 — WORDDECK AUTOPULSE — Continuous Full-Product Completion Control**.
- Stable worker policy: `AGENTS.md` and `WORDDECK_AUTONOMOUS_WORKER_ORCHESTRATION.md` on `worddeck-bootstrap`.
- Google Drive remains the durable product/pedagogy/control archive.

Fresh autonomous workers must recover from live GitHub + Drive rather than requiring previous chat history.

## Full product target

WordDeck is not limited to flashcards. The approved product direction includes:

- Recall and Spelling vocabulary foundations;
- Sentence/Context practice;
- active Grammar;
- Listening/Dictation and broader listening comprehension;
- Story/Course runtime;
- Reading and private local book/text ingestion;
- Word Families/Morphology;
- cross-mode adaptive mastery, Fast Track and Deep Practice;
- placement, skill diagnostics and unseen assessment;
- **Complete English Academy:** Starter/Pre-A1, A1, A2, B1, B2, C1;
- **Deep Skill Academy:** Grammar, Vocabulary/Lexical Competence, Spelling, Reading, Listening, Speaking & Pronunciation, Writing × six levels = 42 optional specialist courses;
- production text/audio/content with provenance and redistribution rights;
- durable learner state, backup, migration, export/import and recovery;
- hardened Windows packaging and later presentation-neutral portability.

Complete English must remain sufficient for the claimed level by itself. Deep Skill courses are optional specialist/remediation products.

## Current lexical foundation

The established Recall inventory is 5446 canonical entries with stable identity and study scopes All/A1/A2/B1/B2/C1. Existing accepted translation/audio assets must not be mass-regenerated without a proven bounded defect.

Personal learning state lives outside the public application payload under `%LOCALAPPDATA%\WordDeck` and must survive updates.

## Accessibility

Practical operation must remain keyboard-first with accessible names/roles, logical focus and Tab order, textual feedback and no mouse-only essential path. Native editing/list navigation must not be broken by global shortcuts.

Automated UI Automation/accessibility tests are prerequisites but do **not** prove physical NVDA acceptance. `NVDA_VERIFIED` may only be claimed for an explicitly tested artifact after real human NVDA use.

## Build

Requires .NET 8 SDK on Windows.

```powershell
dotnet publish .\WordDeck\WordDeck.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true
```

Use the repository's current GitHub Actions and release checks for authoritative build/package evidence rather than assuming a developer-tree build is release-ready.

## Data and content safety

- never ship API keys, OAuth credentials, sessions, cookies, passwords, browser profiles or private logs;
- never ship personal learner profiles/books in the public release;
- preserve UTF-8, spaces and Cyrillic Windows paths;
- back up before risky migrations/imports;
- hide/restore learner vocabulary reversibly rather than physically deleting canonical dictionary entries;
- keep private user books local by default;
- production text/audio/data requires explicit provenance/license suitable for redistribution;
- competitor platforms may inform general methodology only; do not copy proprietary lessons, exercises, dialogue wording, audio, images or UI expression.
