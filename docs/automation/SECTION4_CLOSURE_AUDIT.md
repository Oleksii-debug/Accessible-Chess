# Section 4 — ChessBase-family formats terminal closure audit

Canonical plan authority: **SECTION 4 — ChessBase-family formats: CBH / CBV / CBF / companions / safety**.
Accepted predecessor: Section 3 merge `ca543281040b9030d47abbbb244fb592ae63110d`.
Closure policy: Simplified Section Closure Protocol v3.

## 4.1 Accurate support matrix

The canonical matrix is `docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md`.

- CBH: supported only when the optional pinned external backend is configured.
- CBV: supported only when both bounded external backends are configured; unencrypted archive path only.
- classic companions CBG/CBP/CBT/CBA/CBC/CBS: component-only, never standalone imports.
- legacy CBF+CBI: BLOCKED pending lawful real semantic fixtures/oracle and a qualified decoder seam.
- 2CBH: BLOCKED; it is a multi-file database family and the complete companion topology is not evidence-qualified.
- CBONE: BLOCKED semantically; source topology is single-file.
- CBZ/2CBZ and other unqualified encrypted/new families remain BLOCKED unless separately evidence-qualified.
- Chess960/Fischer Random through current classic ChessBase import remains UNSUPPORTED by the standard-chess canonical core and must fail closed/loss-account rather than be reinterpreted.

Recognition, topology and integrity evidence never imply semantic decoder support.

## 4.2 No-overclaim / evidence boundary

The Product keeps unknown or proprietary semantics explicitly BLOCKED. The retained CBF/CBI evidence package records
`real_fixture_found=false` and `independent_semantic_oracle_found=false`. Per the Section plan, absence of a lawful
authentic proprietary fixture is an external evidence gap, not permission to invent support and not a global Product blocker.

This closure corrects one stale Product claim inherited by the predecessor: `.2cbh` was being labelled as a
single-file database and could receive a misleading single-file integrity snapshot. The repaired adapter reports
`multi_file_database_unqualified_topology`; the integrity layer refuses a whole-family snapshot until the complete
companion map is evidence-qualified. CBONE remains truthfully single-file without semantic support promotion.

## 4.3 Read-only source and canonical publication

`chessbase_adapter.py`, `chessbase_integrity.py`, `chessbase_decoder.py`, `cbv_extractor.py` and
`chessbase_library_import.py` keep proprietary source bytes read-only. Successful configured imports produce canonical
GameTree/ACSDB/PGN-side state; there is no ChessBase writeback authority.

## 4.4 Failure, cancellation, recovery and security

The retained regression surface covers source-family identity, symlink/reparse/path privacy, descriptor-bound integrity,
backend immutability, corrupt/invalid decoder output, CBV path safety, cancellation, passive report ingress, canonical
legality validation, and atomic Library publication. The new 2CBH topology tests additionally prove fail-closed integrity,
no guessed companion completion, CBONE integrity round-trip and mutation detection.

## 4.5 Real-world evidence

Historical repository evidence includes real pinned CBH/CBV backend/corpus qualification for the supported-when-configured
classic path. Unqualified proprietary families stay BLOCKED until lawful fixture/oracle evidence exists. This is an honest
capability closure, not a decoder-support expansion.

## Prior concrete gate evidence

PR #306 previously carried the same bounded 2CBH/CBONE correction. Its run `37518098670` did not disprove the topology
repair: the topology jobs stopped in a repository-wide `compileall tests` step on an unrelated Python static nesting error
before focused topology tests ran, and its retained-library job referenced a removed test module plus old-lineage observer
failures. This Section-4 successor is rebuilt on the accepted Section-3 predecessor and uses a focused closure gate that
does not convert unrelated stale test collection into Section-4 truth.

## Exact closure delta

Relative to `ca543281040b9030d47abbbb244fb592ae63110d`:
- `acs/chessbase_adapter.py`
- `acs/chessbase_integrity.py`
- `tests/test_v2_2cbh_cbone_topology.py`
- `docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md`
- `docs/automation/SECTION4_CLOSURE_AUDIT.md`
- `.github/workflows/section4-chessbase-formats-closure.yml`

No decoder, Library, PGN/GameTree, UI, packaging or unrelated Product implementation is rewritten.

`SECTION4_SUPPORT_OVERCLAIM=NO`
`SECTION4_2CBH_SEMANTICS=BLOCKED`
`SECTION4_CBF_CBI_SEMANTICS=BLOCKED`
`HUMAN_TESTED=NO`
`NVDA_VERIFIED=NO`
