# WordDeck continuous autonomous completion policy

Operating mode: repeated autonomous workers may start every few minutes and overlap. The purpose of this policy is to turn those overlapping runs into cumulative delivery rather than duplicate PRs, duplicate curriculum or repeated audits.

Canonical live coordination: GitHub issue #617.
Canonical source branch: `worddeck-bootstrap`.

## 1. Delivery objective

Finish the **entire WordDeck product**, not one MVP and not only the current vocabulary tools.

Two connected outcomes must converge:

**Technical product:** accessible Windows application with durable learner state, Recall, Spelling, Sentence/Context, Grammar, Listening, Story/Course runtime, Reading/books, Morphology, adaptive mastery, diagnostics/assessment, audio/content packs, packaging, update/recovery and later presentation-neutral portability.

**Pedagogical product:** six Complete English courses (Starter/Pre-A1 through C1), 42 optional Deep Skill courses, production lessons/content/audio scripts, assessment pools/rubrics, Fast Track, Deep Practice, QA, provenance and effectiveness evidence.

Neither outcome is finished by architecture documents alone.

## 2. Fresh-run recovery

Every new run must recover from durable sources; it must not require an earlier chat transcript.

Read in this order:
1. `AGENTS.md` and this policy.
2. issue #617 current overview/checkpoints.
3. live `worddeck-bootstrap`, open WordDeck-relevant PRs/branches and current Actions/evidence.
4. WordDeck Drive control documents and relevant completed MASS reports for the chosen scope.

Do not reread every old document/branch if unchanged. Use current authoritative material and exact evidence.

## 3. Dynamic role selection

No repeated worker has a permanent narrow role. Select the role that most reduces the current critical path:

`BUILD`, `REPAIR`, `CONVERGE`, `TEST`, `QUALIFY`, `REVIEW`, `INTEGRATION_READINESS`, `INTEGRATE`, `RELEASE`, `ACCESSIBILITY`, `STATE`, `SENTENCE`, `GRAMMAR`, `LISTENING`, `READING`, `COURSE_RUNTIME`, `ASSESSMENT`, `AUDIO`, `CONTENT_PRODUCTION`, `CURRICULUM_SYNTHESIS`, `LINGUISTIC_QA`, `CEFR_AUDIT`, `RIGHTS_QA`, `PILOT`, `CLOSE`.

Choose by one question: **what can this run actually finish or materially advance that most shortens the path to the complete product?**

## 4. Collision and ownership

A new run must check whether the intended surface already has:
- a current owner/checkpoint in #617;
- an active incumbent PR/branch;
- a newer successor;
- already integrated work;
- a candidate waiting only for review/CI/integration.

Existing viable ownership has priority. Do not fork a competing implementation merely because another run is slow.

Comments and timestamps are not hard locks. If liveness/ownership is ambiguous, route to another disjoint task. Create a random `INSTANCE_TAG` as tie-break/shard when several free tasks have comparable value.

For source code, tests/workflows touching the same behavior count as overlapping ownership. For pedagogy/content, overlap is by course + module + skill/content type, not only filename.

## 5. WIP and integration pressure

Initial technical WIP target: maximum six active overlapping implementation packages across all repeated runs. Other capacity should review, test, prepare integration, work on disjoint content/pedagogy, or close other blockers.

If three or more reviewed technical candidates are waiting for integration, pause new technical feature creation and drain the integration queue.

One integration owner at a time promotes to `worddeck-bootstrap`. If safe integration authority is not clearly established, prepare an exact `READY_FOR_INTEGRATION` handoff and continue another task.

Pedagogical/content work may use much higher parallelism when slices are disjoint. No swarm worker directly rewrites the shared canonical pedagogical master unless #617 records it as the current pedagogical integrator.

## 6. Finish-first decision order

Before new implementation, check whether existing work can be brought to DONE cheaper.

Priority normally is:
`REUSE -> REPAIR -> CONVERGE -> QUALIFY -> INTEGRATE -> EXTEND`.

A nearly complete candidate missing one repair, exact test, semantic review or integration is normally more valuable than a new PR.

Do not create second schedulers, state stores, grammar engines, sentence engines, reading engines, course runtimes, assessment systems, audio registries or release frameworks when a viable canonical implementation exists.

## 7. Technical finish line

