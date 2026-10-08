# Section 27 terminal closure audit

Status target: `DONE — TERMINAL`

Canonical plan scope: **SECTION 27 — Зворотний канал від учня і teaching interaction modes**.

This is an evidence-only finisher over the current shipping product. It does not create a second teaching, board, classroom, or chess-rules authority.

## Frozen product parent

- product branch: `converge/current-shipping-recovery-hardening-v2-20261006-c2mbezb`
- exact parent before this closure candidate: `8853acbd1a430a1c12e8118827f8718fcb7c613f`

## Dependency handling

The plan names Sections 25–26 as dependencies. Their required interfaces are already present on the exact parent and are pinned here without claiming that Sections 25 or 26 themselves are terminally closed:

- Section 25 boundary: pointer/annotation presentation is distinct from move input and does not own chess legality.
- Section 26 boundary: canonical `TeachingSession`, local Classroom scope, roles/permissions, pseudonymous local identities, pause/resume/restart-safe state.

This owner-directed out-of-order closure accepts only those exact dependency interfaces. A later change to Sections 25–26 does not authorize ordinary re-entry into Section 27; a formal `REOPENED` transition requires a concrete regression or broken accepted contract under the repository closure protocol.

## 27.1 — hover / click / selection / move are distinct structured events

Accepted authorities:

- `acs/teaching_reverse_channel.py`
  - `student.hover` and `student.click` are closed-world actions.
  - browser payload may provide only a canonical square; student identity is trusted out-of-band.
  - hover is observation only.
  - click is a selection answer only under `TeachingInputKind.SELECTION`.
- `acs/teaching_session.py`
  - `submit_selection` and `submit_move` are separate canonical transactions.
  - move input is admitted only by MOVE policy.

Exact accepted blobs:

- `acs/teaching_session.py` = `a0f74111dc5e8c0edc74cfc6b85a677d8dfa3bfc`
- `acs/teaching_reverse_channel.py` = `f3f66b65f9aad8358832e5cb441842403116f166`
- `acs/teaching_classroom_adapter.py` = `39fd13f6bf9b9537e3a5127b9022f759eea7eb62`

## 27.2 — accessible square/piece description and pointer history

`project_teacher_pointer_history` produces ordered, pseudonymized hover/selection history. `accessible_student_pointer_summary` exposes concise Ukrainian/English square and canonical piece descriptions. Raw internal student ids are excluded from the teacher payload.

## 27.3 — teaching interaction modes

`TeachingActivity` is the canonical mode vocabulary and includes:

- `TEACHER_EXPLAINS`
- `STUDENT_RESPONDS`
- `MAKE_MOVE`
- `SHOW_SQUARE`
- `SHOW_PIECE`
- `WHERE_CAN_PIECE_MOVE`
- `ATTACK_DEFENCE`
- `SOLUTION_REVEAL`

Each activity is bound to exactly one canonical input policy.

## 27.4 — teacher-controlled answer reveal and engine visibility

`TeachingInputPolicy` owns `engine_visibility` and `solution_visible`. Solution content is accepted only for `SOLUTION_REVEAL`; other activities reject it. Pause/completion force the board locked and engine hidden. Resume restores only the current step policy.

## 27.5 — presentation actions never mutate the board outside policy

The reverse-channel and annotation boundaries explicitly preserve canonical FEN for hover, selection-only click, pointer and annotation operations. Tests distinguish hover/selection from move and prove that only the canonical move transaction changes the board.

Exact accepted tests:

- `tests/test_teaching_session.py` = `1bf5ad15f80530ca1118b1b040a5889f686aa1a2`
- `tests/test_teaching_reverse_channel.py` = `41ba6dfb2e9542b4bceaa0dd6e26e21206649354`
- `tests/test_teaching_classroom_adapter.py` = `0a7c074601c23c28f7bf241687581dd05d452f99`

## Existing attributable qualification

PR #911 exact candidate `a21593efcfa7977eb4968b3c201169404df2aa46` ran **Teaching Pointer Actions Current Product** run `36901022176` successfully on both Ubuntu 22.04 and Windows 2025. The six runtime/test blobs pinned above are byte-identical on the present shipping parent.

This closure candidate adds a fresh Section 27 exact-head gate. Hosted runner QUEUED/PENDING state is not represented as PASS. Under Simplified Section Closure Protocol v3, hosted-runner unavailability may be accepted only if repository-local evidence is complete and there is no known failing Section 27 acceptance check on the frozen candidate.

## Terminal rule

After canonical integration and post-integration readback, Section 27 is terminally skipped by ordinary workers. Do not revisit or rewrite Section 27 unless the closure registry is formally changed to `REOPENED` for a concrete regression, invalid evidence, changed owner contract, or a later integration that demonstrably breaks this accepted scope.

`HUMAN_TESTED=NO`  
`NVDA_VERIFIED=NO`

Those physical acceptance flags are recorded truthfully and are not intermediate blockers under closure protocol v3.
