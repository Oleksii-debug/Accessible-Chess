# WordDeck development checkpoint

Last updated: 2026-08-18
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

Verified baseline remains Recall + independent Spelling + Adaptive Coach + Sentence Spelling. Do not claim real NVDA verification until the user tests an actual Windows build with NVDA.

## Lane 1 — Core app / Recall / Spelling / accessibility

**Advanced this run**
- Fixed an actual keyboard-accessibility defect: the default spelling-deck deletion shortcut was `Ctrl+Alt+Delete`, which Windows reserves as the Secure Attention Sequence and WordDeck cannot receive.
- Default is now `Ctrl+Shift+Delete`.
- Shared shortcut validation now fail-closes on exact `Ctrl+Alt+Delete`, in addition to existing Tab/Escape/Enter/Alt+F4/bare-navigation protections.
- Spelling regression tests now assert both the reachable default and rejection of the Windows-reserved combination.

**Remains**
- Continue keyboard-only/NVDA-readiness review, focus behavior, persistence recovery and error-path hardening without changing the verified Recall/Spelling semantics.

**Blocker**
- None. Real NVDA verification still requires a user test of an actual Windows build; this is not simulated or claimed.

**Exact next action**
- Audit dialog Tab order/focus restoration and menu/action parity for Recall, Spelling and Sentence windows, then add deterministic regression coverage where behavior can be tested without NVDA.

## Lane 2 — Sentence Coach / corpus / coverage / UI / performance

**Advanced this run**
- Downloaded and independently audited the successful attributed production SentencePack artifact from run `32065274247`, artifact id `9299729781`, digest `sha256:2019dc82e5aeb4b68b8f801159bba65c6510fb68bf3d4272b93d817bb3ce9d19`.
- Audit confirms 207,578 EN-UA sentences, 3,120 / 3,308 current Oxford IDs covered, 190,315 sentences with >=2 targets, 160,058 with >=3, and zero accepted rows missing per-side author attribution.
- Production baseline is now recorded in `QA/SENTENCEPACK_PRODUCTION_ARTIFACT_AUDIT_20260818.md`: gzip 19,906,951 bytes; SQLite 72,400,896 bytes; metadata/open 79 ms; full one-target coverage 33 ms / 3,120; two-target coverage 56 ms / 3,114; representative queries 179 ms and 13 ms; about 49.92 MB measured runtime working-set delta.
- The audit also preserves the old eager-GZIP cost (~644 MB working-set delta) as an explicit regression boundary: normal runtime must continue preferring SQLite.
- Current attributed workflow already computes fail-closed exact-occurrence files for all 188 gaps and partitions the 114 ordinary single-surface gaps into exact-present vs exact-absent before any morphology decision.

**Remains**
- Inspect a current attributed workflow artifact that contains `sentence-gap-exact-occurrence.tsv` and `sentence-gap-summary.json`; do not infer the exact-present/exact-absent split from the older production artifact.
- Resolve exact-present ordinary gaps as matcher/index QA first. Consider maintained development-time morphology only for measured exact-absent ordinary rows if the set is substantial enough to justify it.

**Blocker**
- None. The previously downloaded production artifact predates the new gap-summary outputs, so exact occurrence classification remains intentionally unclaimed rather than guessed.

**Exact next action**
- Inspect the next/current production gap-summary artifact, record exact-present/exact-absent counts, then isolate matcher/index defects from genuine corpus absence while preserving all numbered semantic senses.

## Lane 3 — Oxford 5000 + Oxford 3000 translation QA

**Advanced this run**
- Oxford 5000 additions `ox5000-add-0101` through `ox5000-add-0120` received a source-backed dictionary-entry second pass and are stored separately in `QA/oxford5000_additions_second_pass_0101_0120.tsv` as `verified`.
- The second pass deliberately widened several draft translations where the Oxford entry covers more than the initial gloss, including `appreciation`, `arena`, `arm`, `array`, `articulate`, `artwork` and `aside`.
- Added fail-closed `tools/validate_oxford5000_second_pass_slice.py`: exact ordered IDs, no duplicates, no source/POS/CEFR drift from the extraction batch, nonblank Ukrainian, `verified` only, and explicit OALD source-check evidence.
- The canonical Oxford 5000 additions ledger is **not** yet advanced past the already-verified first 100; the new 20-row slice stays staged until the surrounding batch is sufficiently reviewed for a coherent merge.

**Remains**
- Second-pass additions 0121-0200, especially polysemous/sense-sensitive rows such as `bass1`, `bat`, `bishop`, `blast` and `blow`.
- Further Oxford 5000 extraction after 0200.
- Oxford 3000 semantic QA remains 240 reviewed / 208 verified / 32 needs-second-pass / 3,068 awaiting first pass and must continue independently.

**Blocker**
- None. Semantic QA is intentionally fail-closed and does not block Core, Sentence or Audio work.

**Exact next action**
- Source-check additions 0121-0140 next, preserving POS/sense distinctions, then extend the staged validator slice rather than bulk-marking the entire 0101-0200 batch verified.

## Lane 4 — British Audio / AudioPack / pronunciation QA

**Advanced this run**
- Kept the existing Kokoro/Misaki British generation path; no new TTS, G2P, runtime Python, API or network dependency was introduced.
- Added standalone `tools/validate_targeted_audio_artifact.py` for downloaded targeted replacement artifacts. It verifies exact ready-ledger stable IDs/source, phoneme or explicit text override semantics, unique files, British metadata, speed/voice constraints, minimum nontrivial file size, exact bytes and SHA-256, and rejects omissions/unreviewed IDs.
- Added a synthetic positive + corrupted-hash negative self-test so artifact validation is independently testable without generating speech.
- Technical original Oxford 3000 coverage remains 3,308 / 3,308; all 41 reviewed marker/heteronym/uppercase candidates remain targeted rather than triggering wholesale regeneration.

**Remains**
- The 41-file replacement MP3 artifact still must be downloaded and passed through the strengthened validator before replacement audio is promoted to verified.
- Broader parenthetical/multiword listening QA and final optional stable-ID AudioPack assembly remain.
- Generate audio for Oxford 5000 only after additions themselves are verified; never regenerate the existing 3,308 wholesale.

**Blocker**
- No user-input blocker. Replacement output is simply not promoted until artifact inspection succeeds.

**Exact next action**
- Inspect the latest targeted pronunciation Actions artifact with the standalone validator, then record exact manifest/hash evidence for all 41 entries and only then assemble replacement candidates into the final AudioPack staging area.

## Lane 5 — Release engineering / CI / packaging / tests / documentation

**Advanced this run**
- Windows gate now batches the new Oxford second-pass validator and targeted-audio artifact validator self-test with the existing Tatoeba, gap resolver, Oxford ledger, pronunciation ledger, .NET build/self-tests, self-contained publish and published-EXE validation.
- This grouped checkpoint is intentionally used instead of launching separate expensive workflows for every small edit.
- Existing Windows packaging remains self-contained .NET 8 `win-x64`; no secrets or external service credentials were added.

**Remains**
- Confirm the final head Windows gate is green after the grouped five-lane changes.
- Continue a concise Windows 11/NVDA beta test plan while keeping automated claims separate from real user NVDA results.
- Keep THIRD_PARTY_NOTICES aligned whenever a reusable dependency/dataset decision changes.

**Blocker**
- None expected; any CI failure must be diagnosed as shared vs lane-local and must not freeze unrelated lanes.

**Exact next action**
- Inspect the final grouped Windows gate, fix only verified shared regressions, and retain a clean user-testable beta path without automatically sending builds.
