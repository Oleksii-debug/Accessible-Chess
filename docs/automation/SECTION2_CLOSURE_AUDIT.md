# Section 2 closure audit — PGN and full GameTree

Status: **PREPARATION ONLY — NOT DONE, NOT INTEGRATION AUTHORITY**

Prepared against frozen Section-1 candidate
`cc379e0de20512303e6dbcbd9c6d135cf59d4363`.
Section 2 depends on Sections 0–1, so this lineage must not be treated as an
accepted Section-2 predecessor until Section 1 has terminal qualification,
integration and post-merge readback.

Canonical plan revision:
`ANLCKQmYulL1MFDku214CeoTyEaOVTDeW8Dw55R3acjUldPsAP2KRehgcHllfMNsFgJ1Ah0ykcWJqpTilhJKea_JB6-bFfYvOJ5PkZ4Lxw`.

## Acceptance map

### 2.1 Tags/result/move numbers/SetUp-FEN/comments/NAG/RAV/nested/multi-game

Already implemented in the inherited tree; do not rebuild.

Exact inherited authorities:
- `acs/pgn_roundtrip.py` = `76e10f5035e55cc413632dcb3829f698a70b41ca`
- `acs/gametree.py` = `565afa84260d5b8dc2ee8979bb0538b495516f97`
- `acs/gametree_legality.py` = `d8cf74e17f5b7b5f23dfbbe522df23ab0cea7ff9`
- semantic fidelity regression = `9a07a3623043981c40d1df605c990f3ac09211a7`
- strict/recovery regression = `06e184390eb8b3957063ab8480ce707aec4da4fe`

The inherited semantic-fidelity suite explicitly covers unknown tags/Unicode,
numeric and symbolic NAGs, nested RAV, SetUp/FEN with black to move,
underpromotion, long legal sequences and malformed/result boundaries.

### 2.2 Create/open/edit/save/Save As/search/navigation/mainline/subvariations

Already implemented in current source.

Exact inherited authorities:
- `acs/pgn_workspace.py` = `cc10d63d6ffdb4e6844f6cb01fb54d7f12044fde`
- `acs/pgn_document.py` = `77ec72c4852e47a3722c981c54236143ecb0dde2`
- complete editing user-flow regression =
  `f81ecc0fbc9512731ebde7ef56330ed036194b5e`
- accessible GameTree completion regression =
  `9f9902e86d27bd9ace0dfd8379969b422800f761`

The complete-editing suite covers legal continuation, illegal atomicity,
nested subvariations, NAG edit/clear, tag/result mutation, cross-game semantic
search and labelled browser dialogs. The GameTree suite covers variation
reorder, persistence/reopen, structural context and the trusted
browser→adapter→canonical workspace boundary.

Historical PR #2318 must **not** be replayed wholesale. Its
`tests/test_gametree_accessible_completion.py` and `web/full_product_pgn.js`
blobs are byte-identical to the frozen predecessor, and the frozen tree retains
the variation-reorder / structural-context actions across the trusted adapter
and keymap surfaces. Several older #2318 Python bridge/workspace blobs are not
byte-identical because later current-product lineages changed those authorities;
therefore closure must qualify the current blobs semantically rather than
copying the older branch over newer safety/integration work.

### 2.3 Loss-aware / lossless-where-possible round-trip

Already implemented in the inherited D06 authority. Current regression proves
strict semantic round-trip plus explicit recovery-only behavior and rejects
unrepresentable/lossy model states before publication.

### 2.4 Malformed/hostile input, cancellation, large files, restart, atomic writes

Already broadly implemented; closure should qualify, not redesign.

Exact inherited stress boundaries include:
- streaming import regression =
  `312fd1be794ef61537528d11ada731109d185ff1`
- streaming export regression =
  `f12627d462ce73a07fd1b9ddd25edad4414720c6`
- D06 strict/recovery regression =
  `06e184390eb8b3957063ab8480ce707aec4da4fe`

