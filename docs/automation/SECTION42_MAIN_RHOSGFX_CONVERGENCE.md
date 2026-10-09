# Section 42 — preserved original CC0 piece pack (main convergence)

- Scope: 42.1 genuine Lichess RhosGFX CC0-1.0 originals, each upstream blob and byte count preserved from protected #2494 without changes.
- Source revision: lichess-org/lila `f5b261e3d8ece6f511484e398cb8d81e37735bea`; original rights file blob `def9deca8bceae28cf83d2074a3b09534ae88f6f`.
- Manifest and all 12 SVGs are checked against immutable expected SHA1 blob hashes and exact original lengths before offline derivation.
- Existing conversion tool creates 48 PNG/lossless WebP assets with SHA-256 receipts; actual built artifacts require a successful exact-head CI job, NOT a source-only assertion.
- Both original-source negative/recovery source checks and actual raster derivation execute on PR into current main using `.github/workflows/section42-original-art-main.yml`.
- No changes to FEN, rules, GameTree, user preferences, any existing release pack, or third-party rights boundaries.
- Owner's Section 42 42.2–42.6 visual board wiring, Windows/Web, recovery, keyboard/UIA and Section 41 hard dependency remain open. **NO SECTION42_DONE / NO release acceptance** until independent exact-commit evidence and follow-up integration.
