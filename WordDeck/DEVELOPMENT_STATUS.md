# WordDeck development checkpoint

Last updated: 2026-08-18
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

Verified baseline remains Recall + independent Spelling + Adaptive Coach + Sentence Spelling. Do not claim real NVDA verification until the user tests an actual Windows build with NVDA.

## Lane 1 — Core app / Recall / Spelling / accessibility

**Advanced this run**
- Audited shared deck dialogs used by Recall and Spelling and hardened keyboard/UIA behavior without changing deck semantics.
- Name and destination controls now have explicit logical Tab indices, concise accessible descriptions, and labels/panels are explicitly non-Tab stops.
- Enter remains dialog confirmation and Escape remains cancellation; initial focus still lands deterministically on the editable name or destination combo.
- Identified a separate persistence-hardening target: JSON reload of `SpellingState` should explicitly re-wrap nested dictionaries with case-insensitive comparers, matching the stronger Recall normalization pattern.

**Remains**
- Implement and regression-test case-insensitive comparer restoration for Spelling state after JSON reload.
- Continue keyboard-only focus restoration and error-path review in Spelling/Sentence forms.

**Blocker**
- None. Real NVDA verification still requires a user test of an actual Windows build.

**Exact next action**
- Normalize all reloaded Spelling dictionaries/inner stats maps to `OrdinalIgnoreCase` and add restart/recovery tests using mixed-case dictionary/entry IDs.

## Lane 2 — Sentence Coach / corpus / coverage / UI / performance

**Advanced this run**
- Audited the production attributed SentencePack workflow and found a concrete release-packaging gap: it builds the low-memory SQLite corpus but the uploaded production artifact currently omits the `.sqlite` file.
- Added `tools/validate_sentencepack_release_bundle.py`, a fail-closed development/release validator using only Python standard library `sqlite3`, `gzip` and JSON.
- The validator requires a non-empty `.sqlite`, `.json.gz`, provenance manifest and coverage report; validates SQLite schema metadata (`schema_version=2`, `en` -> `uk`, pack/license/provenance), non-empty sentence/target tables, gzip JSON readability, and equality of coverage counts to SQLite counts.
- Its self-test also proves that a bundle without SQLite is rejected, preventing accidental regression to the previously measured high-memory eager-GZIP runtime path.

**Remains**
- Add the actual production SQLite file to the attributed SentencePack uploaded artifact and run the new validator against that real bundle.
- Inspect the current production `sentence-gap-summary.json` to record exact-present vs exact-absent counts for the 114 ordinary single-surface gaps; exact-present rows remain matcher/index QA first.

**Blocker**
- No user-input blocker. Current production artifact packaging is not release-complete until SQLite is included.

**Exact next action**
- Patch the attributed SentencePack workflow upload list to include the `.sqlite` companion and validate the real artifact with the new release-bundle validator; then continue gap classification.

## Lane 3 — Oxford 5000 + Oxford 3000 translation QA

**Advanced this run**
- Source-checked Oxford 5000 additions `ox5000-add-0121` through `ox5000-add-0140` against the current Oxford 3000/5000 list and corresponding OALD headwords on 2026-08-18.
- Added staged fail-closed slice `QA/oxford5000_additions_second_pass_0121_0140.tsv`, all 20 rows marked `verified` only after POS/CEFR/source-row consistency and dictionary-sense review.
- Widened translations where the lexical entry materially requires it, including `assault`, `assemble`, `assembly`, `assert`, `attachment`, `attribute` and `attorney`; no POS/sense rows were collapsed.
- Existing generic second-pass validator is now invoked in grouped Windows CI for exact IDs 0121-0140 in addition to the earlier 0101-0120 slice.

**Remains**
- Source-check additions 0141-0200, then merge a coherent reviewed 0101-0200 batch into the canonical additions ledger only when unresolved rows in that staged batch are zero.
- Continue Oxford 3000 semantic QA independently; current broader backlog remains unresolved and is not claimed complete.

**Blocker**
- None. Semantic QA remains fail-closed and independent of Core/Sentence/Audio work.

**Exact next action**
- Review additions 0141-0160 next, preserving POS/sense distinctions and source evidence, then continue through 0200 before canonical promotion.

## Lane 4 — British Audio / AudioPack / pronunciation QA

**Advanced this run**
- Reconfirmed that all 17 heteronym/sense-sensitive rows and five uppercase candidates have already been source-resolved in the dedicated 2026-08-18 QA records; the remaining blocker is artifact-level verification, not lexical mapping.
- Added `tools/build_audiopack_manifest.py`, using only Python standard-library hashing/JSON for release tooling; runtime remains independent of Python/Kokoro/API/network.
- The builder produces deterministic `worddeck-audiopack-v1` metadata keyed strictly by stable entry ID, with file name, exact byte count and SHA-256 for every MP3; it rejects duplicate/blank IDs, empty packs and suspiciously small MP3s.
- A synthetic self-test proves deterministic output and fail-closed rejection of undersized audio.

**Remains**
- Download and validate the latest 41-file targeted replacement artifact before any replacement is promoted.
- Merge only verified replacements with the original 3,308 stable-ID files, then build the final AudioPack manifest and notices.
- Generate new audio only for verified Oxford 5000 additions; never regenerate all existing Oxford 3000 audio wholesale.

**Blocker**
- No user-input blocker. Targeted replacement MP3 artifact still needs manifest/hash inspection.

**Exact next action**
- Run the strengthened targeted-artifact validator on the 41 replacements and, if clean, stage those files over the verified base pack and build the canonical AudioPack manifest.

## Lane 5 — Release engineering / CI / packaging / tests / documentation

**Advanced this run**
- Updated the grouped Windows gate rather than adding separate expensive workflows.
- The gate now self-tests the SentencePack release-bundle validator and AudioPack manifest builder, and validates Oxford second-pass IDs 0121-0140 alongside the existing 0101-0120, Tatoeba, gap, pronunciation, .NET build/self-tests, self-contained publish and published-EXE validation.
- No secrets, service credentials or new runtime dependencies were introduced; self-contained Windows packaging remains .NET 8 `win-x64`.

**Remains**
- Confirm the final grouped Windows gate is green after this run's five-lane changes.
- Patch production SentencePack artifact contents to include SQLite and retain compatibility JSON.GZ as interchange/fallback rather than the normal low-memory runtime path.
- Continue concise Windows 11/NVDA beta instructions while keeping automated accessibility claims separate from real user testing.

**Blocker**
- None expected. Any CI failure must be classified as shared vs lane-local and must not freeze unaffected lanes.

**Exact next action**
- Inspect the grouped Windows gate for this checkpoint; fix only verified regressions, then continue lane-local work without sending routine builds.
