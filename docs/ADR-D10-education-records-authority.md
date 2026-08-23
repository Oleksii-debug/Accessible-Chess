# ADR D10 — Education records authority and persistence

Status: proposed on the isolated D10 lane.

## Context

Accessible Chess already has distinct proven domain layers.  D10 must extend them
without creating a second source of truth for classroom progress, training results,
chess state, or live Teacher/Classroom interaction.

## Decision

### `ClassroomSnapshot` is current educational state

`acs.classroom_domain.ClassroomSnapshot` remains authoritative for:

- students and privacy/consent/deletion state;
- classes, groups, courses, cohorts, lessons and assignments;
- current Homework state;
- assignment Result records;
- course Progress and completed lesson IDs;
- student-game references and consent-gated teacher notes.

D10 does not copy those records into another persistence model.  A student-facing
D10 projection reads current `Progress` directly from the exact anchored
`ClassroomSnapshot`.

### `EducationLedger` is append-only activity history

`acs.education_records.EducationLedger` owns only records that are not current
Classroom state:

- immutable assignment submission attempts with opaque response references;
- remote/shared-session durable checkpoint metadata;
- operation receipts for at-most-once/idempotent command replay.

The ledger is content-bound to `ClassroomSnapshot.digest`.  Ordinary writes fail
closed if the classroom anchor changed.  `reconcile_classroom` is the only explicit
re-anchor operation and performs privacy deletion from the append-only history.

### Existing `StudentProgressLedger` remains training/game review authority

When the proven DEV3 progress package is composed, `acs.student_progress` remains
authoritative for append-only training/game review metrics such as attempts,
mistakes, hints, completion and engine-review metadata.  D10 must reuse that model;
`EducationLedger` deliberately contains none of those fields.

### D09 owns live interaction

D10 persists only session checkpoint identity, participants, monotonic remote
sequence and a snapshot digest.  D09 continues to own live TeachingSession and
Classroom interaction semantics: position, pointer, highlight, arrows, hover,
selection/click and board policy.  A D10 checkpoint cannot mutate chess Position.

### D07 and D08 boundaries

D07 owns generic chess Library/ACSDB storage.  The D10 file store is education-domain
persistence only and does not become a generic database implementation.

D08 owns training content and exercise evaluation.  D10 may persist references or
consume the established StudentProgress records but does not duplicate exercise
answer/evaluation logic.

## Persistence and concurrency

`EducationRecordsStore` wraps a versioned envelope around `EducationLedger` and uses:

- bounded reads/writes;
- SHA-256 content revisions;
- create-only `expected_revision=None`;
- exact compare-and-swap for updates;
- peer writer lock;
- same-directory temporary file + flush/fsync + atomic `os.replace`;
- corruption and unknown-schema rejection.

A stale/busy/failed writer cannot partially replace the last durable file.

## Privacy

Student projections are actor-scoped: there is no arbitrary subject-student
parameter.  They require the exact current Classroom anchor and an active student.
Another student's private submission response and the participant list of a shared
session are not exposed.  Student deletion invalidates stale views immediately via
the Classroom digest and explicit reconciliation purges the deleted student's
append-only records and remote participant membership.

## Consequences

This keeps one current Classroom model, one review-progress model and one append-only
education activity history.  Future database adapters may persist these contracts,
but must not collapse them into an ambiguous second chess/classroom core.
