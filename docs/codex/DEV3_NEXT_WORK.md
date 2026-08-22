# DEV3 NEXT WORK

Continue the current DEV3 shadow-column benchmark package first; do not start a new Product wave while its exact CI evidence is unresolved.

Current evidence branch: `auto/dev3-unicode-search-shadow-benchmark-20260822`, executable benchmark head `e930a53c3617da9f9676bc44a55a565bff630875`, PR #109. Validation PR #110 uses benchmark/CI base `0da0187f07e11e489d353e866ab679b3320e3a87` and marker head `5f98ee96214641e65417fee14e2f0d4010a1df34`.

Immediate next action:
1. obtain exact observable Actions evidence for the validation head/merge ref;
2. if GREEN, capture per-case candidate query plans, temp-sort flags and baseline-vs-shadow medians from the 100k run;
3. decide whether materialized folded columns provide enough gain to justify a separate schema-v4 Product migration, especially distinguishing substring filters (leading wildcard, scan likely retained) from ECO prefix search (index-eligible candidate);
4. before any Product migration, require migration/reopen/backward-compatibility coverage and preserve NFKC+casefold correctness, literal `%`/`_`/backslash semantics, 256-character bounds, keyset paging, source provenance and strict scalar validation;
5. if the benchmark is RED, fix benchmark/CI defects without weakening exact result-id equivalence.

Do not edit DEV2 canonical GameTree/domain/remote-session semantics, DEV4 PGN/ChessBase/import security, DEV1 UI/WebView models, DEV5 integration/promotion or frozen Stage1 release lineage. Do not create a second canonical chess/application state model.

The inherited Product package remains PR #105 / validated Product head `9c8a342e7dd98fee52c9776c0cb6a9b970d49296`, `READY_FOR_INTEGRATION=YES`. This benchmark wave itself remains `READY_FOR_INTEGRATION=NO` because it intentionally changes no Product behavior.

After this package is terminal, next eligible DEV3 priorities remain Books/Training persistence/recovery gaps, backend-only engine analysis/cancellation policy gaps, and only then mistake/blunder analytics after authoritative actor identity plus fixed evaluation perspective become terminal.

FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
