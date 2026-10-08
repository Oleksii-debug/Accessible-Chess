# Section 28 terminal closure audit

Status target: `DONE — TERMINAL`

Canonical plan scope: **SECTION 28 — Students, classes, courses, assignments, progress і child UX**.

This is an evidence-only finisher over the current shipping product after terminal integration of Section 27. It does not create duplicate Classroom, Education, Training, TeachingSession, child-coaching, rating, progress, or chess-rules authorities.

## Frozen product parent

- product branch: `converge/current-shipping-recovery-hardening-v2-20261006-c2mbezb`
- exact parent before this closure candidate: `06c1ef2e6b3afa7e94341052772eaae2e954b8cb`
- Section 27 terminal product integration: same parent, via PR #2431.

## Dependency handling

The canonical plan names Sections 6, 26, and 27.

- Section 6 is already terminally closed in the canonical closure registry and remains the training/mastery/resume authority.
- Section 27 is terminally integrated on the exact parent above.
- Section 26 is not falsely marked DONE here. Section 28 accepts only its already-integrated local Teacher/Classroom interfaces on this exact product tree: canonical TeachingSession scope, local Classroom identities, roles/permissions, lesson material/assignments, group/cohort semantics, and resume-safe state.

A later Section 26 change does not authorize ordinary re-entry into Section 28. Re-entry requires a formal `REOPENED` transition for a concrete regression, invalid closure evidence, changed owner contract, or later integration that demonstrably breaks this accepted scope.

## 28.1 — classes, groups, cohorts, students, levels, ratings, courses

Canonical durable classroom entities are defined by `acs/classroom_domain.py`:

- `Student`
- `ClassroomClass`
- `Group`
- `Course`
- `Cohort`
- `Lesson`
- `Assignment`

The domain validates class/group, course/lesson, cohort/course/group, and cohort/student referential integrity.

Child-coaching learning level is explicit and bounded through `LessonLevel` and `AgeBand` in `acs/child_coaching.py`. Rating-aware pair creation is explicit through `PairingMode.RATING` and an exact per-student rating mapping in `acs/classroom_pairing.py`. The pairing boundary deliberately does **not** invent or silently persist a second student-proficiency authority: rating data must be explicitly supplied and exactly cover the participating students.

## 28.2 — homework, pair tasks, student games, review

`ClassroomSnapshot` owns current-state:

- `Assignment`
- `Homework` with assigned / in-progress / submitted / returned lifecycle
- `StudentGame`
- `Result`

`acs/classroom_pairing.py` owns deterministic pair-play launch plans without owning chess game state. Pairings are scoped to one canonical `LessonSession`, preserve exact start FEN, reject unavailable/out-of-scope students, support sequential/random/rating modes, and make retry/reconnect identity explicit.

`acs/student_progress.py` owns append-only training/game review records and deterministic summaries.

## 28.3 — progress, mastery, results, history, assignment lifecycle

- `ClassroomSnapshot.Progress` owns current course/lesson completion state.
- `ClassroomSnapshot.Result` owns current assignment result state.
- `EducationLedger.SubmissionRecord` is immutable append-only assignment-attempt history; retries do not overwrite prior attempts.
- `StudentProgressLedger` records training/game review history, attempts, mistakes, hints, completion, accuracy, and bounded engine-review metadata.
- `education_progress_transaction.py` and `education_progress_lifecycle.py` coordinate progress publication, deletion/privacy, and CAS-safe lifecycle behavior.
- Training mastery remains the already-accepted Section 6 authority and is not duplicated by Section 28.

## 28.4 — age-adaptive child learning and beginner/no-notation UX

`acs/child_coaching.py` provides:

- age bands: preschool 4–6, young beginner 7–8, school age 9–10, strong child;
- lesson levels: beginner, developing, advanced;
- bounded lesson blocks including readiness, warm-up, recap, concept, demonstration, pointer task, guided response, exercise, mini-game, supervised game, attention break, review, and homework;
- explicit `notation_required` with a whole-template `no_notation_required` predicate;
- pointer tasks constrained to selection-only semantics so they cannot mutate board state;
- explicit student engine visibility rather than implicit leakage.

`acs/child_coaching_context.py` projects factual progress context without inventing proficiency state. `acs/child_coaching_projection.py` provides semantic Ukrainian/English teacher/student surfaces.

## 28.5 — versioned lesson templates, prepared positions, visibility boundaries

- `LessonTemplate` is versioned, digest-bound, bounded, editable, and compiled through the canonical `LessonSession` authority.
- `EducationWorkspace.PreparedPosition` remains the durable prepared-position authority.
- `child_coaching_prepared_positions.py` gives deterministic current/next/previous navigation and launches only reviewed exact prepared-position revisions.
- `classroom_prepared_position_deployment.py` binds prepared positions to exact lesson/student/group scope with revision checks and retry identity.
- `ChildCoachingProjection.student_preview` calls the template projector with `include_teacher_notes=False`.
- target square, target piece, solution text, and teacher note are added only to the teacher projection; they are omitted from the student preview.
- student engine visibility remains an explicit block policy.

