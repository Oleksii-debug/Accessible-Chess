# Accessible Chess — Cross-Project Reuse Acceleration Contract

Status: binding engineering guidance for Accessible Chess workers. This document does not replace live GitHub technical truth or the cross-project Drive contract.

## Canonical cross-project sources

Before implementing generic infrastructure, read the connected Google Drive source map and reuse contract first:

- `00_CROSS_PROJECT_SOURCE_MAP — Autosport + Nika Core + Autopilot + Accessible Chess — 2026-09-16`
  - file ID: `1CJV-QwoG_sjNpcvClhpQKs1IyBtwdZ_doc4vQ4LfAgM`
- `01_CROSS_PROJECT_REUSE_CONTRACT — Autosport + Nika Core + Autopilot + Accessible Chess — 2026-09-16`
  - file ID: `1NoHdgS-SM8D7f1-HIcVpoeLjHW_awJIcDq0imAbURaI`

Canonical owner repositories:

- Autosport: `Oleksii-debug/Autosport`
- Nika Core: `Oleksii-debug/Nika-Core`
- Autopilot: `Oleksii-debug/ChatGPT-Autopilot-ExtensionChatGPT-Autopilot-Extension`
- Accessible Chess: `Oleksii-debug/Accessible-Chess`

Never substitute public namesake repositories. A research claim becomes an engineering donor only after exact repo + SHA/ref + path + tests/provenance are verified.

## Worker law: search before build

Before adding any generic scheduler, event/logging layer, durable job/checkpoint layer, idempotency mechanism, tool/capability registry, model gateway, evidence/provenance format, release pipeline primitive, UI automation abstraction or generic persistence component:

1. Refresh the live Accessible Chess canonical Product/package refs, PRs, issues and Actions.
2. Search the current Accessible Chess source/tests first. Existing stronger local authorities win.
3. Search Autosport, Nika Core and Autopilot for proven equivalents and reusable adversarial tests.
4. Verify donor provenance: exact repo, SHA/ref, path, tests, dependencies/license and integration status.
5. Classify the candidate: `REUSE_NOW`, `ADAPT`, `PORTABLE_CANDIDATE`, `PRODUCT_SPECIFIC` or `DO_NOT_REUSE`.
6. Reuse/adapt only when this reduces total engineering time without creating a second authority.
7. Otherwise implement the minimum product-required capability behind a clean seam.
8. Extract a shared library only after a second real consumer needs the same stable semantic contract and conformance tests exist.

Current product delivery wins over abstract portability.

## Accessible Chess as donor

### Windows/NVDA accessibility conformance

Accessible Chess is currently the strongest first-party donor for Windows accessibility/release conformance knowledge. Reusable invariants include:

- process-scoped Windows UIA evidence rather than screenshots or DOM-only assertions;
- exactly 64 logical accessible board squares;
- Move Input remains a real edit control;
- native `Ctrl+A` / `Ctrl+C` semantics are not intercepted;
- visible semantic text -> real selection -> native `Ctrl+C` -> exact clipboard;
- focus continuity after valid operations;
- invalid input is atomic;
- native MenuBar structure is machine-proven separately from human NVDA usability;
- bounded evidence must not leak local paths, tracebacks or provider internals;
- `machine UIA PASS != HUMAN_TESTED != NVDA_VERIFIED`.

Reuse mode: **conformance/test/evidence knowledge first**. Do not transplant chess UI implementation into other products merely to share code.

### Deterministic release/source/artifact evidence

Portable release knowledge includes:

- exact Product SHA binding;
- same-lineage package ancestry;
- no force-push of shared release history;
- pinned toolchain/runtime dependencies;
- deterministic payload/ZIP assembly;
- checksums and exact source/artifact provenance;
- fresh extraction before runtime qualification;
- artifact upload/download byte-identity readback;
- post-restart verification;
- separate machine/human verification flags.

Product-specific payload builders and chess resources remain local.

### Durable recovery and atomicity

Reusable adversarial-test knowledge includes:

