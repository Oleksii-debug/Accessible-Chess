# DEV4 RUN STATE

RUN_ID: 20260822-0900-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Stage1 Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Manual5 integration remains `manual5/integration-20260821` @ `0fa442330bc2bb03636ff9297512da4c29e38684`; prior UI Semantic Gate `32532577650` and Stage1 Saturation `32532577641` remain SUCCESS evidence for that exact integration SHA.
- DEV5 reconciliation PR #66 remains OPEN/DRAFT at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`; DEV4 did not modify that owner lane.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New non-conflicting QA evidence commit: `7aaf647b13f98fb45cbdb4ba900b497ff1bcc20b` — `test(qa): gate ChessBase companion probe false-green`.
- QA PR #67 remains OPEN/DRAFT/MERGEABLE.
- Exact pre-handoff QA head Actions remain unobserved; absence is classified INCONCLUSIVE CI observability, never GREEN.
- Requested `AGENTS.md` and `docs/codex/CURRENT_STATE.md` remain absent on the checked QA ref; operative control state is live GitHub plus `docs/automation/DEV4_*` and canonical Drive handoff.
- Windows strict WIP=1 remains untouched. `NVDA_VERIFIED=NO`.

## New PROVEN_PRODUCT_DEFECT — ChessBase companion probe false-green on directory I/O failure

`acs.chessbase_adapter._case_insensitive_directory_index()` catches every `OSError` from directory enumeration and returns `{}`. `probe_chessbase_source()` then treats that empty index exactly like a successful enumeration with no companions and emits `No classic CBH companion files were detected beside the header`.

A permission/I/O failure is not evidence that companions are absent. The current evidence path therefore collapses `UNOBSERVABLE` into `ABSENT`, creating false-green provenance and potentially misclassifying an inaccessible classic CBH database as merely incomplete.

Added strict QA gate `tests/test_dev4_chessbase_probe_observability.py`. It injects `PermissionError` at `Path.iterdir()` and requires the probe to avoid the ordinary no-companions claim and to surface an explicit unavailable/access/I/O indication. Product code is intentionally unchanged.

Classification: `PROVEN_PRODUCT_DEFECT` because the live evidence/reporting behavior directly contradicts fail-closed observability: an inspection failure is presented as successful negative evidence.

## Previously locked PROVEN_PRODUCT_DEFECT findings

1. External import/ChessBase symlink-reparse indirection follows filesystem targets instead of failing closed.
2. PGN import performs an unbounded full-text `handle.read()` after bounded hashing.
3. Serialized ChessBase probe/integrity/manifest DTOs expose absolute/local paths.
4. PGN `expected_sha256` optimistic overwrite has a TOCTOU lost-update window.
5. PGN `overwrite=False` can clobber a destination created after preflight.
6. PGN export path handling accepts filesystem indirection instead of failing closed; strict coverage includes direct-parent, deeper-ancestor and destination-file symlinks.
7. ChessBase CBH companion directory I/O failures are collapsed into ordinary no-companion evidence instead of explicit unavailable/error state.

## Other classifications / boundaries

- QA EVIDENCE: PGN export recovery guard preserves destination/temp cleanup across injected `os.replace`/`os.fsync` failures and checks POSIX private temp mode.
- QA EVIDENCE: Stockfish provider path-bearing failures are sanitized at the release API boundary before WebView/NVDA output.
- INCONCLUSIVE: exact QA-head CI until commit-associated checks are observed.
- INCONCLUSIVE: parent-directory durability across crash/power loss.
- INCONCLUSIVE: generic `SourceFingerprint.path`, `BatchInspectionItem.path/error` and PGN exception strings reaching actual UI/persisted surfaces beyond already-proven ChessBase DTO leakage.
- HUMAN_ONLY: exact fresh Windows native-menu/NVDA usability; `NVDA_VERIFIED=NO`.
- PROVEN_PRODUCT_INTEGRATION_RISK: preserve accepted DEV1/integration `web/stage1_board_actions.js` semantics during reconciliation.
- PROVEN_RELEASE_PIPELINE_BLOCKER: `nuitka-compilation-report.xml` may remain CI evidence only and must not ship in a user ZIP.
- No Product Ctrl+A/Ctrl+C defect is claimed.
- No force-push, DEV5/integration mutation, `tools/qa` or strict Windows workflow edit, frozen-release merge, Windows candidate creation, or DEV3 ACSDB performance takeover occurred.

## Next action

1. Re-read PR #67 exact head and Actions after handoff metadata commits.
2. Continue generic import resource-limit evidence: explicit source caps, huge/truncated content, encoding abuse, duplicate-source behavior, cancellation and recovery.
3. Extend ChessBase observability checks for component hashing/stat/open failures so inaccessible evidence is never reported as absent or healthy.
4. Trace generic import/provenance errors into real persisted/UI/report sinks; promote only direct exposure.
5. Continue engine/UCI privacy guards only at real user-facing boundaries.
6. Re-enter Stage1 package/security only through DEV5/Audit-authorized reconciliation.
