# Section 0 — whole-contract closure candidate

Status: **PENDING_TERMINAL_CI — NOT DONE**

This file is durable convergence evidence for the numerically earliest live plan Section. It does not promote Section 0 to DONE until the exact successor head passes its dedicated terminal qualification and the live plan, base lineage, main, and CI are rechecked immediately before closure.

## Current convergence authority

This successor is stacked on the exact current Section 0 format-identity repair:

- PR #2341 `section0/import-report-format-identity-20261007-sol56` at `f087ee53a1b47faee1a517e52aea79fcacba65e0`;
- previous whole-Section candidate #2332 at `e9e0dceb21c1dc002b844c4e60563b3552f72744` remains in ancestry;
- source formats/history apex #2326 at `5854b528fbd3632cfa69553a70973123eaf14b54` remains inherited;
- 0.1 / 0.2 / 0.4 authority-boundary lineage #2329 remains inherited;
- 0.5 ImportReport lineage #2330/#2331 remains inherited through #2332;
- 0.3 capability matrix #2328 at `6f8ae8547dfe7c0f15ed124bc0f44a6c660c0056` remains inherited.

The successor itself changes only this closure evidence and the whole-Section qualification workflow. It introduces no parser, chess rules, Position, GameTree, Library, provenance, report, or capability authority.

## Section contract mapping

### 0.1 — one canonical authority

Executable contract: `tests/test_section0_format_authority_contract.py`.

Authorities remain:

- playable position / legal move / SAN / playable FEN: `acs.chesscore.Board` + `Move`;
- editable/interchange position: `acs.position_editor.PositionState`;
- EPD: `acs.epd` over the same PositionState;
- PGN structure: exact `acs.gametree` types;
- strict editable PGN persistence: `acs.pgn_roundtrip` over those exact types;
- Library publication: `acs.library_import_service`;
- semantic game identity: `acs.game_identity`;
- provenance stays outside semantic GameTree identity.

### 0.2 — format application boundaries

`docs/FORMAT_AUTHORITY_BOUNDARIES.md` fixes the dependency direction:

`untrusted format -> bounded adapter -> canonical PositionState/GameTree -> canonical validation -> publication`

and the reverse export direction through canonical serializers/atomic publication. Format adapters may own lexical/container grammar and resource limits, but not chess legality.

### 0.3 — honest capability matrix

Typed authority remains `acs.format_capabilities.FORMAT_CAPABILITIES`.

The vocabulary is closed to:

- SUPPORTED
- PARTIAL
- UNSUPPORTED
- BLOCKED

The checked human projection remains `docs/automation/CANONICAL_FORMAT_CAPABILITY_MATRIX.md`. PARTIAL/BLOCKED are valid product truth and are not silently promoted by this convergence.

### 0.4 — convergence

The current successor preserves the previously reconciled Section 0 ancestry and composes the live #2341 Section 0.5 repair without opening a competing implementation. Historical PRs remain evidence rather than alternate runtime authorities.

The exact successor gate requires:

- #2341 exact head `f087ee53a1b47faee1a517e52aea79fcacba65e0` as its PR base;
- #2332 exact whole-candidate head `e9e0dceb21c1dc002b844c4e60563b3552f72744` in ancestry;
- the inherited capability/import convergence ancestors from #2332;
- exactly two successor delta paths relative to #2341: this file and the whole-Section workflow.

If #2341 moves before qualification, the gate must fail closed and the successor must be reconverged rather than accepted on stale source.

### 0.5 — malformed/partial input reporting

Canonical report authority remains `acs.import_contract.ImportReport`.

The composed stack now requires all of the following:

- exact passive ImportReport ingress;
- exact SourceFingerprint provenance scalars;
- exact ImportedRecord scalar types and identifiers;
- explicit loss/damage/warning evidence for non-FULL records;
- revalidation of mutable report collections and exact record values before observation/publication;
- source-byte and provenance stability through ImportRegistry;
- registered importer format identity to be frozen at registration and matched exactly by returned reports;
- explicit replacement to update importer routing and registered format identity together;
- a format-identity rejection to remain source-preserving and recoverable by batch inspection, so later independent sources are not hidden;
- no warning/recovery path may authorize publication of fabricated chess state.

The #2341 repair changes only the shared import boundary; it does not claim proprietary decoder compatibility.

## Qualification required before DONE

The dedicated successor dual-OS gate must be terminal GREEN on the exact successor head. It checks:

- exact base/head topology and two-path successor geometry;
- #2332 and inherited Section 0 ancestry;
- exact authority/report/registry/capability blobs, including the current #2341 registry/test blobs;
- Section 0.1–0.5 executable contracts;
- the current format-identity regression suite;
- retained EPD/PGN/FEN authority and source-object regressions;
- ChessBase capability/integrity boundaries;
- ACSDB and Version2 formats regressions;
- core chess selftest.

Queued, pending, cancelled, skipped, stale, or absent CI is **not PASS**.

Immediately before any DONE marker, refresh:

- canonical ordered Section plan;
- current project plan where it supplies live acceptance context;
- main and `SEQUENTIAL_CLOSURE_STATE.md`;
- #2341 base head/state and any newer overlapping Section 0 owner;
- exact successor head and terminal CI.

`SECTION_0_DONE=NO_PENDING_TERMINAL_CI_AND_LIVE_REVALIDATION`

`HUMAN_TESTED=NO`

`NVDA_VERIFIED=NO`

Physical NVDA evidence is not a hard dependency for this data-contract Section, but no human/NVDA claim is made here.