- invalid operation must not partially mutate canonical state;
- startup/upgrade failure precedence and cleanup must remain observable;
- recovery must preserve canonical data identity;
- save/reopen and crash/restart paths must not create silent split-brain state;
- evidence should bind exact state/revision/SHA instead of relying on narrative reports.

Prefer sharing conformance tests/failure taxonomy before sharing persistence implementation.

## Accessible Chess as conditional consumer

### Nika external-effect idempotency — future remote/shared Classroom only

Verified donor path: `Oleksii-debug/Nika-Core`, `src/nika_core/runtime/idempotency.py`.

The verified contract provides:

- `PENDING`, `COMPLETED`, `UNCERTAIN` states;
- `operation_key` plus input-fingerprint conflict protection;
- one durable reservation winner;
- no blind replay of already-pending or uncertain effects;
- process-loss promotion of leftover pending effects to uncertain;
- explicit release only when a pending effect is proven not applied;
- reconciliation before an uncertain effect can be marked completed.

Potential Accessible Chess target exists only when Remote/shared lessons introduce real replayable external effects such as remote lesson delivery, assignment dispatch, student/teacher action acknowledgement or remote session commands.

Do **not** insert this ledger into local chess moves, PGN editing, ACSDB search/import, Books/Training navigation, Teacher presentation state or other in-process canonical actions.

### Autopilot / Nika agent infrastructure

No current Accessible Chess dependency justifies importing a universal agent runtime, ToolRegistry, model gateway, scheduler, event bus or browser authority. Revisit only when a concrete product requirement appears and exact current donor source is verified.

## Chess-owned do-not-share boundaries

The following remain Accessible Chess authorities and must not be generalized merely for reuse:

- canonical chess rules/state;
- PGN + GameTree semantics;
- ACSDB / Library / Search domain rules;
- ChessBase adapters and corruption/security policies;
- Stockfish integration/product semantics;
- Books / Training semantics;
- Teacher / Classroom / Classes / Students / Lessons / Assignments / Progress;
- board selection, hover, pointer, focus and move semantics;
- visual/nonvisual UI convergence through one chess/application core;
- NVDA-facing presentation/privacy rules.

No second chess core, database authority, scheduler, event authority or clipboard/copy authority.

## Cross-project extraction candidates after release-critical work

Potential shared conformance families, only after a second consumer actively adopts them:

- `AccessibilityConformance`
- `ReleaseSourceTruthConformance`
- `EvidenceProvenanceConformance`
- `DurableRecoveryConformance`
- `IdempotentExternalEffectConformance`
- `SemanticInteractionConformance`

A test suite may be portable even when domain/runtime code must remain local.

## Current release snapshot — refresh before acting

Snapshot captured 2026-09-16 from live GitHub:

- canonical Product branch: `work/full-product-teacher-education-reachability-20260911`
- observed Product head: `bd849204bf0ce0d510815a7525ff2cec59ee16d7`
- that head merged PR #771 for packaged modern WinForms accessibility policy;
- sole package lineage: `work/post-freeze-v2-windows-package-qualification-20260911`
- observed package head: `9e8ef73138156421f50e00043a041c59d690c9d0`
- package run #26 / Actions run `34903624367` is RED;
- do not infer current readiness from this snapshot: refresh live refs/CI before any release conclusion.

Cross-project docs must not mutate canonical Product merely to keep documentation current during an exact-SHA release chain. Prefer a separate docs branch/PR until release qualification is stable.

## Immediate engineering priority

1. Do not interrupt the current Accessible Chess Windows release chain for speculative reuse work.
2. Diagnose and fix the exact current package run failure without weakening acceptance.
3. Finish machine qualification and artifact readback.
4. Only after the release-critical chain is stable, consider extracting the accessibility/release conformance schemas if another project is an active second consumer.
5. Future remote/shared Classroom transport must consult the verified Nika idempotency contract before implementing replay/retry semantics from scratch.

Binding principle:

`BUILD ONCE -> PROVE IN PRODUCT -> EXTRACT WHEN MULTICONSUMER -> REUSE.`
