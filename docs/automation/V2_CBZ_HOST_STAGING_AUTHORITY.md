# V2 CBZ host staging authority

Date: 2026-08-31

Base: PR #351 exact `00bb0c6b02bc1638ef8829abc0dc040a4b3a6db9`.

## Verdict

`CBZ=BLOCKED`

`2CBZ=BLOCKED`

`support_promotion_allowed=false`

No lawfully reusable real-world ChessBase CBZ with an automatable non-user-secret password and an independent expected PGN/GameTree oracle has been qualified. The pinned `uncbv` fixture remains mechanics evidence, not independent semantic acceptance. This package therefore does not activate CBZ import or infer any 2CBZ payload/decryption semantics.

## Engineering gap closed

PR #346 made stale marker-qualified CBZ workspaces safely recoverable, and PR #351 added a trusted Windows startup preflight over one explicit application-owned recovery root. The underlying extractor still placed its own private workspace under `output.parent`, so a future host could accidentally decrypt under a directory different from the root scanned on restart. A hard process exit could therefore leave proprietary extracted material outside the one recovery authority.

`acs/cbz_host_staging.py` adds a composition layer rather than a second extractor. One explicit recovery root now owns a marker-qualified outer staging lease. The existing `extract_cbz_external()` runs inside that lease. Its decrypted CBV and published extracted CBH family remain below the outer marker-qualified workspace while the canonical importer consumes them. Normal completion, error and cancellation remove the outer lease; after hard process termination the same PR #351 startup preflight can identify the stale dead-owner outer lease on the next application start.

## Password architecture

The host seam requests a password exactly once through a path-free `CbzPasswordRequest` contract. It requires masked entry, disallows persistence and disallows command-line use. The existing PR #324 extractor remains the only execution implementation and continues to send the password only through backend stdin, never argv/environment.

The provider currently returns Python `str`. The Product deliberately does **not** claim that immutable interpreter/provider memory can be wiped. The staging layer only drops its local reference as soon as the bounded context exits. A future concrete Windows password control may improve the host-memory story, but no false secure-memory claim is made here.

## Inherited security retained

The package reuses, rather than duplicates, the existing source/backend fingerprints, live decrypted-output size monitor, source/resource limits, bounded stdout/stderr, timeout, cancellation/kill, CBV traversal/case/symlink/reparse protections, atomic staged publication, stale marker validation and restart cleaner.

## Legal boundary

No DRM/encryption bypass, password cracking, foreign password, proprietary secret or commercial database content is used. No external GPL backend is added to the default package. Real semantic support remains blocked until exact lawful source bytes, explicit reuse provenance, automatable test password, independent PGN/GameTree oracle, canonical legality validation, atomic Library import and export/reopen equivalence all exist.