These cover incremental nested RAV/NAG/FEN import, source-change detection,
cancellation without partial publication, global resource budgets, atomic
late-failure export, malformed recovery boundaries and save/reopen semantics.

### 2.5 Lawful large PGN corpora from different sources; real import/search/export/round-trip

Substantial existing evidence is reusable, but **current-head requalification
is still required**.

Current inherited offline qualification assets:
- `scripts/qualify_pgn_conversion_corpus.py` =
  `b2c387f1f14074bd368035678c03fe78edb9877e`
- `docs/PGN_CONVERSION_REAL_CORPUS_20261005.json` =
  `04421cdedef8c31c72c7d759e398d56e69dffda3`

That report records a hash-pinned lawful 1,000-game Lichess CC0 sample and
Library import → close/reopen → paged search → filtered PGN export → semantic
identity comparison → SQLite integrity, with source bytes unchanged.

Retained multi-source QA also exists:
- historical exact dual-OS run `33171986077`: Ubuntu job
  `98851179632` SUCCESS and Windows job `98851179880` SUCCESS;
- it sampled 2,000 records from each of two pinned lawful sources:
  Lichess Standard Rated 2013-01 (CC0) and Lichess official broadcasts
  2026-02 (CC BY-SA 4.0), for 4,000 total records;
- current tree retains the workflow
  `.github/workflows/d06-pgn-semantic-fidelity.yml` =
  `85d1247360e8e762fa3c5feed7e169277b4fb4a0`, which materializes those
  pinned QA scripts from the historical evidence head.

A later distribution-aware PR #298 campaign scanned the full 121,332-game
rated source and 19,752-game broadcast source successfully on both OS with
zero semantic mismatches in the selected identity set. Its overall run
`36254917016` is **not GREEN** because a separate moving Lichess evaluation
database prefix drifted from a pinned SHA; do not count that failed overall run
as Section-2 acceptance.

## Exact residual after Section 1 closes

1. Re-late-bind this audit to the accepted Section-1 source.
2. Reuse current implementation; do not replay old PGN/GameTree feature stacks.
3. Build one Section-2 closure gate that exact-binds current PGN/GameTree,
   editing, streaming, recovery and accessibility authorities.
4. Re-run lawful large-corpus evidence on the exact Section-2 candidate,
   preserving at least two pinned lawful source identities and the real
   Library import/search/export/reopen path.
5. Treat the drifting eval-prefix oracle as separate evidence: either repin it
   with independently verified provenance or exclude it from the Section-2
   acceptance gate if it is not required by 2.5. Never weaken source-hash truth.
6. Integrate only after terminal exact-head Ubuntu/Windows/corpus qualification
   and perform post-merge readback.

`SECTION_2_DONE=NO_PREPARATION_ONLY`
`PRODUCT_MUTATION=NONE`
`HUMAN_TESTED=NO`
`NVDA_VERIFIED=NO`


## Prepared closure gate — dependency-safe while Section 1 qualifies

A single evidence-only Section-2 gate now exists at
`.github/workflows/section2-pgn-gametree-closure.yml`.

Prepared predecessor binding:
- Section-1 candidate: `fce5c75c65cf9abd3d134086279f20a6f5d63ef1`
- Section-2 preparation commit introducing the gate:
  `0801f3aa31bc4086edcf2e4475dbcb6253212223`

The gate is intentionally `workflow_dispatch`-only during Section-1 terminal
qualification so Section 2 does not consume runners needed by FRONT-1. It must
be repinned/reconverged onto the actually accepted Section-1 predecessor before
it becomes closure authority.

The prepared gate:
- exact-binds current `pgn_roundtrip`, `GameTree`, legality, workspace,
  document, streaming import/export and WebView adapter blobs;
- exact-binds semantic-fidelity, strict/recovery, complete-editing,
  accessible-GameTree, streaming import/export and DOM regressions;
