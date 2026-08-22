# DEV4 SESSION HANDOFF

SESSION: 20260822-1100 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact branches and SHAs

- DEV4 Stage1 Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Manual5 integration: `manual5/integration-20260821` @ `0fa442330bc2bb03636ff9297512da4c29e38684`.
- DEV5 reconciliation draft PR #66: `manual5/dev5-reconcile-dev4-20260822` @ `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`, OPEN/DRAFT.
- DEV5 canonical RUN_ID `20260822-1100`: COMPLETE / TERMINAL / SAFE OVERLAP. DEV1 is still IN_PROGRESS, so no competing Product integration is permitted.
- DEV2 new isolated GREEN terminal Product head: `e705c70300c7307255fe2be3ae92f651f103c221`; validation-only PR #80 must not be merged wholesale.
- DEV3 latest verified executable Product head: `1ca5784b3ce00837b40888a26dd1e94d8ce754ed`.
- DEV4 QA evidence branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New QA evidence commit: `f6f1f01bade024f65ba0838aae95951c58199998` — `test(qa): require finite PGN source cap`.
- QA draft PR #67 remains OPEN/DRAFT/MERGEABLE. Metadata synchronization commits follow the evidence commit; canonical Drive handoff records the final exact live QA head.

## Live CI / evidence discipline

Manual5 integration exact SHA `0fa442330bc2bb03636ff9297512da4c29e38684` retains prior SUCCESS evidence:
- UI Semantic Gate `32532577650`.
- Stage1 Saturation Hardening `32532577641`.

Exact QA-head checks were absent before metadata synchronization. Absence is `INCONCLUSIVE`, never inferred GREEN. Existing integration/DEV5 GREEN does not validate QA-only external-format/security assertions.

## PGN resource defect evidence strengthened

The existing PGN resource-exhaustion defect now has two independent strict assertions in `tests/test_dev4_pgn_resource_security.py`:
1. the text reader must never issue an unbounded `read()` at the external-input boundary;
2. an absurd 8-EiB source fingerprint must be rejected before opening the payload, proving that some finite fail-closed source-size maximum exists.

The second assertion deliberately avoids choosing the production threshold. It establishes only the required security property: chunked reads/hashing do not constitute bounded import if an arbitrarily large payload is still accepted for parse/decode.

Product code is unchanged.

## Locked PROVEN_PRODUCT_DEFECT findings

1. Import/ChessBase symlink/reparse indirection is followed instead of failing closed.
2. PGN import lacks a bounded full-text/resource boundary: unbounded text read and no finite source-size rejection before payload open.
3. ChessBase serialized probe/integrity/manifest payloads expose absolute local paths.
4. PGN `expected_sha256` optimistic-concurrency commit race can overwrite newer content.
5. PGN `overwrite=False` commit race can clobber a destination created after preflight.
6. PGN export filesystem indirection is not fail-closed.
7. ChessBase CBH companion directory I/O failures are reported as ordinary no-companion evidence instead of explicit unavailable/error state.
8. Generic import batch preflight aborts on importer `RuntimeError` instead of recording the failed source and continuing later sources.

## Additional classifications

- QA EVIDENCE: PGN export failure-recovery assertions preserve existing destination/temp cleanup and POSIX temp privacy.
- QA EVIDENCE: Stockfish provider path-bearing exceptions are sanitized at the release API boundary.
- INCONCLUSIVE: exact QA-head CI until checks are observed.
- INCONCLUSIVE: PGN parent-directory durability across crash/power loss.
- INCONCLUSIVE: generic provenance/error strings reaching real UI/persistence/report sinks beyond already-proven ChessBase DTO leakage.
- HUMAN_ONLY: exact fresh Windows native-menu/NVDA usability. `NVDA_VERIFIED=NO`.

## Preserved findings / boundaries

- `docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md` remains evidence-only and does not infer proprietary decoder compatibility from suffix recognition.
- PROVEN_PRODUCT_INTEGRATION_RISK: preserve accepted DEV1/integration `web/stage1_board_actions.js` semantics.
- PROVEN_RELEASE_PIPELINE_BLOCKER: `nuitka-compilation-report.xml` must remain CI evidence only and stay out of user ZIPs.
- No Ctrl+A/Ctrl+C Product defect claim.
- Windows strict WIP=1 respected.
- No force-push, DEV5/integration mutation, `tools/qa` or strict Windows workflow edit, DEV3 ACSDB performance takeover, frozen-release merge or Windows candidate.

## Next action

Recheck live PR #67 exact head and Actions after metadata synchronization. Continue generic import resource-limit evidence beyond PGN and ChessBase component-open/stat/hash observability; continue direct path/error sink tracing only where user-facing/persisted evidence is concrete. Stay in SAFE OVERLAP while DEV1 remains IN_PROGRESS.
