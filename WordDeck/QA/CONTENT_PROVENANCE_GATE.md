# WordDeck commercial content provenance gate

This directory contains the canonical machine-readable seam for the WordDeck commercial-content rights policy defined by `WD-MASS120-089-CONTENT-RIGHTS-PROVENANCE` and independently audited by `WD-MASS120-098-AUDIT-CONTENT-RIGHTS`.

`content_provenance_manifest.json` is intentionally empty at introduction time. An empty manifest does **not** clear existing Oxford-backed lexical/audio data, Tatoeba content, AI-assisted course assets, private books, or any other content family. It means no asset has yet been registered here as `CLEARED_PRODUCTION` under this contract.

Production rule: a public/commercial release inventory must be validated with `tools/validate_content_provenance.py --manifest ... --inventory ... --notices ...`. The validator defaults missing permissions to denial, requires exact SHA-256 identity, requires `CLEARED_PRODUCTION`, checks release channel/expiry/dependencies/review binding, and applies stricter origin-specific checks. A missing manifest record, hash drift, unresolved required notice, quarantined/private/internal/retired dependency, unknown/NC right, or unsupported release channel fails the gate.

The engineering V0.2 candidate remains an engineering evidence package and is not converted into a commercial-rights PASS by this change. In particular, this gate does not invent an Oxford license, Tatoeba/audio clearance, contributor assignment, voice right, or legal opinion. Those must be registered from real evidence before a commercial release inventory can pass.

The additional `review.reviewed_content_hash_sha256` field binds the rights/originality/source review to the exact bytes/text under review. Changing `content_hash_sha256` without re-review therefore fails deterministically.
