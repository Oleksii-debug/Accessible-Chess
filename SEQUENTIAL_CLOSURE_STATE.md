# Sequential closure state

Canonical plan: `ACCESSIBLE CHESS — SECTION PLAN ДО ПОВНІСТЮ ЗАВЕРШЕНОГО ПРОДУКТУ`  
Canonical Drive document: `https://docs.google.com/document/d/1ITsUBFwwETRICctcOWLd6atuMcCFZg6v5-wVFumIyxE/edit`  
Closure run date: 2026-10-09  
Current exact source: `work/owner-gameplay-section37-20261009` at `b0469e509aa37feea12c019e933a9493cb0f88ee`

## Rule

This registry follows the plan's canonical sequential-closure rule. A section is
`DONE` only when its acceptance requirements, integration, failure/recovery
evidence, and applicable accessibility/security/packaging evidence are present
on the exact source. External-only blockers are recorded separately; they are
never silently converted into `DONE`.

## Section 37 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable source registry: `docs/corpus/SECTION37_SOURCE_REGISTRY.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 37.1 | `PARTIAL` | Registry now records source URL, owner, format, rights, expected/actual SHA where bytes exist, and counts. It is not yet the plan's “large” all-format registry. |
| 37.2 | `PARTIAL` | Pinned CC0 Lichess source, deterministic 240-game curation policy, and project-owned 1200-game stress corpus are present. Diverse external PGN/EPD/FEN collections still need real download/readback. |
| 37.3 | `PARTIAL` | 24 Ukrainian project-authored booklets and 144 exercises are real and licensed. Independent third-party EPUB/HTML/TXT/PDF/DOCX/Markdown literature across the required genres is not cleared or bundled. |
| 37.4 | `BLOCKED` | Current evidence explicitly says no lawful genuine CBF+CBI fixture with independent semantic oracle; CBH/CBV/2CBH/CBONE real-file readback is likewise not pinned. |
| 37.5 | `DONE` | TEST_BUILD versus PUBLIC_RELEASE boundary, source-page-only handling, and project-owned notices are documented. |
| 37.6 | `DONE` | Source manifests, checksum fields, bounded download/verification path, safe temporary-workspace pattern, and fail-closed cleanup policy are present. |

### Evidence commands

The following source-level checks were run or are directly inspectable without
claiming physical NVDA acceptance:

```text
sha256(ac s/starter_content.py) = 8118eb8f9897e2f13ef029a533ba22dae2e1f66d8c73feba9dccd9bd4ccf623b
sha256(acs/starter_books_training_content.py) = b844c4e2cd6ae3394ddf007297a6f8229d6688144c159e39cc47e11963ff575a
starter release manifest: 24 booklets, 12 chapters each, 144 training exercises
real-source policy: 240-game deterministic sample from pinned CC0 Lichess source
CBF/CBI evidence: BLOCKED (no lawful fixture + independent semantic oracle)
```

The `ac s` spacing in the first display line is intentional plain-text
readability only; the canonical path is `acs/starter_content.py`.

## Ordered frontier

The next dependency-safe front is Section 38. Sections 38–53 remain pending
until their own acceptance evidence is produced. No later section is marked
`DONE` by this record, and no status is inferred from chat history or from a
single green test.
