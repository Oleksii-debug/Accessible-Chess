# Acceptance and gates

## General definition of done

A package is complete only when:
- the intended behavior is implemented through the canonical architecture;
- negative/error paths are covered;
- relevant focused tests pass;
- full regression tests pass unless an unrelated pre-existing failure is independently proven and documented;
- the diff contains no accidental future-stage contamination or unrelated rewrites;
- user-facing output remains concise and accessible;
- the exact commit is pushed to a persistent branch;
- CI for that exact SHA is inspected, not inferred from an older run.

## Accessibility acceptance

Every user-facing workflow must be operable from keyboard/NVDA without depending on visual-only state.

Required properties include:
- real semantic controls and deterministic focus;
- concise accessible names;
- no implementation essays attached through `aria-describedby` to routine controls;
- no background live-region spam;
- no raw Python/JS exception strings, filesystem paths or engine/provider internals in user speech;
- ordinary selection/copy behavior remains available;
- one canonical 64-square board identity;
- meaningful state changes produce bounded, useful announcements rather than repeated noise.

Automation can prove contracts and Windows UIA facts but cannot set `NVDA_VERIFIED=YES`. Only Oleksii's exact-candidate human test may do that.

## Stage1 machine gate

Before offering a fresh human Windows candidate, the complete automated chain must be green on one exact Product SHA, including:
- source lineage and diff hygiene;
- compile/static JS checks;
- full Product unittest and pytest suites;
- complete diagnostic;
- official Stockfish production smoke;
- real Windows/Nuitka packaged build;
- packaged WebView2 startup;
- original Move Edit/UIA identity and real native keyboard proof;
- 64 unique board squares/focus continuity;
- actual sound assets/runtime path;
- engine lifecycle/isolation;
- native Windows menu structural/keyboard evidence available to automation;
- source-leak/license/notices checks;
- release manifest and SHA256 checksums;
- exact clean ZIP layout.

The exact fresh package must state `nvda_verified=false` before human test.

## Product-state invariants

- Invalid move/FEN/editor/import operations are atomic.
- Review navigation does not mutate live canonical state.
- Undo/redo/variations preserve exact history identity and do not silently truncate unrelated branches.
- Engine results are stale/race checked before commit.
- Analysis user projection never leaks raw UCI/provider paths; user-facing chess lines are legal and accessible.
- Sound failure cannot corrupt chess state or block other event sinks.
- Settings/keymap imports are versioned, validated and conflict-safe.
- Native menu and keyboard actions converge on central application actions where stable action IDs exist.

## Data roadmap gates

PGN/GameTree:
- comments/NAG/nested RAV/header/result structure round-trips without silent loss;
- malformed/unsupported input is explicit;
- save is atomic and supports lost-update protection.

ACSDB:
- versioned migrations are explicit and atomic;
- newer schema is rejected without rewriting;
- queries are parameterized and paging stable;
- provenance/import reports survive round-trip.

ChessBase:
- component families are recognized without claiming unsupported decode;
- provenance/integrity checks are explicit;
- unsupported or partial capability is reported, never guessed.

Books/Training:
- essential meaning is available in linear semantic text and structured chess state;
- diagrams do not require vision;
- variation/exercise return points are deterministic.

Teacher/Classroom:
- pointer/highlight/arrow/hover do not mutate chess Position;
- blind teacher can perform the complete workflow from keyboard/NVDA;
- sighted student visual state is a projection of canonical state, never a second chess source of truth;
- student interactions enter the chess core only through explicit permitted command modes.

## Security and recovery gates

- no secrets committed;
- no unvalidated shell/engine command injection;
- no arbitrary path escape from package/import roots;
- failures preserve user data and expose recovery paths;
- every risky schema/import/refactor operation has a persistent pre-change checkpoint.

## Evidence quality

Do not use test quantity as a substitute for coverage. A green test written to mirror the implementation is weak evidence. Prefer independent observable contracts, adversarial cases, fresh-process tests, package-level checks and exact-state assertions.

Do not weaken, skip or delete a failing gate solely to claim success. If a gate is wrong, demonstrate why, replace it with a stronger correct contract, and document the evidence.