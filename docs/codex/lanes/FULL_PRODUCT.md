# Codex lane — Full Product Critical Path

Owner: Codex full-product agent.

Start branch: `codex/full-product-20260821`.

Mission: while Stage1 release work stays isolated, advance the canonical Windows product in dependency order using existing proven branches/code where possible: canonical core/contracts -> PGN/GameTree -> ACSDB/Library/Search -> ChessBase adapters -> Books/Training -> Teacher/Classroom -> courses/progress -> remote/shared lessons.

Do not merge future-stage code into frozen Stage1 integration/candidate. Inventory existing future branches before writing replacements. Preserve blind-first accessibility and one canonical chess state.

This lane should avoid editing files concurrently owned by the Stage1 release lane. If a shared-core change is necessary, checkpoint it separately and document the dependency rather than silently merging it into Stage1.

At every durable checkpoint append/update this file with:
- UTC timestamp;
- exact branch/SHA;
- subsystem/package completed;
- source branch/code reused or rejected and why;
- focused/full tests;
- known architectural risks/data-loss risks;
- unresolved blockers;
- next executable action.