## Exact accepted runtime blobs

- `acs/classroom_domain.py` = `99f4683e3a0dc272e6e88bb5fccec8bd4a157a5c`
- `acs/child_coaching.py` = `0d9bc76db6ddb0bc943a4569361859ba8ba0ac6a`
- `acs/child_coaching_projection.py` = `48b71553685e05be435388a31b44b8df2aeb5dc1`
- `acs/child_coaching_context.py` = `890fcc1d6cd57c1555e02a435d835d1d3fc75c4d`
- `acs/child_coaching_prepared_positions.py` = `060fb8cee23c7fe22465208268b4b8fef5760d14`
- `acs/classroom_pairing.py` = `fee36f2029759d0c948c58cd3ca37ac20bbb0be4`
- `acs/classroom_prepared_position_deployment.py` = `d760cf1a6c7e900fdc1f607c6bc4524510198948`
- `acs/education_workspace.py` = `0288d1895472b9e4ead9389e910ffcdf872019e0`
- `acs/education_records.py` = `6f42c311357731e0ecc812973f6cb48339fc8fc5`
- `acs/education_progress_transaction.py` = `5d3f3b86684ab02bfa578af9c8a6ccac084fa66e`
- `acs/education_progress_lifecycle.py` = `7bb318f40ad58aab23f696abd0012e62544e072e`
- `acs/student_progress.py` = `a470afdaff99413a1163e52192a0f12ee8b54671`

## Exact accepted test blobs

- `tests/test_child_coaching.py` = `8b1c4686d94ff8c234123ef905e0e4144a5f2a4e`
- `tests/test_child_coaching_projection.py` = `d3de779725cf54c100675098a22fd41330d5d790`
- `tests/test_child_coaching_context.py` = `33e575d589761bb162479eea9f5e1ad06153998e`
- `tests/test_child_coaching_prepared_positions.py` = `6999fca59274c9e1afd7159bab23e544ca6614a7`
- `tests/test_classroom_pairing.py` = `dfe1e5aa3676b9ca966d3d93a60f98b554b8b281`
- `tests/test_classroom_prepared_position_deployment.py` = `1495f03e4dae89284afc4cb7f72b2ddd4a6741b2`
- `tests/test_education_records.py` = `d850eb75104e5710075202341f85da4524b729d8`
- `tests/test_education_workspace.py` = `2c24f9d43744a37b6ee8df15442a79e329653968`
- `tests/test_dev3_student_progress.py` = `41efaa9a52a871aad405238a327fdda86b70d67a`
- `tests/test_education_create_resume_journey.py` = `fc08dd979116360f114aedb6e406389fa4aceffe`
- `tests/test_version2_prepared_child_lesson_binding.py` = `28d08fbf31c043418bf205a5fe7f468d632dc988`
- `tests/test_student_progress_final_product_binding.py` = `680f224f0cded8ce4a8edcf3e55bbfd081a5e698`
- `tests/test_version2_group_rotation_binding.py` = `a3d8e457673b48bc707c938a9d4cc5ac5b942344`
- `tests/test_child_coaching_keyboard_actions.py` = `0e208bd15c0ba51d450718af9e53690d605a1e07`
- `tests/test_full_product_education_keybindings.py` = `d8cec0584a312abaf0a498e0d58545dc32a29f1b`

## Existing attributable qualification and superseded RED

At merged child-coaching candidate `9d07a3a35bc04a974cbbbf03d656e6064026ea5b`, **Child Coaching Current Apex** run `37459208761` completed SUCCESS. The current `child_coaching.py`, `child_coaching_projection.py`, and their direct tests are byte-identical to that successful evidence.

Some adjacent runs on that older candidate were RED. They are not hidden or treated as green. Their concrete causes included a missing test import for `advance_rotation`, an obsolete teacher-session replacement expectation, and an adjacent accessibility/bootstrap oracle. The current shipping tree has superseding test/runtime blobs; for example, the keyboard test now explicitly imports `advance_rotation`, and the teacher-session scope test now asserts the canonical `TeachingSessionError` before state publication.

A fresh Section 28 exact-head gate is registered by this finisher. QUEUED/PENDING is not PASS. Under Simplified Section Closure Protocol v3, hosted-runner unavailability may be accepted only after exact readback, complete repository-controlled evidence, and absence of any known failing Section 28 acceptance check on the frozen candidate.

## Terminal rule

After canonical integration and post-integration readback, Section 28 is terminally skipped by ordinary workers. Do not revisit or rewrite Section 28 unless the closure registry is formally changed to `REOPENED` for a concrete regression, invalid evidence, changed owner contract, or a later integration that demonstrably breaks this accepted scope.

`HUMAN_TESTED=NO`  
`NVDA_VERIFIED=NO`

Those physical acceptance flags are recorded truthfully and are not intermediate blockers under closure protocol v3.
