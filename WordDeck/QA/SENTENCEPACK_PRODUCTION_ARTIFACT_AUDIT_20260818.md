# SentencePack production artifact audit — 2026-08-18

Scope: downloaded GitHub Actions artifact `WordDeck-Tatoeba-EN-UA-Attributed-SentencePack` from successful run `32065274247`, artifact id `9299729781`, digest `sha256:2019dc82e5aeb4b68b8f801159bba65c6510fb68bf3d4272b93d817bb3ce9d19`.

This is a QA evidence record, not a new corpus build and not a claim about later workflow outputs.

## Corpus and provenance

- Pack ID: `tatoeba-en-uk-ccby-20260817`.
- License: `CC BY 2.0 FR`.
- Accepted EN-UA sentence pairs: **207,578**.
- Current embedded Oxford IDs covered: **3,120 / 3,308**.
- Sentences with at least two indexed target IDs: **190,315**.
- Sentences with at least three indexed target IDs: **160,058**.
- Quality-flagged accepted sentences: **53,612**.
- Accepted sentences missing per-side author attribution: **0**.

## Distribution and runtime measurements from the artifact

- Raw JSON: **245,812,895 bytes**.
- Gzip SentencePack: **19,906,951 bytes** — **91.9% reduction**.
- SQLite database measured by the production diagnostics: **72,400,896 bytes**.
- Fresh-process representative SQLite query: **126 ms**, **1,141** returned sentences, about **2.17 MB managed-memory delta** and **24.46 MB working-set delta**.
- Actual Sentence Coach runtime path: metadata/open **79 ms**; one-target full-scope coverage **33 ms / 3,120 IDs**; two-target same-scope coverage **56 ms / 3,114 IDs**; representative one-target query **179 ms / 3,075 sentences**; representative two-target intersection **13 ms / 238 sentences**; measured runtime delta about **49.92 MB working set**.

The same artifact also contains the older eager GZIP diagnostic: **4,798 ms** load, about **553.87 MB managed-memory delta** and **644.43 MB working-set delta**. This remains useful as a regression baseline demonstrating why normal runtime must continue to prefer the disk-backed SQLite corpus.

## Coverage-gap boundary

The audited run predates the current workflow's exported `resolved-sentence-coverage-gaps.tsv`, `sentence-gap-exact-occurrence.tsv` and `sentence-gap-summary.json`. Therefore this audit deliberately does **not** invent exact-present/exact-absent counts for the 114 ordinary gaps.

Current production workflow now computes those files fail-closed from the attributed EN-UA pairs before pack creation. Until a current workflow artifact containing them is inspected, exact-present ordinary gaps must continue to be treated as matcher/index QA candidates and exact-absent gaps must not be assumed to require morphology.

## Regression rule

Do not replace SQLite with eager JSON/GZIP loading for normal Sentence Coach use. Any future storage/index change must preserve corpus provenance and compare against these measured production baselines on the same 207,578-sentence scope.
