# AUTO-CHESS DEV3 next work

Current terminal executable checkpoint: `7db59c1a3538af2497972848ba706ba5bb07b3ea` on `auto/dev3-batch-game-review-20260822`, draft PR #96.
Exact executable CI: run `32583322210`, job `97055819000` — SUCCESS.
Parent BookReader resource-bound package: PR #95 / `12763acb772e25524d58d58933a8f65b1f3434ea`, run `32580759442`, job `97049661061` — SUCCESS.

CURRENT CONTRACTS TO PRESERVE
- one shared canonical engine/application core; GameReviewService uses existing AnalysisService only;
- max 512 review positions; bounded stable identifiers/FEN/depth before engine work;
- one batch = one student/session/game/source revision, unique position IDs;
- cooperative cancellation before/after each blocking engine call and suppression of the result completed after cancellation;
- single-batch non-blocking busy policy prevents cross-batch generation interference;
- provider/cancel-provider failures do not leak private paths/provider detail and do not poison later service use;
- transient review DTO has no PV; StudentProgress persists review metadata only, never engine PV/score/UI state;
- BookReader/Search/ACSDB/Training/StudentProgress durable resource, atomicity and signed-64-bit scalar contracts from prior terminal packages remain unchanged.

DEPENDENCY-CORRECT NEXT ROUTE
1. Freshly re-read live DEV1/DEV2/DEV4/DEV5/Audit ownership and exact GitHub state before any Product mutation.
2. If the canonical StudentGame/Assignment actor + evaluation-perspective contract is terminal and unowned, implement derived mistake/blunder classification as analytics only, with stable linkage and explicit fixed perspective. Do NOT infer this from alternating raw UCI scores.
3. If that contract is still active/unstable, do not compete. Move to another unclaimed DEV3 backend P1 in Library/Search/performance, Books/Training persistence, engine recovery/cancellation/concurrency, or Teacher analysis policy.
4. Shared PGN/ChessBase/import defect repair remains DEV4-owned and must not be stolen.
5. Cross-lane integration remains DEV5-owned; PR #95/#96 are evidence/intake branches, not wholesale merge instructions.
6. Every substantial Product package requires focused + broad regressions + diagnostic + exact Actions evidence; official Stockfish should be used for real engine smoke where applicable.

KNOWN CROSS-LANE BLOCKER
Mistake/blunder classification cannot be implemented correctly on the present DEV3 base because an authoritative fixed actor/perspective + StudentGame/Assignment linkage contract is not terminal here. Raw UCI score perspective can alternate with side to move; naïve adjacent-score subtraction would create false classifications. Wait for the canonical contract rather than inventing a second model.

Release truth: Linux CI is backend evidence only. Fresh Windows candidate: NONE. `NVDA_VERIFIED=NO`.
