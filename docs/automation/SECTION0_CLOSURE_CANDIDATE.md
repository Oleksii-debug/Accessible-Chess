# Section 0 — whole-contract closure candidate

Status: **PENDING_TERMINAL_CI — NOT DONE**

This file is durable convergence evidence for the numerically earliest live plan Section. It does not promote Section 0 to DONE until the exact convergence head passes its dedicated terminal qualification and the live parents are rechecked immediately before closure.

## Live authorities composed by this candidate

- source formats/history apex: #2326 @ `5854b528fbd3632cfa69553a70973123eaf14b54`;
- 0.1 / 0.2 / 0.4 authority-boundary lane: #2329, inherited by the ImportReport stack;
- 0.5 shared ImportReport lane: #2330 current owner, plus #2331 passive-record revalidation successor;
- 0.3 canonical capability matrix lane: #2328 @ `6f8ae8547dfe7c0f15ed124bc0f44a6c660c0056`.

The current convergence branch is history-preservingly reconverged on both live owner heads and the parallel convergence candidate:
- #2331 @ `c80772e40d783694d3931768e66d246236f61aad`;
- #2328 @ `6f8ae8547dfe7c0f15ed124bc0f44a6c660c0056`;
- previous convergence candidate `b1df7ad557d9adf0e1d73f173d05735f0ab8e050` remains in ancestry;
- parallel candidate #2333 @ `8a39f849950020e59f815b9315b2640dc394ca31` is also preserved in ancestry, including its conservative Markdown/DOCX/PDF/2CBZ capability corrections.

The convergence gate requires both current owner heads, the previous convergence candidate, and #2333 to remain ancestors while the effective delta against #2331 stays exactly five paths. The stale component capability workflow is intentionally absent; the whole-Section gate is the composed qualification authority. No force-push, parser rewrite, chess-rules fork, GameTree fork, Library fork, provenance fork or second report model is introduced.

## Section contract mapping

### 0.1 — one canonical authority

Executable contract: `tests/test_section0_format_authority_contract.py`.

Authorities:
- playable position / move / SAN / playable FEN: `acs.chesscore.Board` + `Move`;
- editable/interchange position: `acs.position_editor.PositionState`;
- EPD: `acs.epd` over the same PositionState;
- PGN structure: exact `acs.gametree` types;
- strict editable PGN persistence: `acs.pgn_roundtrip` over those exact types;
- Library publication: existing `acs.library_import_service`;
- semantic game identity: existing `acs.game_identity`;
- provenance remains outside semantic GameTree identity.

### 0.2 — format application boundaries

`docs/FORMAT_AUTHORITY_BOUNDARIES.md` fixes the dependency direction:

`untrusted format -> bounded adapter -> canonical PositionState/GameTree -> canonical validation -> publication`

and the reverse export direction through canonical serializers/atomic publication. Format adapters may own lexical/container grammar and limits, but not chess legality.

### 0.3 — honest capability matrix

Typed authority: `acs.format_capabilities.FORMAT_CAPABILITIES`.

Vocabulary is closed to:
- SUPPORTED
- PARTIAL
- UNSUPPORTED
- BLOCKED

The checked human projection is `docs/automation/CANONICAL_FORMAT_CAPABILITY_MATRIX.md`.

PARTIAL/BLOCKED states are intentional product truth. In particular, FEN full editor/corpus closure belongs to Section 1; keeping its edit/round-trip status PARTIAL does not block Section 0 as long as the matrix remains truthful.

### 0.4 — convergence

This candidate composes the active sibling lineages through a history-preserving convergence chain. The required current owner heads and reconciled candidate remain explicit ancestors; historical PRs remain evidence rather than alternate runtime authorities.

### 0.5 — malformed/partial input reporting

Canonical report authority remains `acs.import_contract.ImportReport`.

The current stack:
- requires exact passive ImportReport ingress;
- validates exact SourceFingerprint provenance scalars;
- validates ImportedRecord scalar types and identifiers;
- requires explicit loss/damage/warning evidence for non-FULL records;
- revalidates mutable report collections;
- revalidates exact ImportedRecord values before report observation/publication;
- rejects malformed adapter reports at shared ImportRegistry ingress;
- preserves source bytes and provenance verification;
- never treats a warning/recovery as permission to publish fabricated chess state.

## Qualification required before DONE

The dedicated whole-Section dual-OS gate must be terminal GREEN on the exact convergence head. It checks:
- required current owner/candidate ancestry;
- exact effective geometry;
- exact authority/report/capability blobs;
- Section 0.1–0.5 executable contracts;
- retained EPD/PGN/FEN authority, source-object, ChessBase capability/integrity, ACSDB and Version2 formats regressions;
- core chess selftest.

Queued, pending, cancelled, skipped or stale runs are **not PASS**.

Immediately before any DONE marker, refresh:
- canonical Section plan;
- live #2328/#2329/#2330/#2331 heads/states;
- exact convergence head and CI;
- current main/shipping authority.

HUMAN_TESTED=NO  
NVDA_VERIFIED=NO

Physical NVDA evidence is not a hard dependency for this data-contract Section, but these flags remain false because no human NVDA claim is being made.
