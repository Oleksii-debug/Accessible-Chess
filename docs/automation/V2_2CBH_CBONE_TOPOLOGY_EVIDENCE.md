# Version 2 — 2CBH / CBONE topology evidence

Status: `2CBH=BLOCKED`, `CBONE=BLOCKED` for semantic import.

This package corrects source topology only. It does not add a decoder and it does not treat extension recognition, a synthetic fixture, or a source fingerprint as proof that games can be decoded correctly.

## Authoritative product lineage

- Repository: `Oleksii-debug/Accessible-Chess`
- Origin parent: merged PR `#302` at `0454f9e19854da9c2261bba4b5d64e688fa3b909`.
- Current integration synchronization point: PR `#295` at `958ae19cd91a135fd3f384d02a880c0ed1adfd10`.
- Architecture remains: external ChessBase source -> bounded adapter/backend -> canonical validated GameTree + metadata + provenance -> ACSDB/PGN.

## External evidence checked

Current ChessBase 18 documentation describes 2CBH as a format that uses fewer files than classic CBH. That is incompatible with treating the `.2cbh` primary as a complete single-file database family.

Source: `https://help.chessbase.com/CBase/18/Eng/new_data_format_2cbh.htm`

ChessBase database-format documentation describes CBONE differently: the whole database is stored in one `.cbone` file, specifically to make backup and transfer easier.

Source: `https://help.chessbase.com/CBase/17/Eng/database_formats.htm`

Public secondary evidence also shows real-world 2CBH installations with same-database sibling files such as `.2cba` and `.2cbg`. This is useful corroboration that 2CBH is multi-file, but it is not enough to define an exhaustive companion map or semantic decoder contract.

A real commercial large corpus also corroborates the topology: the UltraCorr2025 2CBH download page says its encrypted 2CBZ archive expands to a 2CBH database consisting of seven files. That corpus has more than 2.68 million games, including annotated games. It is password/commercial material and is therefore **not** used as a CI fixture, redistributed, or treated as an independent semantic oracle.

Source: `https://www.chessmail.com/UC-2025/Download-UC2025-newformat.html`

## Product correction

Before this package, `.2cbh` and `.cbone` shared `source_kind=single_file_database`.

After this package:

- `.2cbh` -> `multi_file_database_unqualified_topology`;
- `.cbone` -> `single_file_database`;
- both remain read-only and `decoder_available=false`;
- neither is safe to import semantically;
- 2CBH integrity capture fails closed instead of hashing only the primary and falsely presenting that as whole-family integrity;
- CBONE single-file fingerprinting remains allowed because its topology is documented as single-file, but that fingerprint does not promote decoder support.

## Why the 2CBH companion map is not guessed

Available documentation proves multi-file topology but does not provide a sufficiently qualified exhaustive component inventory suitable for a release integrity contract. Observing one or two sibling extensions is not enough. A complete family snapshot must not silently omit other authoritative files.

Therefore this package intentionally does not invent a `_2CBH_COMPONENT_EXTENSIONS` list from screenshots, forum posts, or synthetic names. The integrity gate stays closed until a real legal 2CBH corpus and a qualified companion map are available.

## Real-world acceptance boundary

`real_fixture_found=false`

`independent_semantic_oracle_found=false`

A future support promotion requires a legal real database, exact backend identity/license/build provenance, canonical legality validation, and a real source -> GameTree -> ACSDB -> search -> open -> PGN export -> reopen semantic comparison. Synthetic fixtures may test fail-closed mechanics but cannot establish format support.
