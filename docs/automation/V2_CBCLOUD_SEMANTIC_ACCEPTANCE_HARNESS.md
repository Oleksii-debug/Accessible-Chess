# V2 CBCLOUD semantic acceptance harness

ROLE: `V2-CHESSBASE-FORMATS`

Ownership: `ACCESSIBLE-CHESS-V2-CBCLOUD-SEMANTIC-ACCEPTANCE-HARNESS-20260831`

Parent: PR #404 exact `a1b88d947b526d86c6a2dbdbcce32c4b4e4b0830`.

## Verdict

`CBCLOUD=BLOCKED`.

This package does **not** decode CBCLOUD, does not register `.cbcloud` in the Product importer, does not contact ChessBase cloud services, and does not claim any companion suffix or binary role. It adds a fail-closed semantic acceptance harness for a future lawful real four-file family and independently qualified reader.

Synthetic tests prove the harness contract only. They cannot promote CBCLOUD support.

## Why this successor exists

PR #404 qualified only the local-file boundary:

- `.cbcloud` is a documented local/offline-capable ChessBase database representation;
- one CBCLOUD database consists of four files;
- the four files can carry the same game data as CBH while omitting CBH player/tournament index files;
- the normative identities and binary roles of the three companions remain unqualified;
- no lawful reusable authentic four-file corpus, pinned reader or independent exact-byte semantic oracle is currently qualified.

The next safe engineering step is therefore not a decoder guess. It is a machine gate that is ready to evaluate a future real candidate without changing those facts.

## Exact-family evidence model

A real acceptance manifest must provide exactly four `CbcloudFamilyMemberEvidence` entries. Each entry contains only:

- exact leaf filename;
- exact SHA-256.

No `role`, guessed suffix map or universal component rule exists in the acceptance model. Exactly one member must end in `.cbcloud`; all four filenames must be case-insensitively unique and must be plain leaf names on both POSIX and Windows path syntax.

The four manifest filenames describe **one exact acceptance corpus**, not the CBCLOUD specification.

The manifest additionally requires:

- pinned backend name;
- exact lowercase 40-hex backend commit;
- SPDX license identity;
- HTTPS license evidence;
- HTTPS family-rights evidence;
- explicit `family_automated_use_permitted=true`;
- exact independent PGN oracle SHA-256;
- HTTPS oracle provenance;
- exact expected game count;
- exact acceptance protocol identity.

## Fail-closed execution contract

`qualify_cbcloud_candidate()`:

1. requires the submitted primary to be the exact manifest-bound `.cbcloud` member;
2. fingerprints all four exact files with the existing read-only `import_contract.fingerprint()` path/symlink/reparse/race protections;
3. rejects any missing file, wrong digest or wrong manifest identity before candidate execution;
4. passes the complete four-file immutable family to an injected future reader without assigning semantic roles to companions;
5. accepts only canonical `PgnGame` output;
6. re-fingerprints **all four files** after candidate execution, including candidate-error paths, and invalidates all output if any member changes/disappears;
7. bounds accepted game count and independent PGN oracle bytes;
8. replays every decoded game through canonical `validate_game_legality()`;
9. parses the independent oracle only through canonical `parse_games()`;
10. compares ordered canonical `record_digest` identities;
11. exports decoded games through canonical PGN serialization, reopens them, revalidates legality and requires exact canonical record identity.

Candidate exceptions are converted to bounded acceptance errors; private backend exception text is not exposed.

The report deliberately has no `supported` or `safe_to_import` property.

## Current Product boundary

PR #404 intentionally leaves `.cbcloud` outside `chessbase_adapter.py`. This harness does not change that. A synthetic harness PASS therefore coexists with:

- Product filename recognition: not enabled;
- Product decoder: not available;
- runtime importer registration: absent;
- Library publication: absent;
- support promotion: forbidden.

This is deliberate. The project must first obtain authentic lawful evidence and a real reader.

## Real promotion gate

A future CBCLOUD support package may consume this harness only after it has all of the following:

1. authentic complete four-file CBCLOUD bytes with stable exact hashes;
2. explicit lawful automated-use/CI rights for those exact bytes;
3. an evidence-qualified exact four-file set for that corpus without pretending it is a universal suffix map;
4. a pinned licensed reader that actually decodes those bytes;
5. an independent PGN/GameTree oracle tied to the same exact family;
6. a real PASS through this harness;
7. a separately reviewed bounded Product reader/execution seam;
8. canonical atomic ACSDB import with provenance;
9. Library/Search/Open and PGN Export/Reopen/Integrity equivalence;
10. applicable Windows runtime proof before user-facing activation.

Until those gates pass: `CBCLOUD=BLOCKED`, `support_promotion_allowed=false`, `NVDA_VERIFIED=NO`, `VERSION2_WINDOWS_ZIP=NO`.
