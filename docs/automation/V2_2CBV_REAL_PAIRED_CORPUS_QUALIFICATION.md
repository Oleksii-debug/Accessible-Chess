# Version 2 — real paired 2CBV corpus qualification

ROLE: `V2-CHESSBASE-FORMATS`

LANE: `ACCESSIBLE-CHESS-V2-2CBV-REAL-PAIRED-CORPUS-QUALIFICATION-20260901`

UPSTREAM: PR #429 exact `6280d7d701330fc176d282387205d8c8183b3321`.

## Candidate

SV Mattnetz Berlin publicly offers the **Berliner Einzelmeisterschaft 2024 — M-Klasse** games for the first eight boards/all rounds in three side-by-side download forms:

- PGN;
- CBV;
- 2CBV.

Source page: https://www.sv-mattnetz-berlin.de/?cat=19

The page identifies the event as 30 March through 7 April 2024 and states that the downloadable files contain all games of the first eight boards. This is a real event corpus rather than a decoder self-fixture.

A second organization, Berliner Schachverband, independently publishes the same M-Klasse event as round-by-round PGN files (`R1` through `R9`).

Independent PGN source: https://www.berlinerschachverband.de/berliner-einzelmeisterschaft-m-klasse.html

This creates a materially stronger oracle design than a single publisher's 2CBV plus self-generated PGN: the event provenance can be cross-checked against an independent tournament publisher.

## Runtime-only exact-identity probe

`scripts/v2_2cbv_real_paired_corpus_probe.py` performs a bounded network evidence pass in CI:

1. downloads only the two public HTML source pages within a 2 MiB bound;
2. discovers the visible Mattnetz `PGN Datei alle Runden` and `2CBV Datei alle Runden` anchors without guessing filenames;
3. follows the public download targets under HTTPS with a 64 MiB per-response bound;
4. computes size/SHA-256 in memory only;
5. separately discovers and hashes the nine independent Berliner Schachverband M-Klasse PGNs;
6. writes only URL/final URL/size/SHA-256/content-type/provenance metadata to the CI report;
7. never writes downloaded chess payload bytes to repository files or upload artifacts.

A Google Drive/browser preview or other interstitial is not considered an exact 2CBV payload merely because the link is labelled 2CBV. Exact payload identity is qualified only if the final URL or Content-Disposition filename actually identifies a `.2cbv` object.

## Legal boundary

Both publishers intentionally expose files for public download. This establishes public availability, not a blanket redistribution licence.

No explicit repository/CI redistribution licence for the 2CBV bytes has been qualified in this package. Consequently:

- no downloaded 2CBV bytes are committed;
- no downloaded 2CBV bytes are uploaded as GitHub artifacts;
- no real source payload is copied into tests;
- the probe artifact contains metadata only.

If future terms or direct permission authorize retained fixture bytes, that can be evaluated in a separate owner-controlled package. Public download availability alone is not silently converted into redistribution permission.

## Semantic/oracle boundary

The independent Berliner Schachverband PGNs are useful expected-semantics evidence only after a real 2CBV reader exists and exact event coverage is compared. This package does not claim that two files are semantically identical simply because their labels name the same tournament.

Before support promotion, a future decoder acceptance must establish at least:

- exact 2CBV source SHA-256 and stable provenance;
- exact decoded game count;
- canonical legality/GameTree validation;
- ordered game identity against independently sourced event PGN;
- metadata/annotations/variations treatment with explicit loss policy where formats differ;
- atomic Library publication;
- Search/Open and PGN Export/Reopen equivalence;
- source integrity before/after decode;
- Windows runtime evidence.

## Capability truth

`2CBV=BLOCKED`

`decoder_qualified=false`

`semantic_acceptance_executed=false`

`support_promotion_allowed=false`

The value of this package is to turn a vague real-world lead into a bounded reproducible corpus/oracle evidence chain while preserving the support boundary.

No Stage1, chess core, GameTree, Library, Windows UI, CBZ/2CBZ security, Teacher/Classroom or package-release code is changed.
