# Section 26 terminal closure candidate

Canonical scope: **Local Teacher/Classroom core**.

## Acceptance mapping

- **26.1 TeachingSession/shared Board/GameTree/roles/permissions** — canonical `LessonSession` / `TeachingSessionState` own lesson flow and presentation permissions; student moves delegate to `chesscore.Board`; D09 adapters expose teacher/student audience boundaries and do not create a second chess authority.
- **26.2 lesson material/exercises/assignments locally** — terminal Section 6 owns local Training/exercise content; `ClassroomSnapshot` owns local `LessonMaterial`, `Lesson`, `Assignment`, `Homework`, results/progress, and D10 `EducationWorkspaceStore` publishes them atomically.
- **26.3 individual/group session semantics** — `LessonSession.student_ids` and optional `cohort_id`, Classroom classes/groups/cohorts, scope validation, active-student/floor control and role-safe projections cover single-student and bounded group lessons.
- **26.4 pseudonym/local identity** — canonical local `Student` uses stable local ID plus pseudonym/consent/deletion tombstone. Student projections minimize identity and never require a network account for local use.
- **26.5 restart/resume + accessible teacher control** — this finisher adds `TeachingSessionStore`: an atomic digest/CAS-protected local checkpoint of canonical plan+state. The one V2 application restores only after current Classroom scope validation, persists every accepted Teacher mutation before publication, exposes a recovery-required flag on invalid durable state, and clears the checkpoint only on an explicit successful stop. Existing keyboard/WebView Teacher controls retain pause/resume, pointer, annotations and accessible status.

## Safety and ownership

The store is persistence-only. It cannot parse chess, calculate legality, invent Board/GameTree state, own Classroom records, or trust browser identity. Corrupt, stale, mismatched, oversized and concurrent writes fail closed. A persisted session whose Classroom scope no longer validates is not published to the Teacher surface.

All declared plan dependencies are durably terminal before this closure: Sections 6, 12, 13, 14, 15 and 25.

Control: #2430.