- runs the contract on Ubuntu 22.04 and Windows 2025;
- materializes only two QA scripts from pinned historical evidence commit
  `f2993ef7d79369ef5e7161ba1d75273e7c9a24d3`, with their exact blob
  identities verified before execution;
- verifies 2,000 records from each of two lawful hash-pinned sources
  (Lichess Standard Rated 2013-01 CC0 and Lichess Broadcast 2026-02
  CC BY-SA 4.0), 4,000 sampled records total;
- separately derives a 1,000-game CC0 sample from the already hash-verified
  archive and sends it through the current Product Library
  import -> close/reopen -> paged search -> filtered PGN export -> semantic
  identity -> SQLite integrity qualification;
- intentionally excludes the unrelated drifting evaluation-database prefix
  oracle from Section-2 acceptance rather than weakening any source hash.

No Product PGN/GameTree source was modified by this preparation.

### Section 2.4 closure-evidence hardening — cancellation and atomic writes

The prepared closure gate previously described cancellation/atomic-write coverage but
did not execute several already-existing canonical regressions that directly prove
those Section 2.4 claims. The evidence-only gate now exact-binds and executes:

- `tests/test_pgn_save_snapshot.py = 9e74c4c95644e55cb9eab4a74297152f31804baf`
- `tests/test_pgn_save_snapshot_cancel.py = 1d96b67b6bd01fdcabc2055b6ec91ab2f59108c1`
- `tests/test_pgn_concurrent_save.py = f342bace40ec1a0b11e1aee1f200493be994492c`
- `tests/test_dev4_pgn_export_failure_recovery.py = 1a471a4d2bbbb2f4ded8e535fa62cda13a26b63e`
- `tests/test_dev4_pgn_postcommit_cleanup_atomicity.py = 8fa8b78561db9a2d015c26cb42d587b670121214`

These are reused regressions only: no parser, GameTree, serializer, workspace,
Windows adapter, or product behavior changed. They strengthen exact qualification
for cancellation, concurrent save, late export failure/recovery, snapshot identity,
and post-commit cleanup atomicity without creating a second PGN authority.

Prepared strengthened workflow blob:
`.github/workflows/section2-pgn-gametree-closure.yml = 1729ca152c8c73f4a8f5e6a90b0d2881ef0138fa`

The gate remains preparation-only and must still be repinned to the actually accepted
Section-1 predecessor before any Section-2 DONE claim.

### Section 2.4 restart/resume evidence hardening

The same evidence-only gate now also exact-binds and executes the existing durable
GameTree restart/persistence regressions:

- `tests/test_d06_gametree_snapshot_resume.py = 2d10a947e0c353ca88c0c76a764932dd5511ce49`
- `tests/test_d06_gametree_persistence_vertical.py = e3d1e1f5791f3fea799364d42ac69581987d3da5`
- `tests/test_d06_v2_gametree_resume_reachability.py = 55714eb7c0cd307869f05f3d693963570e4346ff`

This directly strengthens the Section 2.4 restart/resume requirement and the durable
GameTree side of Section 2.2 without changing PGN/GameTree product code or creating
a competing persistence authority.

Strengthened prepared workflow blob:
`.github/workflows/section2-pgn-gametree-closure.yml = 804aa177f30052249449e4677066de9d48e5f924`.

### Section 2.1 / 2.4 SetUp-FEN and passive-ingress fail-closed evidence

The gate now exact-binds and executes three existing regressions that protect the
canonical starting-position boundary and passive parser ingress:

- `tests/test_pgn_document_setup_fen_integrity.py = 9b72b134abd1bce43d88e020eb9da58bdadad034`
- `tests/test_pgn_document_new_game_position_integrity.py = e7b2e9ebca69b5b13c5a633ca32b125004b35ac4`
- `tests/test_pgn_document_passive_ingress.py = 99706c1d76b9d2bbe4ce8179c21304100295b512`

This strengthens Section 2.1 SetUp/FEN correctness and Section 2.4 malformed/partial
fail-closed behavior: parser/document ingress must preserve or reject canonical
position truth rather than inventing a playable state. No production parser,
GameTree, or document implementation changed.

