# Section 34 — Full Web Client closure audit

Status: CANDIDATE / exact-head qualification required

Canonical Section plan:
- Section 34: Full-fledged Web client.
- Dependencies named by the plan: Sections 12–15 and 26–33.
- Acceptance surface:
  - 34.1 semantic HTML, keyboard-first, screen-reader-accessible UI;
  - 34.2 Board/GameTree/Library/Books/Training/Media/Classroom through shared application/server contracts;
  - 34.3 not remote desktop and not a second chess program;
  - 34.4 focus, text selection/copy, errors, progress, no mouse-only action;
  - 34.5 teacher/student/browser workflows and cloud state over the same canonical services.

Owner directive:
- 2026-10-07: complete Section 34 in one closure run and, only after honest closure, mark it terminal DONE so ordinary workers do not return to it.

## Exact starting authority

Product base:
- branch: work/full-product-teacher-education-reachability-20260911
- SHA: b901573906612ad9e0f545c7747874b9f9d8a216
- PR: #645

Repository closure policy:
- root AGENTS.md / Simplified Section Closure Protocol v3.

## Existing implementation reused

This Section deliberately reuses, rather than duplicates:
- FullProductWebViewAdapter and Version2Application/Version2FinalProductApplication command/snapshot seams for Board, PGN/GameTree, Library, Books, Training, Teacher and Education;
- authenticated Classroom HTTP/RPC/runtime lineages;
- account/OAuth/security lineages;
- provider-neutral Media application contracts;
- multiplayer coordination/social contracts.

The pre-existing web/index.html is a Windows pywebview/WebView presentation and is not counted as the full Web client.

## Section 34 implementation delta

New browser-only product surface:
- acs/web_client_gateway.py
- acs/web_client_http.py
- web/accessible_chess_web.html
- web/accessible_chess_web.js
- tests/test_section34_web_client.py
- .github/workflows/section34-web-client.yml
- this audit

Properties:
- Browser identity/workspace values are not authoritative request fields. A trusted authenticated server layer must inject WebPrincipal.
- Session identity is never projected to the browser.
- Browser commands are bounded closed-world envelopes and delegate unchanged to canonical application/server services.
- The Web boundary imports no chesscore/GameTree/notation/PGN rule authority.
- The browser document is semantic HTML with landmarks/headings, native buttons, status/alert live regions, native progress, selectable text and a keyboard-navigable 64-cell grid when canonical board cells are present.
- Standard Ctrl+A/C/X/V/Z/Y editing behavior is not globally intercepted.
- The browser runtime uses fetch/same-origin server calls and contains no pywebview dependency.
- Media, Classroom, Online and Spectator are explicit browser surfaces over delegated service contracts.
- No raw path, bearer token, provider credential or session secret is added to the browser contract.

## Qualification

Dedicated workflow:
- Section 34 Full Web Client
- Ubuntu 22.04 and Windows 2025
- exact checkout proof and diff check
- Python compile
- focused Section 34 unit/negative/security/accessibility contract
- JavaScript syntax
- static no-second-chess-authority proof
- browser semantic/accessibility proof

Manual NVDA/browser acceptance is final whole-product work under Simplified Section Closure Protocol v3 and is not an intermediate Section blocker.

## Dependency discipline

Section 34 MUST NOT be marked DONE merely because this browser shell exists.
At final closure readback, dependency use must be evidence-backed by current accepted/frozen canonical authorities for Sections 12–15 and 26–33, or explicitly accepted by the owner as immutable pin-only handoffs under the repository's existing owner-directed out-of-order closure precedent.

If a named dependency is absent, mutable without an accepted pin, or demonstrably lacks the service contract required by 34.2/34.5, record the exact blocker instead of fabricating DONE.

## Terminal lock after honest closure

When all Section 34 repository-controllable acceptance requirements are satisfied and the accepted candidate is integrated:
- update SEQUENTIAL_CLOSURE_STATE.md with exact candidate/integration evidence;
- mark Section 34 DONE — TERMINAL;
- ordinary workers MUST skip Section 34;
- reopen only for a concrete demonstrated regression, invalidated closure evidence, materially changed acceptance contract, or later integration that demonstrably breaks the closed scope.
