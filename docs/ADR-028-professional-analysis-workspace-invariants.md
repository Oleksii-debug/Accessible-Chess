# ADR-028: Professional engine-analysis workspace invariants

Status: accepted for the product analysis boundary.

## Context

Continuous Stockfish analysis already rejected results for an obsolete FEN, but
the WebView projected provider PV tokens directly.  A legal engine line could
therefore reach a user as raw UCI coordinates, while a syntactically valid but
illegal line was never checked against the analyzed position.  The product also
lacked an explicit target lock, bounded settings, stable PV selection,
non-destructive exploration, and an intentional path for adding an engine line
to game history.

Reconfiguring continuous analysis introduced a separate same-FEN race: the old
result could remain visible while a new depth or MultiPV revision was pending.

## Decision

1. The presentation boundary reconstructs every provider PV from the exact
   target FEN with the canonical chess board.  Only canonical SAN and the FEN
   after each legal ply cross into the WebView.  One illegal token rejects the
   provider result; raw UCI is never a user-facing fallback.
2. Provider exception text remains diagnostic-only.  The WebView receives the
   stable `engine_error` state and localized concise text, never an executable
   path or provider exception.
3. MultiPV is bounded to 1–10 and depth to 1–40.  Reconfiguration and restart
   clear the prior result before the replacement revision can publish, including
   when the FEN itself did not change.
4. Analysis follows the current review node by default.  Locking freezes both
   the target FEN and its exact history-node identity; a different displayed
   position does not make a matching locked result stale.
5. PV rows have one explicit selected index.  Previous/next selection, complete
   PV reading, evaluation, best move, restart, lock/follow, exploration, return,
   and insertion are canonical actions exposed by the same API and remappable
   action registry.
6. Exploration freezes one already validated PV and projects its positions
   without changing the canonical board or history cursor.  Canonical mutation
   is blocked until Return restores the exact source node.  Background refresh
   is non-live and does not rebuild focused PV controls.
7. Insert Move and Insert Line revalidate SAN and every stored FEN from the
   locked source, then add or reuse a non-active history branch.  The main line,
   live board, active child choices, and review cursor remain unchanged.
8. A canonical game/position reset releases an obsolete locked target and
   reanchors running analysis to the new root.  Starting an engine game is
   blocked during temporary PV exploration.

## Consequences

The default Stage 1 contract remains MultiPV 5 at depth 16, while advanced users
can select bounded values.  Analysis and play still share the production-owned
Stockfish runtime and this change creates no second provider process.  History
now has a general non-activating, idempotent branch-insertion primitive suitable
for later GameTree persistence adapters.

Automated tests prove legality conversion, same-FEN invalidation, exact target
locking, temporary exploration, mutation blocking, source restoration,
idempotent branch insertion, concise error projection, structured semantic HTML,
and central keyboard/native-menu wiring.  They do not claim human NVDA
verification, alter the separately owned QA harness, replace the locked release
candidate, or close the open Stage 1 human acceptance gate.
