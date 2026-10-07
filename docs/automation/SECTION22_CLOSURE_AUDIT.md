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

The live durable registry was refreshed immediately before terminal qualification. Every canonical hard dependency is now evidence-backed `DONE — TERMINAL`:

- Sections 3–11 are terminally closed, including Section 10 tactile synchronization and Section 11 tactile input/device profiles;
- Sections 12–13 are terminally closed;
- Sections 16–20 are terminally closed, including Section 20 Media user workflow;
- Section 21 is terminally closed and is the exact Agent parent of this finisher.

Relevant late dependency integrations are Section 11 merge `4ad8976d534fb90b90e2062e2d392db27ed3db8f` and Section 20 merge `94b885c72a172ceefcfa5e82f334496c313de350`.

Section 22 therefore closes without an out-of-order dependency exception. Its tactile gateway intentionally stays on the Section-10 status/refresh boundary and does not consume Section-11 input mutation authority; its Media/Speech tools remain provider-safe and do not create Media chess truth.

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
