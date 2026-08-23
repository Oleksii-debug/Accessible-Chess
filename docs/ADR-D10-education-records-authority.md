# ADR D10 — Education records authority and persistence

Status: proposed on the isolated D10 lane.

## Context

Accessible Chess already has distinct proven domain layers. D10 must extend them
without creating a second source of truth for classroom progress, training results,
chess state, or live Teacher/Classroom interaction.

A second problem appears once current `ClassroomSnapshot` state and append-only
`EducationLedger` history are both durable: two individually atomic files are not a
compound transaction. A crash after publishing one but before the other can leave a
valid Classroom and a valid ledger whose `classroom_digest` no longer matches.

## Decision

### `ClassroomSnapshot` is current educational state

`acs.classroom_domain.ClassroomSnapshot` remains authoritative for:

- students and privacy/consent/deletion state;
- classes, groups, courses, cohorts, lessons and assignments;
- current Homework state;
- assignment Result records;
- course Progress and completed lesson IDs;
- student-game references and consent-gated teacher notes.

D10 does not copy those records into another persistence model. A student-facing
D10 projection reads current `Progress` directly from the exact anchored
`ClassroomSnapshot`.

### `EducationLedger` is append-only activity history

`acs.education_records.EducationLedger` owns only records that are not current
Classroom state:

- immutable assignment submission attempts with opaque response references;
- remote/shared-session durable checkpoint metadata;
- operation receipts for at-most-once/idempotent command replay.

The ledger is content-bound to `ClassroomSnapshot.digest`. Ordinary writes fail
closed if the classroom anchor changed. `reconcile_classroom` is the only explicit
re-anchor operation and performs privacy deletion from the append-only history.

### `EducationWorkspace` is the compound publication unit

`acs.education_workspace.EducationWorkspace` does not replace either domain model.
It binds the exact current `ClassroomSnapshot` and exact `EducationLedger` and rejects
construction/reopen unless `ledger.classroom_digest == classroom.digest`.

Compound operations use copy-on-write and return a new workspace only after all
invariants succeed. In particular:

- Homework submission updates canonical current Homework state and appends immutable
  submission history as one anchored result;
- consent changes and student deletion re-anchor history in the same result;
- deletion keeps identity-minimized tombstones monotonic and purges private D10
  submission/session membership through the existing reconcile contract;
- exact operation retries may succeed even with the original stale expected revision,
  but the same operation ID with different content fails closed.

No workspace operation owns chess legality, Training evaluation, live pointer/hover,
or generic database semantics.

### Existing `StudentProgressLedger` remains training/game review authority

When the proven DEV3 progress package is composed, `acs.student_progress` remains
authoritative for append-only training/game review metrics such as attempts,
mistakes, hints, completion and engine-review metadata. D10 must reuse that model;
`EducationLedger` deliberately contains none of those fields.

### D09 owns live interaction

D10 persists only session checkpoint identity, participants, monotonic remote
sequence and a snapshot digest. D09 continues to own live TeachingSession and
Classroom interaction semantics: position, pointer, highlight, arrows, hover,
selection/click and board policy. A D10 checkpoint cannot mutate chess Position.

### D07 and D08 boundaries

D07 owns generic chess Library/ACSDB storage. The D10 file stores are education-domain
persistence only and do not become a generic database implementation.

D08 owns training content and exercise evaluation. D10 may persist references or
consume the established StudentProgress records but does not duplicate exercise
answer/evaluation logic.

## Persistence and concurrency

`EducationRecordsStore` remains a valid ledger-only persistence/exchange boundary.
It uses bounded reads/writes, SHA-256 content revisions, create-only semantics,
exact CAS, peer locking, same-directory temporary publication, fsync and atomic
`os.replace`.

It must **not** be paired with a separately published Classroom file and then treated
as a compound transaction.

When current Classroom state and D10 history are managed as one durable application
unit, `EducationWorkspaceStore` is the authoritative publication path. It stores one
versioned envelope containing both validated nested records and adds:

- exact workspace digest/anchor validation before publication and after reopen;
- one file-level SHA-256 CAS across both current state and history;
- one peer writer lock across the compound update;
- bounded read/write and strict schema/duplicate/non-finite rejection;
- same-directory temporary file + flush/fsync + one atomic `os.replace`;
- preservation of the previous complete workspace if publication fails.

Therefore no successful workspace save can expose “new Classroom + old ledger” or
“old Classroom + new ledger” as the durable state.

## Privacy

Student projections are actor-scoped: there is no arbitrary subject-student
parameter. They require the exact current Classroom anchor and an active student.
Another student's private submission response and the participant list of a shared
session are not exposed. Student deletion invalidates stale views immediately via
the Classroom digest and explicit reconciliation purges the deleted student's
append-only records and remote participant membership.

Deleted student identifiers are retained only as identity-minimized Classroom
tombstones and cannot silently disappear or revive through workspace re-anchoring.

## Consequences

This keeps one current Classroom model, one review-progress model and one append-only
education activity history while adding exactly one compound durable publication
boundary. Future database adapters may persist these contracts, but must not collapse
them into an ambiguous second chess/classroom core or bypass workspace atomicity when
both Classroom and EducationLedger are updated together.