Technical capability receives real delivery credit only when it is reachable through the actual product, preserves state/restart behavior, has meaningful failure handling and relevant tests, and can participate in the packaged Windows journey.

The final user chain must support keyboard-only/NVDA-oriented operation and durable progress through the actual installed/extracted application. Developer-tree-only classes, test fixtures or backend services not connected to the user path are not complete product capabilities.

Personal state stays outside public releases in `%LOCALAPPDATA%\WordDeck`. Updating must not erase progress. Risky migration/import needs backup/recovery. Public artifacts must contain no credentials, personal paths, profiles, books or private state.

## 8. Learning-system finish line

The product must eventually provide:
- Recall and Spelling foundations;
- real Sentence/Context progression;
- active Grammar;
- Listening with appropriate human/TTS assets by level;
- Reading/private-book workflows;
- Speaking/Pronunciation and Writing course capability;
- six Complete English courses to C1;
- 42 optional Deep Skill courses;
- skill diagnostics and unseen assessments;
- adaptive next-step routing;
- Fast Track based on demonstrated mastery;
- Deep Practice based on diagnosed weakness.

`Exposure`, `Reveal`, `LessonComplete`, `XP` and streaks cannot independently create mastery evidence. One strong skill cannot mathematically hide a severe failed skill in a level claim.

## 9. Content-production discipline

Mass content is allowed when ownership is explicit and the relevant schema/level contract is stable enough for that slice. Workers may produce full modules/large content packets, not tiny filler batches.

Every production item needs stable identity and appropriate metadata: course/level/module/skill, target grammar/lexis where relevant, answer/rubric, audio/source relationships, provenance/license and QA state.

Generated content is not automatically legally safe. Competitor products are methodology references only. Production course text/dialogues/audio must be independently authored or lawfully licensed with redistribution rights.

## 10. Accessibility

All practical user actions must be keyboard reachable. Avoid mouse-only interaction, visual-coordinate dependence, colour-only meaning and inaccessible custom surfaces. Educational alternatives for blind learners must preserve the learning difficulty rather than reveal the answer.

Automated UIA is not human NVDA evidence. `NVDA_VERIFIED=true` is reserved for actual human testing of the named artifact.

## 11. Waiting and blockers

A blocked task does not block the run. If the blocker can be repaired within scope, repair it. If another owner controls it, leave one precise handoff and choose another independent high-value task.

`QUEUED` CI is not failure. Do not create duplicate workflows/PRs because a runner has not started. While waiting, work on a disjoint productive package.

## 12. No circular work

Do not use a run primarily for:
- broad status audit with no delivery;
- another planning document when implementation/content can advance;
- repeated unchanged-head review/CI;
- status-only PR/commit;
- cosmetic cleanup over a product blocker;
- duplicate implementation;
- synthetic/fixture evidence presented as production content;
- rewriting accepted Oxford translations/audio without a proven defect.

## 13. Long-run behavior

After finishing one coherent package, refresh live state. If useful authorized work remains, take the next compatible critical-path package and continue. Do not stop because one PR, report, test or green CI completed.

Stop only when the product goal is actually complete, the execution environment physically prevents further useful work, or every remaining useful task is genuinely blocked/owned.

## 14. Checkpoints

Issue #617 is the machine-readable live coordination surface. Post only material transitions, not heartbeat spam.

Allowed transitions include: `CLAIM`, `DEFECT_PROVEN`, `HEAD_CHANGED`, `CI_TERMINAL`, `READY_FOR_INTEGRATION`, `INTEGRATED`, `CONTENT_READY`, `HANDOFF`, `RUN_END`.

Minimum fields:
- `INSTANCE_TAG`
- `ROLE`
- `TRACK`
- `OWNED_SCOPE`
- `PRODUCT_MOVEMENT`
- `PR_OR_ARTIFACT`
- `EVIDENCE`
- `BLOCKER_OR_HANDOFF`
- `NEXT_ACTION`

If the run produced no real movement, state `RUN_NO_DELIVERY_CREDIT`.

## 15. Drive

Drive remains the durable pedagogical/control archive and source for current scope/requirements. Do not create a full Drive report for every trivial technical heartbeat. Save substantial pedagogical research/content or required project-control updates there under unambiguous titles, and read back writes before claiming success. GitHub #617 remains the live multi-worker coordination surface.
