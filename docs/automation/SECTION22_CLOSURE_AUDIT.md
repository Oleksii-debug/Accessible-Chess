# Section 22 closure audit — Agent tools for completed domains

Canonical plan: **Section 22 — Agent tools for already completed domains**.

## Accepted scope

- **22.1** `board.*`, `gametree.*`, `engine.*`.
- **22.2** `library.*`, `formats.*`, `books.*`, `training.*`.
- **22.3** `media.*`, `speech_context.*`.
- **22.4** `tactile.*` only through already-completed tactile capability boundaries.
- **22.5** `classroom/account/web` are excluded here and remain Section 36 work.

## Canonical Agent parent

Section 21 accepted integrated authority:

`12b9094faad983db5d242d6ec485a4883f71cd6a`

This finisher extends that exact one-Agent/one-ToolExecutor authority. It does not add another model loop, chess rules implementation, parser, GameTree, engine provider, Library database, Books/Training owner, Media truth owner, or tactile device owner.

## Reused qualified capability lineages

The core domain composition reuses the already-qualified source lineages converged by PR #2317:

- continuous engine analysis: #2201;
- canonical GameTree navigation: #2203;
- canonical Library open: #2204;
- Formats capability/import-report tools: #2090;
- Books/Training presentation-state tools: #2207.

The Section-22 finisher deliberately excludes #2317's Classroom tool because the current plan assigns Classroom/Account/Web Agent integration to Section 36.

Speech context reuses the live-permission hardened successor #2213 over #2094. The tool remains read-only quoted evidence and never becomes chess truth.

Tactile Agent access is intentionally narrower than Section 36: only `tactile.status` and payload-free `tactile.refresh`. The model cannot provide a FEN, device handle, geometry, routing target, Classroom state or remote-session state. The host delegates these calls to the already-existing Section-10 tactile status/refresh action boundary.

## Dependency treatment

Durably accepted dependencies at finisher construction include Sections 3–10, 12–13 and 16–19 plus Section 21. Section 11 had a frozen complete candidate and was being terminally converged after Sections 8–10 closed; Section 20 had a bounded current Media user-workflow candidate.

The repository owner explicitly directed one-run terminal closure of Sections 21 and 22 on 2026-10-07. Consistent with the existing owner-directed out-of-order closure precedent, Section 22 is accepted only against the exact immutable interfaces it consumes. It consumes no Section-11 tactile-input/profile mutation API and no Section-20-only model authority. A later accepted Section-11/20 integration may reopen Section 22 only if it demonstrably breaks one of these pinned tool contracts.

## Safety / authority invariants

- exactly one canonical `ToolExecutor`;
- no alternate chess/rules/GameTree/engine authority;
- no model-supplied FEN through tactile tools;
- speech context permission is rechecked on every read;
- media restore remains behind the existing local-write risk/effect boundary;
- Classroom/Account/Web tools are not imported or registered by this finisher;
- bounded arguments/results continue through Section-21 ToolExecutor validation.

## Qualification

Dedicated workflow: `.github/workflows/section22-agent-domain-tools-closure.yml`.

It compiles the Agent surface and runs retained Section-21 authority tests plus focused Board/Engine/Media, GameTree, Library, Formats, Books/Training, speech-context, tactile and scope-boundary tests on Ubuntu 22.04 and Windows 2025.

Hosted runner `queued` or `pending` is not GREEN. Simplified Section Closure Protocol v3 governs external runner unavailability; any executed RED must be repaired before terminal closure.

## Terminal lock rule

After exact candidate integration and post-merge readback:

`SECTION_22_STATE=DONE_TERMINAL`

Ordinary workers must skip Section 22. Reopen only for a concrete demonstrated regression, invalid closure evidence, materially changed acceptance contract, or a later integration that demonstrably breaks this closed scope.