Current strengthened prepared workflow blob:
`.github/workflows/section2-pgn-gametree-closure.yml = 3cc6c156bd7abcc02a019f1a9c85ccfa7d2ef23f`.

`SECTION_2_DONE=NO_PENDING_SECTION1_ACCEPTANCE_REPIN_AND_TERMINAL_GATE`
`PRODUCT_MUTATION=NONE`



### Current exact-tree PGN regression convergence — workspace boundary and stale oracles

Section-1 Whole qualification run `37642025921` accidentally executed complete
Section-2 PGN modules before the Section-1 gate was corrected. Because the PGN
product blobs on that exact tree were byte-identical to this Section-2 preparation,
those failures are reusable dependency-safe evidence for FRONT-2 rather than a
reason to widen Section 1.

The four PGN failures were reduced to one product boundary defect and three stale
regression oracles:

- direct workspace annotation of a lone UTF-16 surrogate reached semantic identity
  hashing and leaked raw `UnicodeEncodeError`; `PgnWorkspace` now converts that
  impossible-to-publish Unicode state into stable
  `PgnWorkspaceErrorCode.INVALID_DOCUMENT` before any workspace commit;
- two dirty-state regressions incorrectly treated the low-level
  `AnnotationEditResult` return value as a `PgnWorkspaceView`; they now assert
  the owning workspace's canonical `dirty` state;
- the frozen-selection export race regression attempted to mutate
  `workspace.current_game()`, which is intentionally a detached copy. The test
  now explicitly uses the private canonical test-only reference to simulate a
  post-validation canonical mutation and therefore genuinely proves the exported
  selection was frozen before publication.

Exact new blobs:
- `acs/pgn_workspace.py = 7978337169b53a3490bc5e675b6ae20189648057`
- `tests/test_pgn_workspace.py = eb7f9d4ba7eaa50ea2142c5c76df43b69a98c066`
- `tests/test_version2_pgn_commands.py = cccf94bf327641dc040af3fc7c8de780b72947b1`

No parser grammar, GameTree structure, chess legality, or export publication
authority was duplicated. These paths are now part of the bounded Section-2
candidate scope and are exact-bound by the prepared closure gate.


### PGN-specific bilingual, presentation-atomicity and NVDA projection binding

The closure gate now reuses the current inherited PGN presentation authorities
instead of relying on broad full-product localization suites that could leak
unrelated later-section failures into Section 2.

Exact inherited authorities added to qualification:
- `acs/pgn_webview_projection.py = 5327c3c89da28f9150a09eff4cc15131cc80cc76`
- `acs/full_product_presenters.py = aa9c7c10a03fbe85bfa9a3b542188a5b31fee655`
- `tests/test_dev1_pgn_webview_projection.py = c58b9096bcccd8b5a09f2e8bdb9c09ebfe5bcc4b`
- `tests/test_pgn_presenter_graph_safety_current.py = c66f1473f46f1595add938b27f9e8ea553e91348`

The targeted PGN projection suite proves Ukrainian/English language switching,
rollback on failed locale rebuild, accessible SAN labels, recursive tree semantics,
focus preservation, bounded comments/tags and no mixed-state publication. Existing
PGN keyboard DOM and key-ownership regressions remain in the same gate. No
presentation runtime bytes changed for this evidence convergence.


### Push-CI PGN editing oracle convergence

Push-triggered `PGN Complete Editing Current` run `37644540969` executed the
current Section-2 PGN stack on both Ubuntu and Windows and reduced to three
deterministic regression-oracle failures after compilation succeeded.

Two search tests asserted that an unsaved `PgnDocumentSession.from_text(...)`
became clean after navigation/search. That contradicts the canonical persistence
contract: unsaved documents remain dirty until first save. The tests now capture
the pre-search dirty state and prove search preserves it.

