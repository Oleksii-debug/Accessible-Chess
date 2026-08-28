# Version 2 CBZ / 2CBZ encrypted-archive evidence boundary

ROLE=V2-CHESSBASE-FORMATS
UTC=2026-08-28
PARENT_PR=306
PARENT_SHA=e3c13d07a338d79764e71e4bef096900aa860cac

## Verdict

CBZ=BLOCKED
2CBZ=BLOCKED

This package qualifies filename recognition and immutable encrypted-source integrity only. It does not add password input, decrypt/extract invocation, a semantic decoder, or a support claim.

real_world_corpus_found=true
legally_reusable_acceptance_fixture_found=false
independent_semantic_oracle_found=false

## CBZ authoritative format evidence

ChessBase documentation describes `.cbz` as the encrypted/password-protected form of an archived ChessBase database. The official help also describes password-protected archive creation and the encrypted archive filename extension.

Primary references:

- https://help.chessbase.com/CBase/16/Eng/archive_database.htm
- https://help.chessbase.com/CBase/16/Eng/files_names_and_extensions.htm
- https://help.chessbase.com/CBase/18/Eng/password.htm

This is enough to recognize `.cbz` as an encrypted archive container. It is not enough to claim that Accessible Chess can decrypt or import it.

## 2CBZ real-world evidence and qualification limit

A real commercial UltraCorr2025 distribution uses `.2cbz` as a password-protected archive that yields the vendor's 2CBH-family database after extraction. The public distribution page is evidence that this extension exists in real-world ChessBase-family use:

- https://www.chessmail.com/ultracorr/UltraCorr2025.htm

The commercial/password-controlled corpus is not redistributed or copied into CI. No official general 2CBZ format specification was found in this qualification cycle, so the adapter labels the payload contract as unqualified. A real commercial example proves existence/topology evidence, not universal decoder semantics.

## Exact pinned backend evidence

Existing Version 2 CBV work pins external `antoyo/uncbv` at:

`3c18e8a7c6a30c21f945a1ab5462521c306dca57`

License: GPL-3.0. It remains an optional separately supplied backend and is not bundled by this package.

At that exact upstream commit:

- `.cbz` is recognized by the backend as an encrypted archive;
- `decrypt` converts the encrypted archive to CBV;
- `extract` can decrypt and then unpack it;
- upstream tests include `small.cbz`, `small2.cbz`, and `small3.cbz` and write the password to the child process through stdin.

The upstream CBZ fixture blob identities are:

- `tests/small.cbz` = `08bc5d6e53eecedc35e37d24cf29bbe0a5953839`
- `tests/small2.cbz` = `fe9a6360bb2341083328114cb966bf644ccc8061`
- `tests/small3.cbz` = `a7ac16b2a7b1cf2bcf9a970e44058aed1f16b2fa`

These prove backend mechanics at the pinned upstream revision. synthetic/upstream fixtures do not prove Product support.

## Current Accessible Chess blocker

Current parent Product blob:

`acs/cbv_extractor.py=0ff079754a963186daad47597e16d7fa3de32782`

Two fail-closed facts prevent a CBZ/2CBZ support claim:

1. `extract_cbv_external` accepts `.cbv` only and rejects `.cbz`/`.2cbz` before backend execution.
2. `_run_uncbv` launches the backend with `stdin=subprocess.DEVNULL`, while pinned upstream encrypted-archive handling obtains the password through interactive stdin.

Therefore merely adding `.cbz` recognition to the generic adapter must not activate the CBV extractor. The evidence tests require current encrypted extraction to remain `UNSUPPORTED_SOURCE` until a separately owned secure password/decrypt lifecycle is implemented and qualified.

## Integrity boundary

For `.cbz` and `.2cbz`, Accessible Chess may safely fingerprint the original encrypted archive as one opaque immutable source file. This records provenance and detects source mutation. It does not inspect or claim the decrypted payload.

The original encrypted source remains authoritative and read-only. Mutation after snapshot invalidates the evidence. No temporary decrypted material is created by this package.

## Missing security and acceptance gates

Promotion above BLOCKED requires all of the following as one evidence-backed chain:

- explicit password input boundary with no logging, persistence, traceback, command-line leakage, or accidental diagnostics;
- bounded stdin/stdout/stderr, timeout, cancellation and process termination behavior;
- bounded temporary decrypted CBV lifecycle with cleanup on success, failure, wrong password and cancellation;
- exact external backend identity, license/build provenance and mutation detection;
- legal real CBZ corpus and, independently, legal real 2CBZ corpus suitable for acceptance use;
- independent semantic oracle for games, metadata, comments and variations;
- canonical move legality validation through the existing Accessible Chess chess core;
- SOURCE -> DECRYPT/EXTRACT -> CANONICAL VALIDATION -> GAMETREE -> LIBRARY -> SEARCH -> OPEN -> EXPORT -> REOPEN -> INTEGRITY comparison;
- damaged/truncated archive, wrong password, resource-exhaustion and adversarial path cases;
- explicit loss accounting.

Until that chain exists, recognition is provenance metadata only and both formats remain BLOCKED.

## Ownership boundaries

This package does not modify Stage 1, Library/ACSDB implementation, CBH/CBV capability authority, the parent 2CBH/CBONE topology package, optional-backend configuration/trust ownership, password UI/storage, or any chess rules implementation. No commercial database bytes are added to the repository.
