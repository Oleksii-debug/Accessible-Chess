# Version 2 CBZ secure execution mechanics

ROLE=V2-CHESSBASE-FORMATS
UTC=2026-08-28
PARENT_PR=316
PARENT_SHA=982c5ccb1b20e958f11af2d48c921ff823f03f85

## Status

CBZ=BLOCKED
2CBZ=BLOCKED

This package closes one concrete file-service blocker only: it adds a bounded encrypted-CBZ execution primitive around the already pinned optional `uncbv` backend. It does not make CBZ a supported user feature and does not add a second ChessBase decoder.

## Exact upstream

The mechanical oracle is the already pinned external source:

- repository: `antoyo/uncbv`
- commit: `3c18e8a7c6a30c21f945a1ab5462521c306dca57`
- license: GPL-3.0
- encrypted fixture: `tests/small.cbz`, Git blob `08bc5d6e53eecedc35e37d24cf29bbe0a5953839`
- decrypted fixture oracle: `tests/decrypted_small.cbv`
- upstream fixture password: used only by the exact fixture CI path

The backend remains separately supplied and SHA-256 pinned through the existing `ExternalCbvExtractorConfig`. Nothing in this package downloads or bundles it.

## Security / file-service contract

`acs/cbz_extractor.py` accepts `.cbz` only. `.2cbz` remains rejected by the execution primitive.

The password boundary is deliberately narrow:

- password is validated and bounded to 1024 UTF-8 bytes;
- NUL, CR and LF are rejected;
- the backend receives the password only through stdin;
- password is never appended to argv;
- password is never copied into the child environment;
- password is not interpolated into exceptions or reports;
- the internal encoded `bytearray` is overwritten and cleared after stdin write.

Python limitation: the caller currently supplies a `str`. Python immutable string storage cannot be reliably wiped by this function. This is one reason the format remains BLOCKED pending the final user-facing secret-entry design.

Decrypt execution is bounded by the existing backend timeout and stdout/stderr caps. The decrypted CBV is monitored for a resource bound, must be a real regular file rather than a symlink/reparse point, and must begin with the exact CBV archive magic used by the pinned backend path. The encrypted source and backend are fingerprinted before work and reverified after decrypt and before publish.

The decrypted CBV is never written directly into final output. A private sibling workspace is created beside the empty trusted output directory. The existing `extract_cbv_external` performs the CBV list/path validation and extraction into a private staged directory. This package does not copy or reimplement its CBV parser/path inventory logic.

Only after the staged CBV extraction succeeds, source/backend identities still match, and cancellation is not requested does the wrapper publish the whole staged directory by same-filesystem directory replacement. If another process places content into the final directory before publish, publication fails closed and the new content is preserved rather than overwritten.

Normal success, validation failure, wrong password, source/backend mutation and cancellation paths clean the private workspace. Staged extracted files are therefore not exposed through the final path after failure.

## Cancellation boundary

Cancellation before or during the decrypt subprocess kills the backend. Cancellation after decrypt or after delegated CBV extraction prevents final publication and removes staged data.

The existing CBV extractor does not yet expose an interrupt token to terminate its own extraction subprocess mid-stage. This wrapper therefore provides atomic cancellation at stage boundaries, not fully interruptible cancellation throughout the delegated CBV extraction. That remains an explicit support blocker; this package does not silently claim otherwise.

## Crash-residue boundary

Normal Python paths clean private decrypted material, but an uncatchable interpreter/process/OS crash can leave the private sibling workspace. No startup crash-residue registry/scavenger is qualified in this package. CBZ support cannot be promoted until that recovery policy is addressed or a backend design removes the decrypted-file residue risk.

## Exact fixture mechanics gate

The dedicated CI checks out exact `antoyo/uncbv@3c18e8a7c6a30c21f945a1ab5462521c306dca57`, builds it from the pinned lockfile, hashes the resulting binary, and runs Accessible Chess against upstream `tests/small.cbz` using the upstream fixture password.

Success requires:

- the decrypted CBV SHA-256 to equal upstream `tests/decrypted_small.cbv`;
- every extracted file byte to equal the upstream `tests/small` oracle directory;
- one `.cbh` primary to exist;
- a wrong password to fail without publishing output or exposing the password.

This is stronger than a mock, but it is still an upstream fixture. It proves exact backend/password/staging mechanics only. It is not real-world semantic acceptance and does not satisfy the project rule that synthetic/upstream fixtures alone cannot establish format support.

## Remaining support blockers

`CBZ=BLOCKED` remains mandatory because there is still no legal reusable real-world CBZ corpus with an independent expected semantic oracle and no complete SOURCE -> DECRYPT/EXTRACT -> CANONICAL VALIDATION -> GAMETREE -> LIBRARY -> SEARCH -> OPEN -> EXPORT -> REOPEN -> INTEGRITY proof.

Further blockers are the immutable caller-string secret limitation, crash-residue recovery, mid-CBV-stage cancellation, user-facing Windows/NVDA password entry, explicit semantic loss accounting, and end-to-end Library/export/reopen equivalence.

`2CBZ=BLOCKED` is stricter: this primitive refuses `.2cbz`; its general decrypt/payload contract is still unqualified and cannot inherit CBZ semantics by filename analogy.

## Ownership boundaries

This package does not modify the active backend-trust-profile owner, PR #300 Windows trusted host, PR #295 CBH/CBV integration authority, parent #316 recognition/evidence contract, Library/ACSDB, chess core/GameTree rules, Stage1, backend packaging, password storage or capability status source of truth.