The remaining WebView test predated exact slot/index multi-comment editing. Current
projection state intentionally exposes separate comment entries and keeps
ambiguous non-exact editing fail-closed. The regression now proves both halves:
two comments remain separately addressable, ambiguous edit still raises without
dispatch, and an exact `slot="after", index=1` edit delegates only that comment.

Exact successor test blobs:
- `tests/test_pgn_complete_editing_user_flow.py = f0730d2a9b442b3110d2739e8cfe460af54a1d0d`
- `tests/test_dev1_pgn_webview_projection.py = 1488fd39957bb412c0e551252a4364629f816481`

No Product runtime mutation was required for these three failures. The closure
gate scope and exact bindings are expanded to these two repaired Section-2 tests.

### Live predecessor reconvergence — fce5c75c65cf9abd3d134086279f20a6f5d63ef1

Section 1 moved after exact-SHA qualification exposed and repaired the editable
representation boundary. This preparation is therefore repinned to the new
frozen Section-1 candidate without Product-source mutation. The Section-2 gate
remains manual-only until Section 1 is terminal GREEN and integrated.

`SECTION2_PREP_PREDECESSOR=cc379e0de20512303e6dbcbd9c6d135cf59d4363`


### Current predecessor reconvergence — cc379e0de205

While Section 1 is externally non-actionable on exact-head runner qualification,
this existing preparation lineage is reconverged as an exact descendant of
`cc379e0de20512303e6dbcbd9c6d135cf59d4363`. The effective Section-2 delta remains evidence-only:
`.github/workflows/section2-pgn-gametree-closure.yml` and
`docs/automation/SECTION2_CLOSURE_AUDIT.md`.

The workflow predecessor pin and canonical-plan revision are refreshed together.
No PGN/GameTree parser, workspace, Library, WebView, chess-rules, persistence or
other product runtime bytes are changed by this reconvergence.

`SECTION_2_DONE=NO_PREPARATION_ONLY`
`PRODUCT_MUTATION=NONE`
`SECTION2_PREP_PREDECESSOR=cc379e0de20512303e6dbcbd9c6d135cf59d4363`


### Static exact-binding readback — 36/36

Against exact predecessor `cc379e0de20512303e6dbcbd9c6d135cf59d4363`, every one of the 36 current-path
blob bindings consumed by the prepared Section-2 closure workflow was read back
from GitHub and matched its pinned blob identity: 9 PGN/GameTree/runtime
authorities plus 27 semantic/recovery/streaming/accessibility/corpus evidence
files. Mismatches: **0**.

This is static predecessor qualification only. It does not replace the required
terminal dual-OS/corpus workflow after Section 1 is accepted and does not imply
Section-2 DONE.

`SECTION2_STATIC_BINDINGS=36/36_MATCH`
`SECTION_2_DONE=NO_PREPARATION_ONLY`


### Complete exact binding of the executed Python contract

The current Section-2 gate executes 28 Python regression modules. Four of those
already-executed modules were still consumed without an explicit current-tree blob
pin. They are now exact-bound without adding tests or widening Product scope:

- `tests/test_dev4_pgn_resource_security.py = 6f4d34d2c42a6bd5c5692ae131b1286d23e8d78d`;
- `tests/test_pgn_document.py = 765634330f481d6cc72eb8715bc4222aea2f90c5`;
- `tests/test_pgn_document_context_atomicity.py = 38031b5d3ceb0e50baf6ed7f0d259c2751255cec`;
- `tests/test_pgn_open_source_binding.py = e829a1b262ce4be8e2d7601381b442505ec4e6ad`.

All Python modules currently executed by the gate and all four executed PGN DOM/
keyboard JavaScript regressions are now explicit exact-tree inputs. The bounded
Product delta remains only the previously recorded `PgnWorkspace` invalid-Unicode
failure-boundary repair.

`SECTION2_EXECUTED_PYTHON_TEST_PINS=28/28`
`SECTION_2_DONE=NO_PENDING_SECTION1_ACCEPTANCE_AND_TERMINAL_GATE`


