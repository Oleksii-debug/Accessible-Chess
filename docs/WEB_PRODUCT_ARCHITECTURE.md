# Accessible Chess — Web Product Architecture

Status: binding future architecture direction under the 2026-09-04 canonical product amendment.

## 1. Product shape

Accessible Chess should become one chess platform with at least two first-class clients:

- Windows/NVDA desktop client;
- accessible Web client.

Both clients must use the same canonical chess/application semantics.

Canonical shape:

`Windows UI / Web UI -> stable application commands/queries -> canonical chess/library/training services -> persisted state/results`

Do not create separate chess rules, PGN semantics, GameTree semantics, Library semantics, Book semantics, Teacher semantics or exercise correctness logic for Web.

## 2. Web is not remote-desktop streaming by default

A remote Windows desktop streamed through a browser may be used for diagnostics or exceptional legacy functions, but it is not the normal Accessible Chess Web product.

The normal Web edition should use semantic HTML and browser-native interaction so that keyboard users and screen readers receive real controls, headings, state and text rather than a remote image.

## 3. Shared core and replaceable presentation adapters

The following remain canonical shared services/components:
- Board/Position/Move legality;
- SAN/FEN;
- Game/GameTree/Variation;
- PGN import/export;
- Library/ACSDB;
- Books/BookDocument/BookReader/BookProgress;
- Stockfish request/result semantics;
- Teacher/Classroom session state;
- assignments/exercises/progress;
- source provenance/import reports.

Presentation-specific code may differ:
- Windows UIA/WebView2/native menu;
- browser HTML/CSS/JavaScript;
- keyboard mapping details;
- visual themes;
- platform file pickers.

But those surfaces must translate user actions into common application commands.

## 4. Web-ready command boundary

New important capabilities should be expressible through stable serializable command/query/result models where practical.

Examples:
- open game by durable identity;
- move/annotation/pointer commands;
- load position/FEN/PGN;
- request analysis;
- search Library;
- open Book location;
- save/restore reading/progress state;
- create/join Teacher/Classroom session;
- submit student answer;
- create/complete assignment.

A Windows handler should not directly mutate canonical storage when a reusable application service can own the action.

## 5. Server architecture

The commercial Web edition should use server-side application services rather than shipping the entire premium/business logic to the browser.

Server responsibilities may include:
- authentication/account identity;
- per-user/workspace data isolation;
- subscription/entitlement checks;
- Library/cloud storage;
- Teacher/Classroom session synchronization;
- assignment/course state;
- server Stockfish or bounded analysis workers;
- notifications;
- usage limits/quotas;
- audit/security events;
- backups and migrations.

The browser is an untrusted client. Modifying browser JavaScript must not grant paid access or another user's data.

## 6. Local vs server execution

Not every feature needs identical placement.

Possible split:
- ordinary board interaction may execute immediately in the client while canonical state is validated/synchronized;
- heavy database import/search may run on a server worker;
- Stockfish may run locally, in-browser where technically justified, or on the server behind one analysis contract;
- local desktop files remain a Windows capability unless explicitly uploaded/authorized;
- cloud Library and Classroom state remain server-backed.

Placement is an implementation choice; semantics remain shared.

## 7. Accounts, subscriptions and commercial security

Future commercial plans should use server-side entitlement truth.

Binding rules:
- no paid capability is unlocked only by a browser-side boolean;
- no payment secrets or provider API keys are embedded in browser bundles;
- authentication/session handling is separate from chess domain logic;
- every state-changing request validates user/workspace authorization server-side;
- tenant/user data is isolated;
- rate limits and abuse protections exist for expensive operations;
- logs never expose private credentials;
- subscription provider remains replaceable.

Possible plan structure is a product/business decision later; architecture should permit free/basic/pro/teacher/organization tiers without hard-coding one payment provider into chess services.

## 8. Accessibility requirements for Web

The Web edition must be accessibility-first independently of the Windows client.

Required direction:
- semantic HTML controls;
- full keyboard operation;
- correct accessible names, roles and state;
- predictable focus after actions/navigation;
- heading/landmark structure;
- text equivalents for board/pointer/highlight/arrow state;
- screen-reader-accessible errors and progress;
- no required drag-and-drop or mouse-only operation;
- accessible alternatives for sighted-student visual features.

Windows `NVDA_VERIFIED` does not imply Web accessibility verification.

## 9. Teacher/Classroom Web value

Teacher/Classroom is a major reason to support Web.

A target scenario:
- blind teacher may use Windows/NVDA or accessible Web controls;
- sighted student opens a browser link;
- both connect to the same durable teaching session;
- position, pointer, highlights, arrows and active-student state synchronize;
- student hover/click/selection/answer events return as structured accessible events;
- teacher controls permissions and reveal policy.

This avoids requiring every student to install the Windows program.

## 10. Data model preparation now

New durable entities should avoid being implicit local-only state.

Where relevant include:
- durable opaque IDs;
- user/workspace/session identity;
- versioned serialization;
- timestamps only where semantically needed;
- ownership/access policy;
- source/provenance;
- deterministic migration rules.

Do not put local absolute Windows paths into canonical cross-platform identities.

## 11. Development sequence

Do not start a second full UI implementation while the desktop product is still moving rapidly.

Recommended order:
1. finish current Windows release/Version 2 work;
2. enforce one application/domain core;
3. add explicit presentation/application boundaries and contract tests;
4. create a minimal read-only Web proof over real canonical services;
5. add board interaction;
6. add authentication/workspace isolation;
7. add cloud Library/progress;
8. add Teacher/Classroom synchronization;
9. add subscription/entitlement layer;
10. expand feature parity by dependency order.

## 12. Release truth

Track Web separately:
- WEB_ARCHITECTURE_READY;
- WEB_API_READY;
- WEB_BOARD_READY;
- WEB_LIBRARY_READY;
- WEB_TEACHER_READY;
- WEB_AUTH_SECURITY_READY;
- BILLING_ENTITLEMENTS_READY;
- WEB_ACCESSIBILITY_VERIFIED;
- WEB_PRODUCTION_READY.

No Web readiness is claimed merely because existing desktop screens use WebView technology.
