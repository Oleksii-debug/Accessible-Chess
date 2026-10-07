# Section 0 convergence candidate

Status: **CANDIDATE — exact-head CI required before DONE**

This receipt converges the current Section 0 contract lineages without replacing the canonical chess core.

## Frozen ancestry

- canonical pre-Section-0 apex: `5854b528fbd3632cfa69553a70973123eaf14b54`
- authority-boundary lineage (#2329): `c61fbc8f1381ddec05109532f907595c2a7c9aaf`
- fail-closed ImportReport lineage (#2330): `3dcdf4463ebec205ca202f1faee58130d7ddbd4e`
- capability-matrix lineage (#2328): `2ca2d3f78b0070ce7c0382c64729d3457136900e`
- two-parent convergence receipt: `0bc9dd57d41f047e0c259af3dcf8b2791cac23d3`
  - first parent: `3dcdf4463ebec205ca202f1faee58130d7ddbd4e`
  - second parent: `2ca2d3f78b0070ce7c0382c64729d3457136900e`

The merge preserves both histories. No force-push or replay of overlapping runtime authorities is used.

## Section 0 acceptance mapping

- **0.1 canonical Position / Move / SAN / FEN / GameTree / Game / provenance authority** — bound by `docs/FORMAT_AUTHORITY_BOUNDARIES.md` and executable contract tests.
- **0.2 application boundaries** — format publication is required to pass through existing application/chess authorities; format code does not own legality.
- **0.3 capability matrix** — `acs.format_capabilities.FORMAT_CAPABILITIES` is the typed authority with read/edit/write/round-trip statuses. 2CBV and 2CBZ remain explicitly BLOCKED rather than being promoted from recognition evidence.
- **0.4 canonical lineages** — #2329/#2330 and #2328 are joined by the two-parent convergence receipt above; this branch is the Section 0 convergence candidate.
- **0.5 malformed/partial input** — shared `ImportReport` validates exact passive provenance/record shapes before registry observation and preserves explicit FULL/PARTIAL/DAMAGED/WARNING evidence.

## No-overclaim boundary

Section 0 does not claim full CBF/CBI, 2CBV, 2CBZ, CBZ, 2CBH or CBONE semantic support. Missing lawful fixtures, independent semantic oracles, decryption/decoder evidence, or external backend qualification remain explicit BLOCKED/PARTIAL capability state.

## Qualification required

The dedicated Section 0 convergence workflow must pass on Ubuntu 22.04 and Windows 2025 at the exact PR head. Queued or pending Actions are not PASS. A later head invalidates earlier exact-head qualification and must be re-qualified.