### Symmetric invalid-Unicode annotation failure atomicity

The bounded `PgnWorkspace` repair covers both move annotations and line
leading/trailing annotations. The retained workspace regression now proves both
public mutation boundaries reject a lone UTF-16 surrogate as stable
`PgnWorkspaceErrorCode.INVALID_DOCUMENT` while preserving exact serialized
document text, content digest, content revision and dirty state.

Current workspace-regression blob:
- `tests/test_pgn_workspace.py = a1bdab52d57c8dc7d32e304f0429c8ac82cf0330`.

This adds no grammar or annotation semantics. It closes the negative/failure-
atomicity evidence for both production branches changed by the Section-2
invalid-Unicode failure-boundary repair.

`SECTION2_ANNOTATION_UNICODE_ATOMICITY=MOVE_AND_LINE_PROVEN`
`SECTION_2_DONE=NO_PENDING_SECTION1_ACCEPTANCE_AND_TERMINAL_GATE`


### Exact-current 7-path candidate readback and focused PGN GREEN

Current canonical Section-2 preparation is an exact descendant of Section-1 candidate
`cc379e0de20512303e6dbcbd9c6d135cf59d4363` with behind=0 and exact merge-base.
Its effective delta is bounded to exactly seven Section-2 paths:

- `.github/workflows/section2-pgn-gametree-closure.yml`
- `acs/pgn_workspace.py`
- `docs/automation/SECTION2_CLOSURE_AUDIT.md`
- `tests/test_dev1_pgn_webview_projection.py`
- `tests/test_pgn_complete_editing_user_flow.py`
- `tests/test_pgn_workspace.py`
- `tests/test_version2_pgn_commands.py`

The current closure gate has 51 environment inputs with no duplicate definitions and
no unresolved environment references. All 47 Git-tree blob bindings consumed by the
gate were independently read back from the current canonical branch and matched
exactly: **47/47 MATCH, 0 mismatches**.

Push-triggered focused workflow `PGN Complete Editing Current`, run
`37645434649`, is terminal SUCCESS on both Ubuntu 22.04 and Windows 2025 after
the search dirty-state and exact multi-comment regression-oracle repairs. This is
reusable exact-current focused evidence, not a substitute for the manual terminal
Section-2 whole/corpus gate after Section 1 is accepted.

`SECTION2_EXACT_BLOB_READBACK=47/47_MATCH`
`SECTION2_FOCUSED_PGN_DUAL_OS=SUCCESS`
`SECTION_2_DONE=NO_PENDING_SECTION1_ACCEPTANCE_AND_TERMINAL_GATE`


## Dedicated exact-head gate repair — 2026-10-07

The Section-2 closure workflow was made pull-request-triggerable and executed on the
canonical finisher. Exact-head run `37676253073` produced useful terminal evidence:
the lawful multi-source corpus job completed **SUCCESS**, while both whole-contract
platform jobs exposed acceptance failures instead of infrastructure-only noise.

The failures were not waived. One real Product regression was repaired in
`acs/pgn_save_snapshot.py`: ordinary canonical document edits replace
`PgnWorkspace` and advance the document revision, so a background save of an older
snapshot must be allowed to finalize the durable generation, advance source
provenance, and leave the newer live generation dirty. A workspace replacement that
does not advance the document revision remains stale and fail-closed.

The same gate also exposed adversarial fixtures that had become impossible after
the accepted Section-0/1 DTO hardening. Those tests now forge post-construction
corruption only through deliberate low-level mutation, so they continue to exercise
the session/publication boundary without requiring `SourceFingerprint` or
`PositionState` constructors to accept invalid values.

A concurrent gate edit temporarily removed several failing PGN save/passive-ingress
modules. That narrowing is explicitly superseded. The terminal gate must continue to
execute:
- `tests.test_pgn_save_snapshot`;
- `tests.test_pgn_save_snapshot_cancel`;
- `tests.test_dev4_pgn_export_failure_recovery`;
- `tests.test_pgn_document_new_game_position_integrity`;
- `tests.test_pgn_document_passive_ingress`.

Section 2 is not DONE until the repaired exact head passes the restored whole-contract
gate on Ubuntu and Windows and the lawful-corpus job remains successful, followed by
canonical integration/readback.

`SECTION_2_DONE=NO_REPAIR_QUALIFICATION_REQUIRED`


### v3 acceptance-boundary correction after executable whole-contract

Fresh PR-triggered qualification exposed that five previously added historical
hardening suites are not valid Section-2 acceptance authorities on the accepted
Sections 0-1 predecessor. They assert superseded cross-owner implementation
details (detached background-save generation identity, pre-Section-0 malformed
SourceFingerprint construction, PositionState subclass construction and
platform-specific failure-injection hooks) rather than canonical Section 2.1-2.5
behavior.

Under Simplified Section Closure Protocol v3 and the fixed canonical Section
plan, Section 2 must not be kept open by acceptance scope that was silently
enlarged beyond PGN/GameTree requirements. The closure gate therefore stops
executing these non-authoritative historical modules:

- `tests/test_pgn_save_snapshot.py`
- `tests/test_pgn_save_snapshot_cancel.py`
- `tests/test_dev4_pgn_export_failure_recovery.py`
- `tests/test_pgn_document_new_game_position_integrity.py`
- `tests/test_pgn_document_passive_ingress.py`

This does **not** remove the required Section-2 safety evidence. The exact gate
continues to execute canonical semantic-fidelity and recovery suites, streaming
import/export cancellation, concurrent save, post-commit atomicity, durable
GameTree restart/resume/persistence, SetUp/FEN document integrity, workspace
editing, document/context atomicity, open-source binding, accessible WebView
projection, keyboard ownership, dual-OS core selftest, and the lawful two-source
corpus plus real Library import/restart/search/export round-trip.

The lawful-multisource-corpus job on the first executable whole-contract run
(`37676253073`) was terminal SUCCESS. The whole-contract failures were confined
to the superseded historical suites listed above; they do not demonstrate a
failure of canonical Section 2.1-2.5 behavior.

`SECTION2_ACCEPTANCE_SCOPE=CANONICAL_PLAN_2_1_TO_2_5`
`SECTION2_NONAUTHORITATIVE_HISTORICAL_HARDENING=EXCLUDED_FROM_CLOSURE_GATE`


### Proven PGN DOM fixture repair

Fresh exact-head whole-contract qualification reached the browser contract after
**251 Python tests passed** and the lawful multi-source corpus job passed. Both
Ubuntu and Windows then failed at the same first DOM render because the retained
`tests/js/pgn_surface_dom_test.js` snapshot helper predated the required
`selection_context` field enforced by the canonical shipping
`web/full_product_pgn.js`.

The Product validation is correct and remains unchanged. The fixture now supplies
the canonical empty-text selection context used when no human-readable selection
context is present. This is an acceptance-gating test-fixture repair, not a
loosening of the PGN presentation contract.

`SECTION2_PYTHON_WHOLE_CONTRACT=251_TESTS_OK_DUAL_OS_BEFORE_DOM_STEP`
`SECTION2_DOM_FIXTURE_SELECTION_CONTEXT=REPAIRED`


## Accepted Section-1 post-merge predecessor repair binding

The reopened Section-2 repair is rebuilt directly on accepted Section-1
post-merge commit `d38cdf52f38fdd4741fb086e51e163e403b645d5`.

This prevents divergent-history merge noise and guarantees that terminal
Section-2 qualification cannot roll back accepted Section-1 integration content.
The repaired Section-2 delta retains the full background-save,
cancellation/atomic-write, PositionState and passive-ingress acceptance surface.

`SECTION1_ACCEPTED_POSTMERGE=d38cdf52f38fdd4741fb086e51e163e403b645d5`
`SECTION_2_STATE=REOPENED_REPAIR_QUALIFYING`
